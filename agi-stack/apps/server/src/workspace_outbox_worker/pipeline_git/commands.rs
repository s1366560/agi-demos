use super::*;

pub(in crate::workspace_outbox_worker::pipeline_git) async fn run_git_command_owned(
    cwd: &Path,
    args: Vec<String>,
    env: &[(String, String)],
    timeout_seconds: u64,
) -> CoreResult<GitCommandOutput> {
    let arg_refs: Vec<&str> = args.iter().map(String::as_str).collect();
    run_git_command(cwd, &arg_refs, env, timeout_seconds).await
}

pub(in crate::workspace_outbox_worker) async fn run_git_command(
    cwd: &Path,
    args: &[&str],
    env: &[(String, String)],
    timeout_seconds: u64,
) -> CoreResult<GitCommandOutput> {
    let mut command = tokio::process::Command::new("git");
    command
        .args(args)
        .current_dir(cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    let output = tokio::time::timeout(Duration::from_secs(timeout_seconds), command.output())
        .await
        .map_err(|_| {
            CoreError::Storage(format!(
                "git {} timed out after {timeout_seconds}s",
                args.join(" ")
            ))
        })?
        .map_err(|err| {
            CoreError::Storage(format!("git {} failed to start: {err}", args.join(" ")))
        })?;
    Ok(GitCommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

async fn run_git_command_with_stdin(
    cwd: &Path,
    args: &[&str],
    env: &[(String, String)],
    timeout_seconds: u64,
    stdin_text: &str,
) -> CoreResult<GitCommandOutput> {
    let mut command = tokio::process::Command::new("git");
    command
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    let mut child = command.spawn().map_err(|err| {
        CoreError::Storage(format!("git {} failed to start: {err}", args.join(" ")))
    })?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(stdin_text.as_bytes())
            .await
            .map_err(|err| {
                CoreError::Storage(format!("git {} stdin failed: {err}", args.join(" ")))
            })?;
    }
    let output = tokio::time::timeout(
        Duration::from_secs(timeout_seconds),
        child.wait_with_output(),
    )
    .await
    .map_err(|_| {
        CoreError::Storage(format!(
            "git {} timed out after {timeout_seconds}s",
            args.join(" ")
        ))
    })?
    .map_err(|err| CoreError::Storage(format!("git {} failed: {err}", args.join(" "))))?;
    Ok(GitCommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

pub(in crate::workspace_outbox_worker) async fn short_git_head(
    cwd: &Path,
    env: &[(String, String)],
) -> CoreResult<String> {
    let head = run_git_command(cwd, &["rev-parse", "--short", "HEAD"], env, 60).await?;
    if head.exit_code == 0 {
        Ok(head.stdout.trim().to_string())
    } else {
        Ok("unknown".to_string())
    }
}

pub(in crate::workspace_outbox_worker::pipeline_git) async fn git_blob_hash(
    cwd: &Path,
    text: &str,
    env: &[(String, String)],
) -> CoreResult<String> {
    let hash = run_git_command_with_stdin(cwd, &["hash-object", "--stdin"], env, 60, text).await?;
    if hash.exit_code == 0 {
        Ok(hash.stdout.trim().to_string())
    } else {
        Ok(format!("git_hash_failed:{}", compact_git_error(&hash)))
    }
}

pub(in crate::workspace_outbox_worker) async fn current_worktree_dirty_signature(
    cwd: &Path,
) -> CoreResult<Option<String>> {
    if !cwd.exists() {
        return Ok(None);
    }
    let env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    let dirty = run_git_command(cwd, &["status", "--porcelain"], &env, 60).await?;
    if dirty.exit_code != 0 || dirty.stdout.trim().is_empty() {
        return Ok(None);
    }
    git_blob_hash(cwd, &dirty.stdout, &env).await.map(Some)
}

pub(in crate::workspace_outbox_worker::pipeline_git) async fn create_git_askpass_script(
) -> CoreResult<PathBuf> {
    let path = std::env::temp_dir().join(format!("memstack-git-askpass-{}.sh", generate_uuid_v4()));
    tokio::fs::write(
        &path,
        "#!/bin/sh\ncase \"$1\" in\n*Username*) printf '%s\\n' \"${GIT_USERNAME:-x-access-token}\" ;;\n*) printf '%s\\n' \"$GIT_TOKEN\" ;;\nesac\n",
    )
    .await
    .map_err(|err| {
        CoreError::Storage(format!(
            "failed to write git askpass script {}: {err}",
            path.display()
        ))
    })?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = tokio::fs::metadata(&path)
            .await
            .map_err(|err| {
                CoreError::Storage(format!(
                    "failed to stat git askpass script {}: {err}",
                    path.display()
                ))
            })?
            .permissions();
        permissions.set_mode(0o700);
        tokio::fs::set_permissions(&path, permissions)
            .await
            .map_err(|err| {
                CoreError::Storage(format!(
                    "failed to chmod git askpass script {}: {err}",
                    path.display()
                ))
            })?;
    }
    Ok(path)
}

pub(in crate::workspace_outbox_worker) fn compact_git_error(result: &GitCommandOutput) -> String {
    let text = if result.stderr.trim().is_empty() {
        result.stdout.trim()
    } else {
        result.stderr.trim()
    };
    if text.is_empty() {
        return format!("git exited with {}", result.exit_code);
    }
    compact_text(text, 1200)
}

pub(in crate::workspace_outbox_worker::pipeline_git) fn is_non_fast_forward_push_rejection(
    result: &GitCommandOutput,
) -> bool {
    let text = format!("{}\n{}", result.stdout, result.stderr).to_ascii_lowercase();
    text.contains("non-fast-forward")
        || text.contains("fetch first")
        || text.contains("updates were rejected")
        || text.contains("tip of your current branch is behind")
        || text.contains("not possible to fast-forward")
}

pub(in crate::workspace_outbox_worker::pipeline_git) fn is_unrelated_history_merge_rejection(
    result: &GitCommandOutput,
) -> bool {
    let text = format!("{}\n{}", result.stdout, result.stderr);
    text.to_ascii_lowercase()
        .contains("refusing to merge unrelated histories")
        || text.contains("拒绝合并无关的历史")
}
