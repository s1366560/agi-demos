//! Exercises the shipped binary; no provider network access or account fixture is required.
use serde_json::{json, Value};
use std::process::Stdio;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
    time::{timeout, Duration},
};

struct Server {
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
}
impl Server {
    fn new(provider: &str) -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_memstack-cua-cloud-connectors"))
            .args(["--provider", provider])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .unwrap();
        let input = child.stdin.take().unwrap();
        let output = BufReader::new(child.stdout.take().unwrap());
        Self {
            child,
            input,
            output,
        }
    }
    async fn request(&mut self, request: Value) -> Value {
        self.input
            .write_all(format!("{request}\n").as_bytes())
            .await
            .unwrap();
        self.input.flush().await.unwrap();
        let mut line = String::new();
        timeout(Duration::from_secs(3), self.output.read_line(&mut line))
            .await
            .unwrap()
            .unwrap();
        serde_json::from_str(&line).unwrap()
    }
}
#[tokio::test]
async fn real_mcp_handshake_catalog_and_missing_account_error() {
    for provider in ["google", "microsoft365"] {
        let mut server = Server::new(provider);
        let first = server
            .request(json!({"jsonrpc":"2.0","id":0,"method":"tools/list"}))
            .await;
        assert_eq!(first["error"]["message"], "initialize_required");
        let initialized=server.request(json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}})).await;
        assert_eq!(
            initialized["result"]["serverInfo"]["computer_use_connector"]["provider"],
            provider
        );
        let tools = server
            .request(json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}))
            .await;
        assert_eq!(tools["result"]["tools"].as_array().unwrap().len(), 8);
        let call=server.request(json!({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"calendar_list","arguments":{}}})).await;
        assert_eq!(
            call["result"]["structuredContent"]["error"]["code"],
            "oauth_required"
        );
        assert_eq!(call["result"]["isError"], true);
        server.child.kill().await.unwrap();
    }
}
#[tokio::test]
async fn private_oauth_token_never_echoed_and_reinitialize_is_rejected() {
    let mut server = Server::new("google");
    let initialized=server.request(json!({"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","_meta":{"memstack":{"oauth_access_token":"fixture-secret-only"}}}})).await;
    assert!(initialized.get("result").is_some());
    assert!(!initialized.to_string().contains("fixture-secret-only"));
    let reinitialize=server.request(json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}})).await;
    assert_eq!(reinitialize["error"]["message"], "already_initialized");
    // Invalid parameters are rejected before an HTTP request can use the fixture token.
    let call=server.request(json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"calendar_create","arguments":{"endpoint":"https://example.invalid"}}})).await;
    assert_eq!(
        call["result"]["structuredContent"]["error"]["code"],
        "invalid_arguments"
    );
    server.child.kill().await.unwrap();
}
