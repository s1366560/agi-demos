use std::error::Error;
use std::process::Stdio;
use std::time::Duration;

use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use serde_json::{Value, json};
use sha2::{Digest as _, Sha256};
use tempfile::TempDir;
use tokio::io::{AsyncBufReadExt as _, AsyncWriteExt as _, BufReader};
use tokio::net::TcpListener;
use tokio::process::Command;
use tokio::time::timeout;

const STARTUP_TIMEOUT: Duration = Duration::from_secs(45);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(40);

#[tokio::test]
async fn desktop_control_initializes_base_bcs_before_workspace_extensions()
-> Result<(), Box<dyn Error>> {
    let fixture = DesktopControlFixture::new().await?;
    let mut child = Command::new(env!("CARGO_BIN_EXE_memstack-workspace-core"))
        .arg("--desktop-control")
        .current_dir(fixture.root.path())
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()?;
    let child_pid = child
        .id()
        .ok_or("Workspace Core child PID is unavailable")?;
    let mut input = child
        .stdin
        .take()
        .ok_or("Workspace Core child stdin is unavailable")?;
    let output = child
        .stdout
        .take()
        .ok_or("Workspace Core child stdout is unavailable")?;

    input
        .write_all(format!("{}\n", fixture.initialize_frame()).as_bytes())
        .await?;
    input.flush().await?;

    let mut ready_line = String::new();
    let mut output = BufReader::new(output);
    timeout(STARTUP_TIMEOUT, output.read_line(&mut ready_line)).await??;
    let ready: Value = serde_json::from_str(ready_line.trim())?;
    assert_eq!(ready["type"], "desktop_ready");
    assert_eq!(ready["protocolVersion"], 1);
    assert_eq!(ready["nonce"], fixture.nonce);
    assert_eq!(ready["pid"], child_pid);
    assert_eq!(ready["apiBaseUrl"], fixture.api_base_url);

    input
        .write_all(
            format!(
                "{}\n",
                json!({
                    "type": "desktop_shutdown",
                    "protocolVersion": 1,
                    "nonce": fixture.nonce,
                })
            )
            .as_bytes(),
        )
        .await?;
    input.flush().await?;

    let status = timeout(SHUTDOWN_TIMEOUT, child.wait()).await??;
    assert!(status.success(), "Workspace Core shutdown failed: {status}");
    Ok(())
}

struct DesktopControlFixture {
    root: TempDir,
    config_path: std::path::PathBuf,
    snapshot_path: std::path::PathBuf,
    snapshot_sha256: String,
    api_base_url: String,
    nonce: &'static str,
}

impl DesktopControlFixture {
    async fn new() -> Result<Self, Box<dyn Error>> {
        let root = tempfile::tempdir()?;
        let port = reserve_loopback_port().await?;
        let api_base_url = format!("http://127.0.0.1:{port}");
        let database_path = root.path().join("workspace.db");
        let bots_path = root.path().join("bots");
        let files_path = root.path().join("files");
        let config_path = root.path().join("bcs-config.toml");
        let config = format!(
            "bind = \"127.0.0.1\"\nport = {port}\nbots_base_dir = {:?}\n\
             bcs_endpoint = \"{api_base_url}\"\nstore_messages = true\n\
             strict_container_validation = false\napi_keys = []\n\
             allowed_switch_provider_ids = []\n[database]\ntype = \"sqlite\"\n\
             [database.sqlite]\npath = {:?}\n[leader_election]\nenabled = false\n\
             [secret]\nprovider = \"env\"\n[secret.providers.env]\nprefix = \"BCS_SECRET_\"\n\
             [gateway_principal]\nissuer = \"desktop-sidecar\"\n\
             audience = \"workspace-core\"\nkey_id = \"desktop-local\"\n\
             signing_key_env = \"AVERNET_SECRET_PRINCIPAL_SIGNING_KEY_VALUE\"\n\
             [session_files]\nstorage_backend = \"local\"\n\
             [session_files.backend]\ndata_dir = {:?}\n[auth]\nchain = [\"local\"]\n\
             require_authentication = false\nallow_mock_headers = false\n\
             [metrics]\nenabled = false\n[logging]\ndefault_level = \"warn\"\nconsole = true\n",
            bots_path, database_path, files_path,
        );
        tokio::fs::write(&config_path, config).await?;

        let snapshot_path = root.path().join("legacy-workspace-import.json");
        let snapshot = serde_json::to_vec(&json!({
            "schemaVersion": 1,
            "source": "desktop-session-store",
            "workspaceCount": 0,
            "messageCount": 0,
            "workspaces": [],
            "messages": [],
        }))?;
        let snapshot_sha256 = hex::encode(Sha256::digest(&snapshot));
        tokio::fs::write(&snapshot_path, snapshot).await?;
        Ok(Self {
            root,
            config_path,
            snapshot_path,
            snapshot_sha256,
            api_base_url,
            nonce: "desktop-startup-nonce-00000001",
        })
    }

    fn initialize_frame(&self) -> Value {
        json!({
            "type": "desktop_initialize",
            "protocolVersion": 1,
            "nonce": self.nonce,
            "secret": URL_SAFE_NO_PAD.encode([7_u8; 32]),
            "configPath": self.config_path,
            "mode": "desktop-local",
            "serviceToken": "service-token-0123456789abcdef0123456789",
            "agentRegistryUrl": "http://127.0.0.1:9",
            "agentRegistryToken": "registry-token-0123456789abcdef012345678",
            "providerWebhookUrl": "http://127.0.0.1:9/internal/provider",
            "providerWebhookToken": "webhook-token-0123456789abcdef0123456789",
            "providerEventToken": "event-token-0123456789abcdef012345678901",
            "planDispatchUrl": "http://127.0.0.1:9/internal/plan-dispatch",
            "instanceId": "desktop-control-startup-test",
            "legacyImportPath": self.snapshot_path,
            "legacyImportSha256": self.snapshot_sha256,
        })
    }
}

async fn reserve_loopback_port() -> Result<u16, Box<dyn Error>> {
    let listener = TcpListener::bind(("127.0.0.1", 0)).await?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}
