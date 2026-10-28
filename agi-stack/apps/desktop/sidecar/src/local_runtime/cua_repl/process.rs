use super::{config::RuntimeConfig, kernel::FRAME_LIMIT};
use serde_json::{Value, json};
use std::{path::Path, process::Stdio, time::Duration};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub(super) async fn execute(config: &RuntimeConfig, params: &Value) -> Result<Value, String> {
    let executable = params["executable"]
        .as_str()
        .ok_or("repl_process_executable_required")?;
    // macOS sh is a launcher that execs bash. Enter bash in POSIX mode directly
    // rather than broadening the sandbox's process-exec grant.
    let posix_shell = cfg!(target_os = "macos") && executable == "/bin/sh";
    let executable = Path::new(if posix_shell { "/bin/bash" } else { executable })
        .canonicalize()
        .map_err(|_| "repl_process_executable_missing")?;
    let sandbox = config.sandbox.clone();
    if let Some(cwd) = params["cwd"].as_str() {
        let cwd = Path::new(cwd)
            .canonicalize()
            .map_err(|_| "repl_process_cwd_invalid")?;
        if !cwd.starts_with(&sandbox.workspace)
            && sandbox.profile
                != super::super::authority_store::DesktopPermissionProfile::FullAccess
        {
            return Err("repl_process_cwd_forbidden".into());
        }
        // Permission roots remain fixed. cwd cannot widen filesystem access.
        let mut command = sandbox.command(&executable)?;
        if posix_shell {
            command.arg("--posix");
        }
        command.current_dir(&cwd);
        return run(command, params).await;
    }
    let mut command = sandbox.command(&executable)?;
    if posix_shell {
        command.arg("--posix");
    }
    run(command, params).await
}

async fn run(mut command: tokio::process::Command, params: &Value) -> Result<Value, String> {
    let arguments = params["args"]
        .as_array()
        .ok_or("repl_process_arguments_required")?;
    if arguments.len() > 1024 {
        return Err("repl_process_arguments_too_large".into());
    }
    for argument in arguments {
        command.arg(argument.as_str().ok_or("repl_process_argument_invalid")?);
    }
    if let Some(env) = params["env"].as_object() {
        for (key, value) in env {
            if key.contains('=') || key.contains('\0') || key == "HOME" || key == "TMPDIR" {
                return Err("repl_process_environment_invalid".into());
            }
            command.env(
                key,
                value.as_str().ok_or("repl_process_environment_invalid")?,
            );
        }
    }
    let timeout = params["timeoutMs"]
        .as_u64()
        .unwrap_or(30_000)
        .clamp(1, 300_000);
    let input = params["input"].as_str().unwrap_or("").as_bytes().to_vec();
    if input.len() > FRAME_LIMIT {
        return Err("repl_process_input_too_large".into());
    }
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| "repl_process_spawn_failed")?;
    let mut stdin = child.stdin.take().ok_or("repl_process_stdin_missing")?;
    let stdout = child.stdout.take().ok_or("repl_process_stdout_missing")?;
    let stderr = child.stderr.take().ok_or("repl_process_stderr_missing")?;
    let operation = async {
        let write = async {
            stdin.write_all(&input).await?;
            stdin.shutdown().await
        };
        let read = |stream: Box<dyn tokio::io::AsyncRead + Unpin + Send>| async move {
            let mut bytes = Vec::new();
            stream
                .take((FRAME_LIMIT + 1) as u64)
                .read_to_end(&mut bytes)
                .await?;
            Ok::<_, std::io::Error>(bytes)
        };
        let (_, out, err) = tokio::try_join!(write, read(Box::new(stdout)), read(Box::new(stderr)))
            .map_err(|_| "repl_process_io_failed")?;
        if out.len() > FRAME_LIMIT || err.len() > FRAME_LIMIT {
            return Err("repl_process_output_too_large");
        }
        let status = child.wait().await.map_err(|_| "repl_process_wait_failed")?;
        Ok(
            json!({"stdout":String::from_utf8_lossy(&out),"stderr":String::from_utf8_lossy(&err),"exitCode":status.code()}),
        )
    };
    tokio::time::timeout(Duration::from_millis(timeout), operation)
        .await
        .map_err(|_| "repl_process_timeout")?
        .map_err(str::to_string)
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::super::sandbox::Sandbox;
    use super::*;
    use crate::local_runtime::authority_store::DesktopPermissionProfile;

    #[tokio::test]
    async fn cancelling_a_managed_process_reaps_the_child() {
        let root =
            std::env::temp_dir().join(format!("memstack-repl-process-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let root = root.canonicalize().unwrap();
        let runtime = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../build/cua-repl")
            .canonicalize()
            .unwrap();
        let node = runtime.join("bin/node");
        let config = RuntimeConfig {
            _temporary_owner: None,
            executable: node.clone(),
            entrypoint: runtime.join("src/cli.mjs"),
            artifact_root: root.join("artifacts"),
            sandbox: Sandbox {
                profile: DesktopPermissionProfile::WorkspaceWrite,
                workspace: root.clone(),
                temporary: root.clone(),
                runtime,
                protected: vec![],
                immutable: vec![],
                module_roots: vec![],
            },
        };
        let job = tokio::spawn(async move {
            execute(&config,&json!({"executable":node,"args":["-e","require('node:fs').writeFileSync('child.pid',String(process.pid));setTimeout(()=>{},30000)"]})).await
        });
        let pid = tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                if let Ok(value) = tokio::fs::read_to_string(root.join("child.pid")).await {
                    if let Ok(pid) = value.parse::<i32>() {
                        break pid;
                    }
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        job.abort();
        let _ = job.await;
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                // SAFETY: signal zero only queries the fixture child process.
                if unsafe { libc::kill(pid, 0) } == -1 {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("cancelled managed process remained alive");
        std::fs::remove_dir_all(root).unwrap();
    }
}
