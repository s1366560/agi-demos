use super::*;
use agistack_core::{
    agent::hitl_validation::{HitlValidationContext, HitlValidationPort},
    ports::{permission_input_digest, PermissionBinding, PermissionKind},
    AgentAction, HitlKind, HitlRequest, ReActEngine, SessionStatus,
};

fn decision() -> HitlRequest {
    HitlRequest::new("fixture-human", HitlKind::Permission, "Allow the fixture once?")
        .with_decision(serde_json::from_value(json!({
            "action":{"name":"computer_get_app_state","label":"Observe fixture"},
            "target":{"kind":"computer_app","id":"native-pending"},
            "data":{"summary":"Observe the owned fixture"},
            "reason":"The fixture requires an observation",
            "risk":{"level":"low","rationale":"Only the owned fixture is observed"},
            "reversibility":{"mode":"reversible","recovery":"Close the fixture"},
            "scope":{"kind":"once","ids":["native-pending"]},
            "evidence":[{"kind":"tool_result","id":"native-pending","label":"Genuine pending result"}]
        })).unwrap())
}

async fn pending() -> (Broker, Arc<Authority>, BoundRun, String) {
    let (broker, authority, mut receive) = fixture();
    let call = dispatch(&broker, 1, "computer_get_app_state", r#"{"app":"fixture"}"#);
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    let wire = permission::WirePermission {
        kind: PermissionKind::NativeConsent,
        binding: PermissionBinding {
            tool_name: "computer_get_app_state".into(),
            input_digest: permission_input_digest(r#"{"app":"fixture"}"#).unwrap(),
            engine_session_id: Some("engine-session".into()),
            cell_id: None,
            step_id: None,
        },
        demand: json!({"error":"cua_permission_required","scopes":["once"],"request":{
            "request_id":"native-pending","session_id":"native-session","engine_session_id":"engine-session",
            "tool_name":"computer_get_app_state","app":"fixture","identity_digest":"identity",
            "input_digest":"native-digest","capability":"observe"}}),
    };
    let validated = broker
        .permission_from_device("connection", &id, Some(3), wire.clone())
        .await
        .unwrap();
    broker
        .receive_result_with_permission(
            "connection",
            &id,
            wire.demand.to_string(),
            false,
            vec![],
            None,
            None,
            Some(validated),
        )
        .unwrap();
    assert!(call.await.unwrap().unwrap().permission_required.is_some());
    let app = crate::prod_api::unit::test_state();
    let bound = BoundRun {
        owner: owner(),
        run: run(),
        tools: Arc::new(app.registry.clone()),
        broker: broker.clone(),
        parked: false,
    };
    (broker, authority, bound, id)
}

#[tokio::test]
async fn exact_human_request_rejects_mismatches_without_inventing_a_pending_decision() {
    let (broker, authority, bound, id) = pending().await;
    let validator = NativeHumanRequestValidation::capture(&bound, "conversation");
    let context = HitlValidationContext {
        session_id: "engine-session",
        round: 2,
    };
    validator.validate(&context, &decision()).await.unwrap();
    for mutation in 0..7 {
        let mut request = decision();
        match mutation {
            0 => request.decision.as_mut().unwrap().target.kind = "browser".into(),
            1 => request.decision.as_mut().unwrap().target.id = "foreign".into(),
            2 => request.decision.as_mut().unwrap().action.name = "computer_click".into(),
            3 => request.kind = HitlKind::Clarification,
            4 => request.decision = None,
            5 => request.decision.as_mut().unwrap().target.kind = "device_mcp_tool".into(),
            _ => request.decision.as_mut().unwrap().data.summary.clear(),
        }
        assert!(
            validator.validate(&context, &request).await.is_err(),
            "mutation {mutation}"
        );
    }
    assert!(validator
        .validate(
            &HitlValidationContext {
                session_id: "foreign",
                round: 2
            },
            &decision()
        )
        .await
        .is_err());
    assert!(broker.pending.lock().unwrap().is_empty());
    assert!(!broker.requests.lock().unwrap()[&id].cancelled);
    authority
        .current
        .store(false, std::sync::atomic::Ordering::SeqCst);
    assert!(validator.validate(&context, &decision()).await.is_err());
}

struct Validation(NativeHumanRequestValidation);
#[async_trait]
impl HitlValidationPort for Validation {
    async fn validate(
        &self,
        context: &HitlValidationContext<'_>,
        request: &HitlRequest,
    ) -> CoreResult<()> {
        self.0.validate(context, request).await
    }
}
struct Observer;
#[async_trait]
impl agistack_core::agent::ReActObserver for Observer {}

#[tokio::test]
async fn exact_target_rejection_returns_to_agent_then_genuine_native_permission_persists() {
    let Some(pool) = super::cancellation_tests::pg_fixture().await else {
        return;
    };
    let (broker, _, bound, id) = pending().await;
    let mut wrong = decision();
    wrong.decision.as_mut().unwrap().target.kind = "browser".into();
    let engine = Arc::new(
        ReActEngine::new(
            Arc::new(agistack_adapters_mem::ScriptedLlm::new(vec![
                AgentAction::RequestHuman { request: wrong },
                AgentAction::RequestHuman {
                    request: decision(),
                },
            ])),
            Arc::new(agistack_plugin_host::HotPlugRegistry::new()),
            Arc::new(agistack_adapters_mem::InMemoryCheckpointStore::new()),
            Arc::new(agistack_adapters_mem::FixedClock(0)),
        )
        .with_hitl_validation(Arc::new(Validation(NativeHumanRequestValidation::capture(
            &bound,
            "conversation",
        )))),
    );
    let state = engine
        .run("engine-session", "Neutral fixture", Some("project"))
        .await
        .unwrap();
    assert_eq!(state.status, SessionStatus::AwaitingInput);
    assert_eq!(state.round, 1);
    assert!(state
        .transcript
        .iter()
        .any(|entry| entry.content.contains("human_request_rejected:")
            && entry
                .content
                .contains("computer_use_permission_target_invalid")));
    let mut app = crate::prod_api::unit::test_state();
    app.computer_use_devices = broker.clone();
    app.worker_postgres = Some(pool.clone());
    let event = park(
        &app,
        bound,
        engine,
        Arc::new(Observer),
        &state,
        "conversation",
        Some("message"),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(event["kind"], "permission");
    assert_eq!(event["decision"]["target"]["id"], "native-pending");
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT status FROM hitl_requests WHERE id='fixture-human'"
        )
        .fetch_one(&pool)
        .await
        .unwrap(),
        "pending"
    );
    assert_eq!(broker.pending.lock().unwrap().len(), 1);
    hitl::cancel_run(
        &broker,
        &Owner {
            user_id: "foreign".into(),
            ..owner()
        },
        "run",
    );
    assert_eq!(broker.pending.lock().unwrap().len(), 1);
    hitl::cancel_run(&broker, &owner(), "foreign");
    assert_eq!(broker.pending.lock().unwrap().len(), 1);
    hitl::cancel_run(&broker, &owner(), "run");
    assert!(broker.pending.lock().unwrap().is_empty());
    assert!(broker.requests.lock().unwrap()[&id].cancelled);
    assert_eq!(broker.devices.lock().unwrap().len(), 1);
    pool.close().await;
}

#[tokio::test]
async fn exact_human_request_accepts_only_the_real_server_mcp_permission_kind() {
    let (broker, _, _) = fixture();
    broker.devices.lock().unwrap().get_mut("connection").unwrap().tools.push(
        ToolDefinition::new("mcp_owned","Owned fixture",json!({"type":"object",
            "x-cua-mcp-binding":{"server_id":"owned","server_name":"Owned","revision":1,"catalog_digest":"one"}})));
    let mut authority = run();
    authority.permission_profile = "read_only".into();
    authority.allowed_mcp_servers = vec!["owned".into()];
    authority.agent_profile.allowed_mcp_servers = authority.allowed_mcp_servers.clone();
    let result = broker
        .request(
            &owner(),
            "conversation",
            &authority,
            &context(1, "mcp_owned"),
            "{}",
        )
        .await
        .unwrap();
    let demand = result.permission_required.unwrap().demand().clone();
    let app = crate::prod_api::unit::test_state();
    let bound = BoundRun {
        owner: owner(),
        run: authority,
        tools: Arc::new(app.registry.clone()),
        broker: broker.clone(),
        parked: false,
    };
    let validator = NativeHumanRequestValidation::capture(&bound, "conversation");
    let mut request = decision();
    request.decision.as_mut().unwrap().target.id =
        demand["request"]["request_id"].as_str().unwrap().into();
    request.decision.as_mut().unwrap().action.name = "mcp_owned".into();
    let context = HitlValidationContext {
        session_id: "engine-session",
        round: 2,
    };
    assert!(validator.validate(&context, &request).await.is_err());
    request.decision.as_mut().unwrap().target.kind = "device_mcp_tool".into();
    validator.validate(&context, &request).await.unwrap();
    broker.cancel_run(&owner(), "run");
    assert!(validator.validate(&context, &request).await.is_err());
}
