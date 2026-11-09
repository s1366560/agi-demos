use super::config::RuntimeConfig;
use serde_json::{json, Value};
use std::process::Stdio;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout},
};

pub(super) const FRAME_LIMIT: usize = 16 * 1024 * 1024;

pub(super) struct Kernel {
    _config: RuntimeConfig,
    pub child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    frame: Vec<u8>,
}

impl Kernel {
    pub async fn start(config: &RuntimeConfig) -> Result<Self, String> {
        // Inherit only for local debugging. CI captures stderr; a full pipe
        // blocks the Node process before it writes the ready frame.
        let stderr = if cfg!(test) && std::env::var_os("CI").is_none() {
            Stdio::inherit()
        } else {
            Stdio::null()
        };
        let mut child = config
            .sandbox
            .command(&config.executable)?
            .arg("--experimental-vm-modules")
            .arg("--max-old-space-size=256")
            .arg(&config.entrypoint)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(stderr)
            .spawn()
            .map_err(|_| "repl_kernel_spawn_failed")?;
        let stdin = child.stdin.take().ok_or("repl_kernel_stdin_missing")?;
        let stdout = BufReader::new(child.stdout.take().ok_or("repl_kernel_stdout_missing")?);
        let mut kernel = Self {
            _config: config.clone(),
            child,
            stdin,
            stdout,
            frame: Vec::new(),
        };
        let ready = tokio::time::timeout(std::time::Duration::from_secs(10), kernel.read())
            .await
            .map_err(|_| "repl_kernel_start_timeout")??;
        if ready != json!({"type":"ready","protocolVersion":1}) {
            return Err("repl_kernel_protocol_mismatch".into());
        }
        Ok(kernel)
    }

    pub async fn send(&mut self, message: &Value) -> Result<(), String> {
        let mut bytes = serde_json::to_vec(message).map_err(|_| "repl_invalid_request")?;
        if bytes.len() > FRAME_LIMIT {
            return Err("repl_request_too_large".into());
        }
        bytes.push(b'\n');
        self.stdin
            .write_all(&bytes)
            .await
            .map_err(|_| "repl_kernel_transport_closed".into())
    }

    pub async fn read(&mut self) -> Result<Value, String> {
        // read_until alone permits an unbounded allocation from a compromised interpreter.
        loop {
            let bytes = self
                .stdout
                .fill_buf()
                .await
                .map_err(|_| "repl_kernel_read_failed")?;
            if bytes.is_empty() {
                return Err("repl_kernel_exited".into());
            }
            let end = bytes.iter().position(|byte| *byte == b'\n');
            let count = end.map_or(bytes.len(), |index| index + 1);
            if self.frame.len() + count > FRAME_LIMIT {
                return Err("repl_output_too_large".into());
            }
            self.frame.extend_from_slice(&bytes[..count]);
            self.stdout.consume(count);
            if end.is_some() {
                return serde_json::from_slice(&std::mem::take(&mut self.frame))
                    .map_err(|_| "repl_invalid_protocol_frame".into());
            }
        }
    }
}

impl Drop for Kernel {
    fn drop(&mut self) {
        let _ = self.child.start_kill();
    }
}
