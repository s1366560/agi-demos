//! Session and workspace invalidation must reach an already retained local CUA authority.
#[path = "authority_idle_tests.rs"]
mod idle_tests;
#[path = "authority_race_tests.rs"]
mod race_tests;

use super::*;
use crate::local_runtime::{
    auth_context::AuthenticatedContext,
    knowledge_authority_v2::agent_access::{self, PluginNativeIdentityV2, RunAuthorization},
    local_router_with_generation_required,
};
use agistack_core::agent::tool_policy::ToolPolicyContext;
use axum::{body::Body, http::Request};
use std::sync::atomic::{AtomicUsize, Ordering};
use tower::ServiceExt;

const LAUNCH: &str = "cua-authority-revocation-launch";
const TOOL: &str = "computer_list_apps";

struct CountingHost(Arc<AtomicUsize>);

#[async_trait]
impl ToolHost for CountingHost {
    fn list_tools(&self) -> Vec<String> {
        vec![TOOL.into()]
    }

    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok("{}".into())
    }
}

struct Fixture {
    state: Arc<LocalRuntimeState>,
    conversation: LocalConversation,
    run: DesktopRun,
    root: std::path::PathBuf,
    token: String,
    auth: AuthenticatedContext,
    calls: Arc<AtomicUsize>,
}

impl Fixture {
    async fn new() -> Self {
        let (state, conversation, run, root) = test_support::state(LAUNCH);
        state.ensure_authoritative_launch_checkpoint(&run).await.unwrap();
        let wire: Value = serde_json::from_str(include_str!(
            "../../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
        ))
        .unwrap();
        let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string()).unwrap();
        let generation = crate::local_runtime::platform_plugin_sync_v2::desktop_loader(None, None)
            .stage(snapshot.clone())
            .await
            .unwrap();
        state
            .platform_plugin_authority_v2
            .publish_local_baseline(&snapshot, &wire, generation)
            .await;
        let outcome = post(&state, None, "/api/v1/auth/local-session", json!({})).await;
        let token = outcome["access_token"].as_str().unwrap().to_owned();
        let auth = state
            .session_store
            .validate_session_credential(&token, chrono::Utc::now().timestamp_millis())
            .unwrap()
            .unwrap();
        Self {
            state,
            conversation,
            run,
            root,
            token,
            auth,
            calls: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn authorization(&self) -> Arc<RunAuthorization> {
        RunAuthorization::capture(
            self.auth.clone(),
            Some(Arc::new(
                self.state
                    .platform_plugin_authority_v2
                    .acquire_generation()
                    .unwrap(),
            )),
            &self.conversation,
            &self.run.message_id,
            Some(&self.run.id),
        )
        .unwrap()
    }

    fn retained(&self) -> (ExecutionAuthority, PluginNativeIdentityV2) {
        self.state
            .claim_agent_run(&self.conversation.id, Some(&self.run.id))
            .unwrap();
        let native =
            PluginNativeIdentityV2::capture(&self.state, &self.conversation, Some(&self.run))
                .unwrap();
        let profile = self.state.execution_profile(&self.conversation).unwrap();
        let local = local_authority::LocalExecution {
            state: Arc::downgrade(&self.state),
            owner: Some(self.auth.clone()),
            scope: ExecutionScope {
                tenant_id: self.conversation.tenant_id.clone(),
                project_id: self.conversation.project_id.clone(),
                conversation_id: self.conversation.id.clone(),
                run_id: self.run.id.clone(),
                run_revision: self.run.revision,
                engine_session_id: String::new(),
                device_id: None,
                connection_epoch: None,
                generation: 0,
            },
            run: self.run.clone(),
            conversation: self.conversation.clone(),
            tools: Arc::new(CountingHost(self.calls.clone())),
            boundary: None,
            allowed_servers: profile.allowed_mcp_servers,
            allowed_tools: profile.allowed_tools,
            agent_id: profile.agent.id,
            subagent_id: None,
            child: None,
        };
        (ExecutionAuthority::LocalRun(Arc::new(local)), native)
    }

    async fn finish(self) {
        self.state.release_agent_run(&self.conversation.id);
        if !self
            .state
            .session_store
            .session_context_is_current(&self.auth, chrono::Utc::now().timestamp_millis())
            .unwrap()
        {
            tokio::time::timeout(std::time::Duration::from_secs(2), async {
                loop {
                    let released = {
                        let runs = self.state.agent_runs.lock().unwrap();
                        let owners = self.state.run_owners.lock().unwrap();
                        !runs.contains_key(&self.conversation.id)
                            && !owners.contains_key(&self.conversation.id)
                    };
                    if released {
                        break;
                    }
                    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
                }
            })
            .await
            .expect("revocation cleanup must finish before removing fixture storage");
        }
        self.state.cua_repl.shutdown();
        self.state.platform_plugin_authority_v2.deactivate().await;
        drop(self.state);
        std::fs::remove_dir_all(self.root).unwrap();
    }
}

async fn post(
    state: &Arc<LocalRuntimeState>,
    token: Option<&str>,
    path: &str,
    body: Value,
) -> Value {
    let mut request = Request::builder()
        .method("POST")
        .uri(path)
        .header("x-agistack-launch", LAUNCH)
        .header("content-type", "application/json");
    if let Some(token) = token {
        request = request.header("authorization", format!("Bearer {token}"));
    }
    let response = local_router_with_generation_required(state.clone())
        .oneshot(request.body(Body::from(body.to_string())).unwrap())
        .await
        .unwrap();
    assert_eq!(response.status(), axum::http::StatusCode::OK);
    let bytes = axum::body::to_bytes(response.into_body(), 1024 * 1024)
        .await
        .unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

async fn dispatch(authority: &ExecutionAuthority, round: u64) -> CoreResult<ToolResult> {
    call_identity::scope(
        &ToolPolicyContext {
            session_id: "retained-cua-engine",
            round,
            tool: "cua_repl_js",
        },
        authority.call(TOOL, "{}"),
    )
    .await
}

#[tokio::test]
async fn formal_owner_signout_revokes_retained_local_cua_authorities_before_dispatch() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization()), async {
        let (authority, native) = fixture.retained();
        assert!(native.current(&fixture.state));
        dispatch(&authority, 1).await.unwrap();
        assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);

        let outcome = post(
            &fixture.state,
            Some(&fixture.token),
            "/api/v1/auth/signout",
            json!({}),
        )
        .await;
        assert_eq!(outcome["success"], true);
        let native_current = native.current(&fixture.state);
        let result = dispatch(&authority, 2).await;

        assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
        assert!(
            result.is_err(),
            "revoked session dispatched a local CUA operation"
        );
        assert!(
            !native_current,
            "native identity retained a revoked owner session"
        );
    })
    .await;
    fixture.finish().await;
}

#[tokio::test]
async fn formal_workspace_switch_revokes_retained_local_cua_authorities_before_dispatch() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization()), async {
        let (authority, native) = fixture.retained();
        dispatch(&authority, 1).await.unwrap();
        let outcome = post(
            &fixture.state,
            Some(&fixture.token),
            "/api/v1/workspace-context/switch",
            json!({
                "tenant_id": "northstar",
                "project_id": "desktop-client",
                "expected_revision": fixture.auth.workspace.revision,
                "idempotency_key": "cua-authority-workspace-switch"
            }),
        )
        .await;
        assert_eq!(outcome["context"]["project_id"], "desktop-client");
        let native_current = native.current(&fixture.state);
        let result = dispatch(&authority, 2).await;

        assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
        assert!(
            result.is_err(),
            "previous workspace dispatched a local CUA operation"
        );
        assert!(
            !native_current,
            "native identity retained the old workspace revision"
        );
    })
    .await;
    fixture.finish().await;
}

#[tokio::test]
async fn formal_unrelated_session_signout_preserves_retained_local_cua_authorities() {
    let fixture = Fixture::new().await;
    let other = post(
        &fixture.state,
        None,
        "/api/v1/auth/local-session",
        json!({}),
    )
    .await;
    let other_token = other["access_token"].as_str().unwrap();
    assert_ne!(other["session"]["session_id"], fixture.auth.session_id);
    agent_access::scope(Some(fixture.authorization()), async {
        let (authority, native) = fixture.retained();
        dispatch(&authority, 1).await.unwrap();
        post(
            &fixture.state,
            Some(other_token),
            "/api/v1/auth/signout",
            json!({}),
        )
        .await;

        assert!(native.current(&fixture.state));
        dispatch(&authority, 2).await.unwrap();
        assert_eq!(fixture.calls.load(Ordering::SeqCst), 2);
    })
    .await;
    fixture.finish().await;
}

#[tokio::test]
async fn formal_session_refresh_preserves_retained_local_cua_authorities() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization()), async {
        let (authority, native) = fixture.retained();
        dispatch(&authority, 1).await.unwrap();
        for path in ["/api/v1/auth/me", "/api/v1/workspace-context"] {
            let response = local_router_with_generation_required(fixture.state.clone())
                .oneshot(
                    Request::builder()
                        .method("GET")
                        .uri(path)
                        .header("x-agistack-launch", LAUNCH)
                        .header("authorization", format!("Bearer {}", fixture.token))
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(response.status(), axum::http::StatusCode::OK);
        }

        assert!(native.current(&fixture.state));
        dispatch(&authority, 2).await.unwrap();
        assert_eq!(fixture.calls.load(Ordering::SeqCst), 2);
    })
    .await;
    fixture.finish().await;
}
