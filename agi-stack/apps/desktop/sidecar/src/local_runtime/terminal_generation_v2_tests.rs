//! Actual HTTP upgrade and PTY evidence; response-body leases are not the assertion boundary.
use std::{sync::Arc, time::Duration};

use agistack_plugin_host::{
    desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
    parse_profile_snapshot_v2, DataPlaneTargetV2, LoaderV2, RuntimeGenerationV2, RuntimeV2Error,
    ScopeKindV2, ScopeV2, TargetHostDescriptorV2, DESKTOP_SIDECAR_HOST_SERVICE_V2,
};
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::{net::TcpListener, task::JoinHandle};
use tokio_tungstenite::{
    connect_async,
    tungstenite::{client::IntoClientRequest, Message},
    MaybeTlsStream, WebSocketStream,
};

use super::{
    local_router_with_generation_required, now_iso, session_store, tests::test_state,
    ConversationCapabilityMode, ConversationRunMode, DesktopExecutionEnvironmentKind,
    DesktopPermissionProfile, DesktopRunStatus, LocalConversation, LocalRuntimeState,
};

const CREDENTIAL: &str = "terminal-upgrade-test-credential";
const BOOTSTRAP: &str =
    include_str!("../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");
type ClientSocket = WebSocketStream<MaybeTlsStream<tokio::net::TcpStream>>;

async fn publish(state: &LocalRuntimeState, number: u64) -> Arc<RuntimeGenerationV2> {
    let mut snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("parse actual profile");
    snapshot.profile_id = format!("terminal-upgrade-{number}");
    snapshot.generation = number;
    snapshot.digest = format!("sha256:terminal-upgrade-{number}");
    let generation = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
        ],
    )
    .stage(snapshot.clone())
    .await
    .expect("stage actual Loader generation");
    state
        .platform_plugin_authority_v2
        .publish_local_baseline(
            &snapshot,
            &serde_json::to_value(&snapshot).expect("serialize snapshot"),
            Arc::clone(&generation),
        )
        .await;
    generation
}

fn resolves(
    generation: &RuntimeGenerationV2,
) -> Result<Arc<TargetHostDescriptorV2>, RuntimeV2Error> {
    generation.resolve_versioned::<TargetHostDescriptorV2>(
        DESKTOP_SIDECAR_HOST_SERVICE_V2,
        "1.0.0",
        &ScopeV2 {
            kind: ScopeKindV2::Root,
            tenant_id: None,
            project_id: None,
            session_id: None,
        },
        None,
    )
}

async fn disposed(generation: &RuntimeGenerationV2) {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if matches!(
                resolves(generation),
                Err(RuntimeV2Error::GenerationDisposed)
            ) {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("generation must dispose after upgraded task and PTY drain");
}

fn seed_running(state: &LocalRuntimeState) -> (String, u64) {
    let conversation = LocalConversation {
        id: "terminal-generation-conversation".to_owned(),
        project_id: "local-project".to_owned(),
        tenant_id: "local".to_owned(),
        title: "Terminal generation test".to_owned(),
        workspace_id: Some("local-workspace".to_owned()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Plan,
        created_at: now_iso(),
        updated_at: now_iso(),
    };
    state
        .session_store
        .insert_conversation(&conversation)
        .expect("seed conversation");
    state
        .session_store
        .replace_agent_plan_tasks(
            &conversation.id,
            &[json!({
                "id": "terminal-generation-task", "conversation_id": conversation.id,
                "content": "Open approved terminal", "status": "pending", "priority": "high",
                "order_index": 0, "created_at": now_iso(), "updated_at": now_iso(),
            })],
        )
        .expect("seed reviewed plan");
    let plan = state
        .session_store
        .latest_draft_plan(&conversation.id)
        .expect("read plan")
        .expect("plan");
    let now = now_iso();
    let prepared = state
        .worktree_manager()
        .prepare(
            DesktopExecutionEnvironmentKind::Local,
            "terminal-generation-environment",
            &now,
        )
        .expect("prepare real local workspace");
    let approved = state
        .session_store
        .approve_plan_and_start_in_environment(session_store::ApprovePlanStartInput {
            conversation_id: &conversation.id,
            project_id: "local-project",
            plan_version_id: &plan.id,
            expected_plan_version: plan.version,
            idempotency_key: "terminal-generation-approval",
            message_id: "terminal-generation-message",
            request_message: "Open approved terminal",
            environment: Some(prepared.environment),
            requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
            permission_profile: DesktopPermissionProfile::FullAccess,
            now: &now,
        })
        .expect("approve environment");
    let run = state
        .session_store
        .prepare_run_for_execution(&approved.run.id, &now_iso())
        .expect("prepare run")
        .expect("running run");
    (run.id, run.revision)
}

struct Server(JoinHandle<()>);
impl Drop for Server {
    fn drop(&mut self) {
        self.0.abort();
    }
}
async fn attach(state: Arc<LocalRuntimeState>, run: &(String, u64)) -> (ClientSocket, Server) {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .await
        .expect("TCP listener");
    let address = listener.local_addr().expect("listener address");
    let app = local_router_with_generation_required(state);
    let server = Server(tokio::spawn(async move {
        axum::serve(listener, app)
            .await
            .expect("serve actual router");
    }));
    let response = reqwest::Client::new()
        .post(format!(
            "http://{address}/api/v1/projects/local-project/sandbox/terminal"
        ))
        .bearer_auth(CREDENTIAL)
        .header("x-agistack-launch", CREDENTIAL)
        .json(&json!({"run_id": run.0, "expected_run_revision": run.1}))
        .send()
        .await
        .expect("HTTP grant request")
        .error_for_status()
        .expect("HTTP grant accepted");
    let grant: Value = response.json().await.expect("grant response");
    let session = grant["session_id"].as_str().expect("terminal session id");
    let mut request = format!("ws://{address}/api/v1/projects/local-project/sandbox/terminal/proxy/ws?session_id={session}")
        .into_client_request().expect("upgrade request");
    request.headers_mut().insert(
        "sec-websocket-protocol",
        format!("memstack.auth, {CREDENTIAL}")
            .parse()
            .expect("protocol header"),
    );
    let (mut socket, response) = connect_async(request)
        .await
        .expect("real WebSocket upgrade");
    assert_eq!(response.status().as_u16(), 101);
    let connected = next_json(&mut socket).await;
    assert_eq!(connected["type"], "connected");
    assert_eq!(connected["run_id"], run.0);
    (socket, server)
}
async fn next_json(socket: &mut ClientSocket) -> Value {
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            let message = socket
                .next()
                .await
                .expect("socket remains open")
                .expect("socket frame");
            if let Message::Text(text) = message {
                return serde_json::from_str(&text).expect("JSON frame");
            }
        }
    })
    .await
    .expect("terminal frame timeout")
}
async fn terminal_probe(socket: &mut ClientSocket) {
    // The complete marker is absent from the input, so PTY input echo cannot satisfy this proof.
    socket
        .send(Message::Text(
            json!({"type":"input", "data":"printf '__CORDIS_%s__\\n' GENERATION_OK\n"}).to_string(),
        ))
        .await
        .expect("PTY input");
    tokio::time::timeout(Duration::from_secs(10), async {
        let mut output = String::new();
        loop {
            let value = next_json(socket).await;
            if value["type"] == "output" {
                output.push_str(value["data"].as_str().expect("output string"));
                if output.contains("__CORDIS_GENERATION_OK__") {
                    break;
                }
            }
        }
    })
    .await
    .expect("real shell must execute printf");
}

#[tokio::test]
async fn upgraded_terminal_pins_old_generation_through_swap_and_actual_pty_close() {
    let state = test_state(CREDENTIAL);
    let old = publish(&state, 81).await;
    let run = seed_running(&state);
    let (mut socket, _server) = attach(Arc::clone(&state), &run).await;
    let _new = publish(&state, 82).await;
    assert!(
        resolves(&old).is_ok(),
        "101 body completion must not dispose the socket generation"
    );
    terminal_probe(&mut socket).await;
    assert!(
        resolves(&old).is_ok(),
        "old generation must remain usable while PTY is active"
    );
    socket.close(None).await.expect("send WebSocket close");
    drop(socket);
    disposed(&old).await;
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn authoritative_run_revocation_closes_upgraded_terminal_and_releases_generation() {
    let state = test_state(CREDENTIAL);
    let old = publish(&state, 91).await;
    let run = seed_running(&state);
    let (mut socket, _server) = attach(Arc::clone(&state), &run).await;
    let _new = publish(&state, 92).await;
    terminal_probe(&mut socket).await;
    state
        .session_store
        .transition_run(
            &run.0,
            run.1,
            DesktopRunStatus::ReadyReview,
            None,
            &now_iso(),
        )
        .expect("revoke authoritative run revision");
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if next_json(&mut socket).await["type"] == "authority_revoked" {
                break;
            }
        }
    })
    .await
    .expect("upgraded terminal must observe run revocation");
    tokio::time::timeout(Duration::from_secs(5), async {
        while let Some(frame) = socket.next().await {
            if matches!(frame, Ok(Message::Close(_)) | Err(_)) {
                break;
            }
        }
    })
    .await
    .expect("revocation must close actual upgraded socket");
    drop(socket);
    disposed(&old).await;
    state.platform_plugin_authority_v2.deactivate().await;
}
