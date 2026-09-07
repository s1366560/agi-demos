//! Opt-in cross-process contract: real Rust TCP producer and compiled renderer client.
use std::{process::Stdio, time::Duration};

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpListener,
    process::Command,
};

use super::*;

struct Server(tokio::task::JoinHandle<()>);
impl Server {
    async fn stop(mut self) {
        self.0.abort();
        let _ = (&mut self.0).await;
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        self.0.abort();
    }
}

async fn serve(state: Arc<LocalRuntimeState>) -> (Server, String) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = format!("http://{}", listener.local_addr().unwrap());
    let router = crate::local_runtime::local_router_with_generation_required(state);
    (
        Server(tokio::spawn(async move {
            axum::serve(listener, router).await.unwrap();
        })),
        address,
    )
}

async fn consumer(
    state: &Arc<LocalRuntimeState>,
    directory: &TestDirectory,
    base_url: &str,
    phase: &str,
) {
    let auth = authenticated(state);
    let MemoryMutation::Create { memory } = mutation(&auth) else {
        panic!("fixture")
    };
    let config = json!({"baseUrl": base_url, "token": TOKEN, "memory": memory,
        "tenantId": auth.workspace.tenant_id, "projectId": auth.workspace.project_id,
        "phase": phase, "stateFile": directory.0.join("renderer-receipts.json")});
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../tests/native-knowledge-producer-consumer.mjs");
    let mut child = Command::new(std::env::var("KNOWLEDGE_NODE_BIN").unwrap_or("node".into()))
        .arg(script)
        .env("KNOWLEDGE_CONTRACT_CONFIG", config.to_string())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let mut input = child.stdin.take().unwrap();
    let mut output = BufReader::new(child.stdout.take().unwrap()).lines();
    let mut completed = false;
    while let Some(line) = output.next_line().await.unwrap() {
        let event: Value = serde_json::from_str(&line).expect("consumer emits structured events");
        match event["event"].as_str() {
            Some("before_mutation") => {
                assert_eq!(phase, "late");
                publish(state, directory, 3, true).await;
                input.write_all(b"continue\n").await.unwrap();
                input.flush().await.unwrap();
            }
            Some("complete") => {
                assert!(!completed);
                completed = true;
            }
            _ => panic!("unexpected consumer event: {event}"),
        }
    }
    assert!(
        child.wait().await.unwrap().success(),
        "renderer consumer failed: {phase}"
    );
    assert!(completed, "consumer must finish every assertion");
}

#[tokio::test]
#[ignore = "requires KNOWLEDGE_RENDERER_COMPILED_ROOT and compiled renderer dependencies"]
async fn real_rust_producer_node_typed_crud_survives_restart_and_late_scope() {
    tokio::time::timeout(Duration::from_secs(90), async {
        std::env::var("KNOWLEDGE_RENDERER_COMPILED_ROOT").expect("compiled renderer root required");
        let directory = TestDirectory::new();
        let state = test_state(TOKEN);
        publish(&state, &directory, 1, true).await;
        let (server, base_url) = serve(Arc::clone(&state)).await;
        consumer(&state, &directory, &base_url, "write").await;
        server.stop().await;
        state.platform_plugin_authority_v2.deactivate().await;
        drop(state);

        let state = test_state(TOKEN);
        publish(&state, &directory, 2, true).await;
        let (server, base_url) = serve(Arc::clone(&state)).await;
        consumer(&state, &directory, &base_url, "late").await;
        consumer(&state, &directory, &base_url, "finish").await;
        let auth = authenticated(&state);
        let lease = Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        );
        let scope = operation_scope(&auth, &lease);
        let operation = KnowledgeOperationV2::admit(lease, &auth, &scope).unwrap();
        assert!(operation
            .get("knowledge-test-memory")
            .await
            .unwrap()
            .is_none());
        assert_eq!(operation.changes(0, 20).await.unwrap().len(), 3);
        drop(operation);
        server.stop().await;
        state.platform_plugin_authority_v2.deactivate().await;
    })
    .await
    .expect("cross-process contract exceeded 90 seconds");
}
