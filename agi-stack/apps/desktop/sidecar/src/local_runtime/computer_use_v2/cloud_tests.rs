//! The fixture admits server claims without opening an application or requesting OS access.
use super::*;
use crate::trusted_session::{
    TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
    TrustedSessionRuntimeMode, TrustedSessionStore, TrustedSessionStoreError,
};
use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use tokio::sync::Semaphore;

#[path = "cloud_audio_cleanup_tests.rs"]
mod audio_cleanup_tests;
#[path = "consent_presentation_tests.rs"]
mod consent_presentation_tests;
#[path = "cloud_resume_tests.rs"]
mod resume_tests;

#[derive(Default)]
struct MemoryCredential(Mutex<Option<String>>);
impl TrustedSessionStore for MemoryCredential {
    fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
        *self.0.lock().unwrap() = Some(value.into());
        Ok(())
    }
    fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
        Ok(self.0.lock().unwrap().clone())
    }
    fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
        *self.0.lock().unwrap() = None;
        Ok(())
    }
}
#[derive(Clone)]
pub(super) struct Authority {
    device_id: String,
    user_id: Arc<Mutex<String>>,
    tenant_id: Arc<Mutex<String>>,
    pub(super) claim: Arc<Mutex<Value>>,
    entered: Arc<Semaphore>,
    pub(super) release: Arc<Semaphore>,
    pub(super) resume_response: Arc<Mutex<Option<Value>>>,
    resume_entered: Arc<Semaphore>,
    resume_release: Arc<Semaphore>,
    pub(super) step_mode: Arc<Mutex<String>>,
    pub(super) step_calls: Arc<Mutex<Vec<Value>>>,
    pub(super) step_continuation: Arc<Mutex<Option<Value>>>,
}
pub(super) struct Fixture {
    pub(super) state: Arc<LocalRuntimeState>,
    pub(super) broker: TrustedSessionBroker,
    pub(super) authority: Authority,
    server: tokio::task::JoinHandle<()>,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.server.abort();
    }
}
pub(super) async fn publish_factory(state: &Arc<LocalRuntimeState>, enabled: bool) {
    let mut wire: Value = serde_json::from_str(include_str!(
        "../../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    for entry in wire["entries"].as_array_mut().unwrap() {
        if entry["module_ref"] == module::MODULE_REF {
            entry["enabled"] = json!(enabled);
        }
    }
    wire["generation"] = json!(if enabled { 20 } else { 21 });
    wire.as_object_mut().unwrap().remove("digest");
    wire["digest"] = json!(super::super::tool_authority::canonical_json_digest(&wire).unwrap());
    let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string()).unwrap();
    let generation = super::super::platform_plugin_sync_v2::desktop_loader(None, None)
        .stage(snapshot.clone())
        .await
        .unwrap();
    let retirement = state
        .platform_plugin_authority_v2
        .replace_local_baseline(&snapshot, &wire, generation);
    tokio::spawn(async move {
        retirement.dispose().await;
    });
}

impl Fixture {
    pub(super) async fn publish_factory(&self, enabled: bool) {
        publish_factory(&self.state, enabled).await;
    }
    pub(super) async fn new() -> Self {
        let state = crate::local_runtime::tests::test_state("cua-cloud-authority");
        let device_id = state.session_store.installation_id().to_owned();
        let authority = Authority {
            device_id: device_id.clone(),
            user_id: Arc::new(Mutex::new("cloud-user".into())),
            tenant_id: Arc::new(Mutex::new("cloud-tenant".into())),
            claim: Arc::new(Mutex::new(json!({
                "request_id":"request", "user_id":"cloud-user", "tenant_id":"cloud-tenant",
                "project_id":"cloud-project", "device_id":device_id, "conversation_id":"conversation",
                "run_id":"approved-run", "run_kind":"plan", "session_id":"engine-session", "round":4,
                "tool_name":"computer_get_app_state", "input_json":"{\"app\":\"fixture\"}",
                "permission_profile":"read_only", "approved_tools":[],
                "expires_at":chrono::Utc::now().timestamp()+60,
                "authorization_revision":3, "plan_version_id":"approved-plan"
            }))),
            entered: Arc::new(Semaphore::new(0)),
            release: Arc::new(Semaphore::new(0)),
            resume_response: Default::default(),
            resume_entered: Arc::new(Semaphore::new(0)),
            resume_release: Arc::new(Semaphore::new(0)),
            step_mode: Default::default(),
            step_calls: Default::default(),
            step_continuation: Default::default(),
        };
        async fn me(State(authority): State<Authority>) -> Json<Value> {
            Json(json!({"user_id":*authority.user_id.lock().unwrap()}))
        }
        async fn project(State(authority): State<Authority>) -> Json<Value> {
            Json(json!({"id":"cloud-project","tenant_id":*authority.tenant_id.lock().unwrap()}))
        }
        async fn workspace_context(State(authority): State<Authority>) -> Json<Value> {
            Json(
                json!({"context":{"tenant_id":*authority.tenant_id.lock().unwrap(),
                "project_id":"cloud-project","revision":1},"membership_role":"owner"}),
            )
        }
        async fn status(State(authority): State<Authority>) -> Json<Value> {
            Json(
                json!({"ready":true,"device_id":authority.device_id,"user_id":"cloud-user","tenant_id":"cloud-tenant","project_id":"cloud-project"}),
            )
        }
        async fn claim(
            State(authority): State<Authority>,
            Json(input): Json<Value>,
        ) -> Json<Value> {
            assert_eq!(input, json!({"device_id":authority.device_id}));
            authority.entered.add_permits(1);
            authority.release.acquire().await.unwrap().forget();
            Json(authority.claim.lock().unwrap().clone())
        }
        async fn resume_authority(
            State(authority): State<Authority>,
            Json(input): Json<Value>,
        ) -> (axum::http::StatusCode, Json<Value>) {
            assert_eq!(
                input,
                json!({"device_id":authority.device_id,"session_id":"engine-session"})
            );
            authority.resume_entered.add_permits(1);
            authority.resume_release.acquire().await.unwrap().forget();
            let value = authority
                .resume_response
                .lock()
                .unwrap()
                .clone()
                .unwrap_or_else(|| {
                    let mut value = authority.claim.lock().unwrap().clone();
                    value["expires_at"] = json!(chrono::Utc::now().timestamp() + 30);
                    value
                });
            (
                if value["denied"] == true {
                    axum::http::StatusCode::CONFLICT
                } else {
                    axum::http::StatusCode::OK
                },
                Json(value),
            )
        }
        async fn continuity_authority(
            State(authority): State<Authority>,
            Json(input): Json<Value>,
        ) -> (axum::http::StatusCode, Json<Value>) {
            assert_eq!(input["device_id"], authority.device_id);
            assert_eq!(input["session_id"], "engine-session");
            let mut value = authority
                .resume_response
                .lock()
                .unwrap()
                .clone()
                .unwrap_or_else(|| authority.claim.lock().unwrap().clone());
            value["expires_at_ms"] = json!(chrono::Utc::now().timestamp_millis() + 5000);
            (
                if value["denied"] == true {
                    axum::http::StatusCode::CONFLICT
                } else {
                    axum::http::StatusCode::OK
                },
                Json(value),
            )
        }
        async fn step_authority(
            State(authority): State<Authority>,
            axum::extract::Path((request, step)): axum::extract::Path<(String, String)>,
            headers: axum::http::HeaderMap,
            Json(input): Json<Value>,
        ) -> Json<Value> {
            use sha2::{Digest, Sha256};
            assert_eq!(
                headers.get("authorization").unwrap(),
                "Bearer fixture-credential"
            );
            assert_eq!(request, authority.claim.lock().unwrap()["request_id"]);
            let mut recorded = input.clone();
            recorded["_step_id"] = json!(step);
            authority.step_calls.lock().unwrap().push(recorded);
            let mode = authority.step_mode.lock().unwrap().clone();
            if matches!(mode.as_str(), "pending" | "pending-mismatch") {
                let claim = authority.claim.lock().unwrap().clone();
                let parent: Value =
                    serde_json::from_str(claim["input_json"].as_str().unwrap()).unwrap();
                let mut pending = json!({"status":"pending","error":"cua_permission_required","scopes":["once"],"request":{
                    "request_id":"fixture-pending","session_id":input["cell_id"],"engine_session_id":claim["session_id"],
                    "app":input["target"]["id"],"identity_digest":"fixture-catalog","capability":"execution_step",
                    "tool_name":input["tool_name"],"input_digest":format!("{:x}",Sha256::digest(input["input_json"].as_str().unwrap().as_bytes())),
                    "execution_step":{"key":"fixture-step","cell_id":input["cell_id"],"step_id":step,"target":input["target"],
                        "code_digest":format!("{:x}",Sha256::digest(parent["code"].as_str().unwrap().as_bytes()))}}});
                if mode == "pending-mismatch" {
                    pending["request"]["execution_step"]["step_id"] = json!("foreign");
                }
                return Json(pending);
            }
            let consumed = input.get("receipt").is_some();
            let mut result = json!({"status":if input["outcome"]=="not_sent" {"released"} else if consumed {"authorized"} else {"ready"},
                "receipt":"fixture-step-receipt","step_id":step,"cell_id":input["cell_id"],
                "input_digest":format!("{:x}",Sha256::digest(input["input_json"].as_str().unwrap().as_bytes())),
                "authorization_revision":authority.claim.lock().unwrap()["authorization_revision"],"catalog_digest":if mode=="changed" && consumed {"changed"} else {"fixture-catalog"}});
            if let Some(proof) = authority.step_continuation.lock().unwrap().as_ref() {
                if proof["step_id"] == step {
                    result["continuation"] = proof.clone();
                    if mode == "changed-continuation" && consumed {
                        result["continuation"]["hitl_request_id"] = json!("changed");
                    }
                }
            }
            Json(result)
        }
        let router = Router::new()
            .route("/api/v1/auth/me", get(me))
            .route(
                "/api/v1/agent/device/requests/:request_id/steps/:step_id/authorize",
                post(step_authority),
            )
            .route("/api/v1/projects/cloud-project", get(project))
            .route("/api/v1/workspace-context", get(workspace_context))
            .route("/api/v1/agent/device/status", get(status))
            .route(
                "/api/v1/agent/device/requests/:request_id/claim",
                post(claim),
            )
            .route(
                "/api/v1/agent/device/requests/:request_id/resume-authority",
                post(resume_authority),
            )
            .route(
                "/api/v1/agent/device/requests/:request_id/continuity-authority",
                post(continuity_authority),
            )
            .with_state(authority.clone());
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(listener, router).await.unwrap();
        });
        let broker = TrustedSessionBroker::new(Arc::new(MemoryCredential::default()));
        broker
            .save(TrustedSessionRecord {
                version: 1,
                api_base_url: format!("http://{address}"),
                runtime_mode: TrustedSessionRuntimeMode::Cloud,
                credential_kind: TrustedSessionCredentialKind::CloudBearer,
                credential: "fixture-credential".into(),
                expires_at: None,
            })
            .unwrap();
        Self {
            state,
            broker,
            authority,
            server,
        }
    }
    pub(super) fn input(&self, action: &str) -> Value {
        json!({"action":action,"connection_id":"connection","scope":{"tenant_id":"cloud-tenant","project_id":"cloud-project","conversation_id":"conversation"},"request_id":"request"})
    }
    pub(super) async fn operation(&self, action: &str) -> Result<Value, String> {
        cloud::operation(&self.state, &self.broker, self.input(action)).await
    }
    pub(super) fn owner(&self) -> Owner {
        Owner {
            user_id: "cloud-user".into(),
            tenant_id: "cloud-tenant".into(),
            project_id: "cloud-project".into(),
            device_id: self.authority.device_id.clone(),
        }
    }
}

#[tokio::test]
async fn actual_sidecar_consent_wire_separates_engine_native_sessions_and_retains_grant_on_resume()
{
    let fixture = Fixture::new().await;
    let helper = super::management_lifecycle_tests::Helper::new(false);
    fixture
        .state
        .computer_use
        .client
        .set(helper.client.clone())
        .unwrap_or_else(|_| panic!("fixture client already set"));
    fixture.publish_factory(true).await;
    let owner = fixture.owner();
    store::update(
        &fixture.state.session_store.connection().unwrap(),
        &owner,
        0,
        "enable",
        None,
    )
    .unwrap();
    let expected: Value = serde_json::from_str(include_str!(
        "../../../../../../../shared/fixtures/computer-use-cloud-consent.json"
    ))
    .unwrap();
    fixture.authority.claim.lock().unwrap()["session_id"] =
        expected["request"]["engine_session_id"].clone();
    fixture.operation("describe").await.unwrap();
    fixture.authority.release.add_permits(1);
    let response = fixture.operation("call").await.unwrap();
    let mut output: Value =
        serde_json::from_str(response["output_json"].as_str().unwrap()).unwrap();
    let native_id = output["request"]["session_id"].as_str().unwrap().to_owned();
    let request_id = output["request"]["request_id"].as_str().unwrap().to_owned();
    assert_ne!(
        output["request"]["engine_session_id"],
        output["request"]["session_id"]
    );
    assert!(fixture
        .state
        .computer_use
        .sessions
        .lock()
        .unwrap()
        .contains_key(&native_id));
    output["request"]["session_id"] = expected["request"]["session_id"].clone();
    output["request"]["request_id"] = expected["request"]["request_id"].clone();
    assert_eq!(output["request"], expected["request"]);
    assert_eq!(output["scopes"], expected["scopes"]);
    let grant =
        serde_json::from_value(json!({"action":"grant","request_id":request_id,"scope":"session"}))
            .unwrap();
    api::operation(&fixture.state, &owner, grant).await.unwrap();
    fixture.authority.claim.lock().unwrap()["round"] = json!(5);
    fixture.authority.release.add_permits(1);
    let resumed = fixture.operation("call").await.unwrap();
    assert!(
        serde_json::from_str::<Value>(resumed["output_json"].as_str().unwrap())
            .unwrap()
            .get("error")
            .is_none()
    );
    assert_eq!(fixture.state.computer_use.sessions_for(&owner).len(), 1);
    fixture.operation("cancel").await.unwrap();
    assert!(fixture.state.computer_use.sessions_for(&owner).is_empty());
    assert!(helper
        .client
        .session_artifact_root(&native_id)
        .await
        .is_none());
}

#[tokio::test]
async fn cloud_connector_read_session_grant_cannot_authorize_mutation_and_once_cannot_repeat() {
    let fixture = Fixture::new().await;
    let helper = super::management_lifecycle_tests::Helper::new(false);
    assert!(fixture
        .state
        .computer_use
        .client
        .set(helper.client.clone())
        .is_ok());
    fixture.publish_factory(true).await;
    let owner = fixture.owner();
    store::update(
        &fixture.state.session_store.connection().unwrap(),
        &owner,
        0,
        "enable",
        None,
    )
    .unwrap();
    let read = json!({"connector":"messages","operation":"list","arguments":{}});
    let write = json!({"connector":"messages","operation":"send","arguments":{"recipient":"fixture","body":"mock-only"}});
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["tool_name"] = json!("computer_connector_call");
        claim["permission_profile"] = json!("full_access");
        claim["input_json"] = json!(read.to_string());
    }
    fixture.operation("describe").await.unwrap();
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    let pending: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    api::operation(&fixture.state,&owner,serde_json::from_value(json!({"action":"grant","request_id":pending["request"]["request_id"],"scope":"session"})).unwrap()).await.unwrap();
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["round"] = json!(5);
        claim["input_json"] = json!(write.to_string());
    }
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    let action: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(action["request"]["capability"], "connector_action");
    assert_eq!(action["scopes"], json!(["once"]));
    for scope in ["session", "always"] {
        assert_eq!(api::operation(&fixture.state,&owner,serde_json::from_value(json!({"action":"grant","request_id":action["request"]["request_id"],"scope":scope})).unwrap()).await.unwrap_err(),"cua_action_requires_once");
    }
    api::operation(
        &fixture.state,
        &owner,
        serde_json::from_value(
            json!({"action":"grant","request_id":action["request"]["request_id"],"scope":"once"}),
        )
        .unwrap(),
    )
    .await
    .unwrap();
    fixture.authority.claim.lock().unwrap()["round"] = json!(6);
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    assert!(
        serde_json::from_str::<Value>(result["output_json"].as_str().unwrap())
            .unwrap()
            .get("error")
            .is_none()
    );
    fixture.authority.claim.lock().unwrap()["round"] = json!(7);
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    let repeated: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(repeated["error"], "cua_permission_required");
    assert_ne!(
        repeated["request"]["request_id"],
        action["request"]["request_id"]
    );
    assert_eq!(
        helper
            .requests()
            .iter()
            .filter(|request| request["method"] == "connector_call")
            .count(),
        1
    );
    fixture.operation("cancel").await.unwrap();
}

#[tokio::test]
async fn cloud_deadline_releases_native_resources_retains_pending_and_old_timer_cannot_clear_renewal(
) {
    let fixture = Fixture::new().await;
    let helper = super::management_lifecycle_tests::Helper::new(false);
    fixture
        .state
        .computer_use
        .client
        .set(helper.client.clone())
        .unwrap_or_else(|_| panic!("fixture client already set"));
    fixture.publish_factory(true).await;
    let owner = fixture.owner();
    store::update(
        &fixture.state.session_store.connection().unwrap(),
        &owner,
        0,
        "enable",
        None,
    )
    .unwrap();
    fixture.operation("describe").await.unwrap();
    fixture.authority.claim.lock().unwrap()["expires_at"] =
        json!(chrono::Utc::now().timestamp() + 2);
    fixture.authority.release.add_permits(1);
    let pending = fixture.operation("call").await.unwrap();
    let body: Value = serde_json::from_str(pending["output_json"].as_str().unwrap()).unwrap();
    let native = body["request"]["session_id"].as_str().unwrap().to_owned();
    // Renew this same logical/native session before its previous deadline.
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["round"] = json!(5);
        claim["expires_at"] = json!(chrono::Utc::now().timestamp() + 4);
    }
    fixture.authority.release.add_permits(1);
    fixture.operation("call").await.unwrap();
    tokio::time::sleep(std::time::Duration::from_millis(2250)).await;
    assert!(helper.client.session_artifact_root(&native).await.is_some());
    assert_eq!(fixture.state.computer_use.pending_for(&owner).len(), 1);
    tokio::time::timeout(std::time::Duration::from_secs(4), async {
        while helper.client.session_artifact_root(&native).await.is_some() {
            tokio::time::sleep(std::time::Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(fixture.state.computer_use.sessions_for(&owner).len(), 1);
    assert_eq!(fixture.state.computer_use.pending_for(&owner).len(), 1);
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["round"] = json!(6);
        claim["expires_at"] = json!(chrono::Utc::now().timestamp() + 10);
    }
    fixture.authority.release.add_permits(1);
    fixture.operation("call").await.unwrap();
    assert!(helper.client.session_artifact_root(&native).await.is_some());
    assert!(std::fs::read_to_string(helper.root.join("requests"))
        .unwrap()
        .contains("reset_session"));
    fixture.operation("close").await.unwrap();
}

#[tokio::test]
async fn recording_deadline_and_fresh_claim_never_replay_or_reauthorize_start_automatically() {
    let fixture = Fixture::new().await;
    let helper = super::management_lifecycle_tests::Helper::new(false);
    assert!(fixture
        .state
        .computer_use
        .client
        .set(helper.client.clone())
        .is_ok());
    fixture.publish_factory(true).await;
    let owner = fixture.owner();
    {
        let db = fixture.state.session_store.connection().unwrap();
        store::update(&db, &owner, 0, "enable", None).unwrap();
        store::update(&db, &owner, 1, "configure", Some(("microphone", true))).unwrap();
    }
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["tool_name"] = json!("computer_audio_start");
        claim["input_json"] = json!(r#"{"source":"microphone"}"#);
        claim["permission_profile"] = json!("full_access");
    }
    fixture.operation("describe").await.unwrap();
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    let pending: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(pending["scopes"], json!(["once"]));
    let physical = pending["request"]["session_id"].as_str().unwrap();
    api::operation(
        &fixture.state,
        &owner,
        serde_json::from_value(
            json!({"action":"grant","request_id":pending["request"]["request_id"],"scope":"once"}),
        )
        .unwrap(),
    )
    .await
    .unwrap();
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["round"] = json!(5);
        claim["expires_at"] = json!(chrono::Utc::now().timestamp() + 2);
    }
    fixture.authority.release.add_permits(1);
    fixture.operation("call").await.unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(4), async {
        while helper
            .client
            .session_artifact_root(physical)
            .await
            .is_some()
        {
            tokio::time::sleep(std::time::Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();
    fixture.authority.claim.lock().unwrap()["expires_at"] =
        json!(chrono::Utc::now().timestamp() + 60);
    fixture.authority.release.add_permits(1);
    fixture.operation("call").await.unwrap();
    fixture.authority.claim.lock().unwrap()["round"] = json!(6);
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    let fresh: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(fresh["error"], "cua_permission_required");
    assert_eq!(fresh["scopes"], json!(["once"]));
    assert_eq!(
        helper
            .requests()
            .iter()
            .filter(|request| request["method"] == "audio_start")
            .count(),
        1,
        "both exact-call recovery and a new model start require no automatic recording replay"
    );
    fixture.operation("cancel").await.unwrap();
}

#[tokio::test]
async fn disabled_v2_factory_revokes_held_native_session_and_rejects_old_registered_calls() {
    let fixture = Fixture::new().await;
    let helper = super::management_lifecycle_tests::Helper::new(false);
    fixture
        .state
        .computer_use
        .client
        .set(helper.client.clone())
        .unwrap_or_else(|_| panic!("fixture client already set"));
    fixture.publish_factory(true).await;
    let owner = fixture.owner();
    store::update(
        &fixture.state.session_store.connection().unwrap(),
        &owner,
        0,
        "enable",
        None,
    )
    .unwrap();
    fixture.operation("describe").await.unwrap();
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    let output: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    let native = output["request"]["session_id"].as_str().unwrap();
    assert!(helper.client.session_artifact_root(native).await.is_some());
    fixture.publish_factory(false).await;
    fixture.authority.release.add_permits(1);
    assert_eq!(
        fixture.operation("call").await.unwrap_err(),
        "cua_factory_disabled"
    );
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while helper.client.session_artifact_root(native).await.is_some() {
            tokio::time::sleep(std::time::Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();
    fixture.operation("close").await.unwrap();
}

#[tokio::test]
async fn cloud_registration_uses_authenticated_identity_and_revokes_on_logout() {
    let fixture = Fixture::new().await;
    let descriptor = fixture.operation("describe").await.unwrap();
    assert_eq!(descriptor["enabled"], false);
    assert_eq!(descriptor["tool_definitions"], json!([]));
    assert!(!cloud::ready(&fixture.state, &fixture.owner()));
    fixture.operation("ready").await.unwrap();
    assert!(cloud::ready(&fixture.state, &fixture.owner()));
    fixture.broker.clear().unwrap();
    assert!(!cloud::ready(&fixture.state, &fixture.owner()));
    assert_eq!(
        fixture.operation("call").await.unwrap_err(),
        "cua_trusted_session_required"
    );
    fixture.operation("close").await.unwrap();
    assert!(fixture
        .state
        .computer_use
        .cloud_connections
        .lock()
        .unwrap()
        .is_empty());
}

#[tokio::test]
async fn cloud_rejects_forged_native_input_and_foreign_project_claim() {
    let fixture = Fixture::new().await;
    let mut input = fixture.input("describe");
    input["tool_name"] = json!("computer_click");
    assert_eq!(
        cloud::operation(&fixture.state, &fixture.broker, input)
            .await
            .unwrap_err(),
        "cua_cloud_request_invalid"
    );
    *fixture.authority.tenant_id.lock().unwrap() = "other-tenant".into();
    assert_eq!(
        fixture.operation("describe").await.unwrap_err(),
        "cua_scope_mismatch"
    );
    *fixture.authority.tenant_id.lock().unwrap() = "cloud-tenant".into();
    fixture.operation("describe").await.unwrap();
    fixture.authority.claim.lock().unwrap()["project_id"] = json!("foreign-project");
    fixture.authority.release.add_permits(1);
    assert_eq!(
        fixture.operation("call").await.unwrap_err(),
        "cua_cloud_claim_scope_invalid"
    );
    assert!(fixture.state.computer_use.client.get().is_none());
    assert!(fixture
        .state
        .computer_use
        .sessions_for(&fixture.owner())
        .is_empty());
}

#[tokio::test]
async fn cancellation_and_disconnect_fence_an_in_flight_authenticated_claim() {
    for action in ["cancel", "close"] {
        let fixture = Fixture::new().await;
        fixture.operation("describe").await.unwrap();
        let state = fixture.state.clone();
        let broker = fixture.broker.clone();
        let input = fixture.input("call");
        let call = tokio::spawn(async move { cloud::operation(&state, &broker, input).await });
        fixture.authority.entered.acquire().await.unwrap().forget();
        fixture.operation(action).await.unwrap();
        fixture.authority.release.add_permits(1);
        let error = call.await.unwrap().unwrap_err();
        assert!(matches!(
            error.as_str(),
            "cua_cloud_request_cancelled" | "cua_cloud_connection_not_registered"
        ));
        assert!(fixture.state.computer_use.client.get().is_none());
        assert!(fixture
            .state
            .computer_use
            .sessions_for(&fixture.owner())
            .is_empty());
    }
}

#[tokio::test]
async fn cancellation_before_claim_keeps_a_tombstone_and_prevents_dispatch() {
    let fixture = Fixture::new().await;
    fixture.operation("describe").await.unwrap();
    fixture.operation("cancel").await.unwrap();
    assert_eq!(
        fixture.operation("call").await.unwrap_err(),
        "cua_cloud_request_cancelled"
    );
    assert_eq!(fixture.authority.entered.available_permits(), 0);
    assert!(fixture.state.computer_use.client.get().is_none());
}

#[tokio::test]
async fn connector_refusal_blocks_new_rounds_and_desktop_fallback_for_the_same_run() {
    let fixture = Fixture::new().await;
    fixture.operation("describe").await.unwrap();
    let owner = fixture.owner();
    let instance = store::update(
        &fixture.state.session_store.connection().unwrap(),
        &owner,
        0,
        "enable",
        None,
    )
    .unwrap();
    let pending = PendingConsent {
        request_id: "native-consent".into(),
        session_id: "native-session".into(),
        engine_session_id: None,
        app: "connector:account:calendar".into(),
        identity_digest: "declared-connector".into(),
        capability: "calendar".into(),
        tool_name: "computer_connector_call".into(),
        input_digest: "exact-request".into(),
        target: None,
        app_icon: None,
        owner: owner.clone(),
    };
    let session = Arc::new(Session {
        resources: Default::default(),
        dispatch: tokio::sync::Mutex::new(()),
        owner: owner.clone(),
        context: CuaCallContext {
            user_id: owner.user_id.clone(),
            tenant_id: owner.tenant_id.clone(),
            project_id: owner.project_id.clone(),
            device_id: owner.device_id.clone(),
            conversation_id: "conversation".into(),
            run_id: "approved-run".into(),
            session_id: pending.session_id.clone(),
            input_mode: agistack_adapters_cua::CuaInputMode::default(),
        },
        revision: instance.revision,
        stopped: AtomicBool::new(false),
        paused: AtomicBool::new(false),
        user_control: Default::default(),
        presentation: Mutex::new(json!({"phase":"idle","can_resume":false})),
        child: None,
        cloud: None,
    });
    fixture
        .state
        .computer_use
        .sessions
        .lock()
        .unwrap()
        .insert(pending.session_id.clone(), session);
    fixture
        .state
        .computer_use
        .pending
        .lock()
        .unwrap()
        .insert(pending.request_id.clone(), pending.clone());
    store::save_pending(
        &fixture.state.session_store.connection().unwrap(),
        &owner,
        &pending.request_id,
        &json!(pending),
    )
    .unwrap();
    let input: api::ManagementRequest =
        serde_json::from_value(json!({"action":"decline","request_id":pending.request_id}))
            .unwrap();
    api::operation(&fixture.state, &owner, input).await.unwrap();
    assert!(fixture.state.computer_use.sessions_for(&owner).is_empty());
    for (round, tool) in [(7, "computer_get_app_state"), (8, "computer_click")] {
        {
            let mut claim = fixture.authority.claim.lock().unwrap();
            claim["round"] = json!(round);
            claim["tool_name"] = json!(tool);
        }
        fixture.authority.release.add_permits(1);
        assert!(fixture
            .operation("call")
            .await
            .unwrap_err()
            .contains("cua_permission_denied_run"));
        assert!(fixture.state.computer_use.pending_for(&owner).is_empty());
        assert!(fixture.state.computer_use.client.get().is_none());
    }
    let db = fixture.state.session_store.connection().unwrap();
    assert!(denials::ensure(&db, &owner, "approved-run").is_err());
    assert!(denials::ensure(&db, &owner, "a-new-authorized-run").is_ok());
    let mut other = owner;
    other.user_id = "other-user".into();
    assert!(denials::ensure(&db, &other, "approved-run").is_ok());
}
