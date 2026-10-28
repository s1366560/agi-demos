//! The production step client uses real authenticated HTTP and validates both receipt phases.
use super::*;
#[path = "cloud_continuation_tests.rs"]
mod continuation_tests;
#[path = "cloud_mcp_tests.rs"]
mod mcp_tests;
use crate::local_runtime::computer_use_v2::cloud_tests::Fixture;
use crate::local_runtime::execution_authority::{with_step_id, with_step_origin, StepOrigin};

async fn fixture() -> (Fixture, Admission) {
    let fixture = Fixture::new().await;
    fixture.publish_factory(true).await;
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["tool_name"] = json!("cua_repl_js");
        claim["input_json"] = json!(r#"{"code":"await fixture()"}"#);
    }
    let claim: Claim =
        serde_json::from_value(fixture.authority.claim.lock().unwrap().clone()).unwrap();
    let lease = CloudLease {
        broker: fixture.broker.clone(),
        epoch: fixture.broker.snapshot().unwrap().epoch,
        expires_at: claim.expires_at,
        profile: claim.permission_profile.clone(),
        approved_tools: Default::default(),
        allowed_mcp_servers: vec![],
        alive: Arc::new(AtomicBool::new(true)),
        cancelled: Arc::new(AtomicBool::new(false)),
        factory: factory_lease(&fixture.state, &fixture.owner()).unwrap(),
    };
    let admission = Admission {
        state: Arc::downgrade(&fixture.state),
        claim: Arc::new(claim),
        lease,
    };
    (fixture, admission)
}
async fn authorize(admission: &Admission) -> CoreResult<Permit> {
    with_step_origin(
        StepOrigin {
            cell_id: "cell".into(),
            parent_request_id: Some("original".into()),
            continuation_scope: None,
        },
        with_step_id(
            "step".into(),
            admission.authorize(
                "computer_click",
                r#"{"app":"fixture","x":1,"y":2}"#,
                &json!({"kind":"native","id":"fixture"}),
            ),
        ),
    )
    .await
}

#[tokio::test]
async fn authenticated_http_step_consumes_exact_receipt_and_only_known_not_sent_releases() {
    let (fixture, admission) = fixture().await;
    let permit = authorize(&admission).await.unwrap();
    assert!(matches!(permit, Permit::Authorized { .. }));
    let calls = fixture.authority.step_calls.lock().unwrap().clone();
    assert_eq!(calls.len(), 2);
    assert_eq!(calls[0]["parent_request_id"], "original");
    assert!(calls[0].get("receipt").is_none());
    assert_eq!(calls[1]["receipt"], "fixture-step-receipt");
    let mut first = calls[0].clone();
    first["receipt"] = json!("fixture-step-receipt");
    assert_eq!(first, calls[1]);
    admission.release_not_sent(permit).await.unwrap();
    let calls = fixture.authority.step_calls.lock().unwrap();
    assert_eq!(calls.len(), 3);
    assert_eq!(calls[2]["outcome"], "not_sent");
    assert_eq!(calls[2]["input_json"], calls[0]["input_json"]);
}

#[tokio::test]
async fn pending_http_step_does_not_consume_and_changed_receipt_never_authorizes() {
    let (fixture, admission) = fixture().await;
    *fixture.authority.step_mode.lock().unwrap() = "pending".into();
    assert!(matches!(
        authorize(&admission).await.unwrap(),
        Permit::Pending(_)
    ));
    assert_eq!(fixture.authority.step_calls.lock().unwrap().len(), 1);
    *fixture.authority.step_mode.lock().unwrap() = "changed".into();
    assert!(authorize(&admission)
        .await
        .unwrap_err()
        .to_string()
        .contains("consumption_invalid"));
    assert_eq!(fixture.authority.step_calls.lock().unwrap().len(), 3);
    admission.lease.cancelled.store(true, Ordering::SeqCst);
    assert!(authorize(&admission).await.is_err());
    assert_eq!(fixture.authority.step_calls.lock().unwrap().len(), 3);
}

#[tokio::test]
async fn pending_http_step_requires_exact_server_response_and_never_consumes_mismatch() {
    let (fixture, admission) = fixture().await;
    *fixture.authority.step_mode.lock().unwrap() = "pending-mismatch".into();
    assert!(authorize(&admission)
        .await
        .unwrap_err()
        .to_string()
        .contains("pending_step_invalid"));
    assert_eq!(fixture.authority.step_calls.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn only_matching_typed_native_permission_allows_not_sent_release() {
    let (_, admission) = fixture().await;
    let tool = "computer_get_app_state";
    let input = r#"{"app":"fixture"}"#;
    let demand = json!({"error":"cua_permission_required","request":{"request_id":"fake"}});
    let raw = ToolResult::text(demand.to_string());
    assert!(!admission.native_not_sent(&raw, tool, input).unwrap());
    let binding = permission_binding(tool, input).unwrap();
    let typed = PermissionRequired::new(
        PermissionKind::NativeConsent,
        binding.clone(),
        demand.clone(),
    )
    .into_result();
    assert!(admission.native_not_sent(&typed, tool, input).unwrap());
    let mut mixed = typed.clone();
    mixed.control_outcome = Some(agistack_core::ports::ToolControlOutcome::UserStopped);
    assert!(admission.native_not_sent(&mixed, tool, input).is_err());
    mixed.control_outcome = None;
    mixed.control_generation = Some("generation".into());
    assert!(admission.native_not_sent(&mixed, tool, input).is_err());
    assert!(admission
        .native_not_sent(&typed, tool, r#"{"app":"foreign"}"#)
        .is_err());
    let foreign =
        PermissionRequired::new(PermissionKind::ServerMcpTool, binding, demand).into_result();
    assert!(admission.native_not_sent(&foreign, tool, input).is_err());
}

#[cfg(target_os = "macos")]
#[tokio::test]
async fn actual_claimed_cloud_cell_preserves_bindings_and_resumes_only_pending_native_step() {
    let mut fixture = Fixture::new().await;
    let helper =
        crate::local_runtime::computer_use_v2::management_lifecycle_tests::Helper::new(false);
    let application_root = helper.root.join("application");
    let workspace = helper.root.join("workspace");
    std::fs::create_dir(&application_root).unwrap();
    std::fs::create_dir(&workspace).unwrap();
    Arc::get_mut(&mut fixture.state).unwrap().app_data_dir = Some(application_root);
    *fixture.state.workspace_root.lock().unwrap() = workspace;
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
    let code = "var before=(typeof before==='undefined'?0:before)+1; try { await cua.getBrowser({id:'mcpapps'}); } catch (error) { nodeRepl.write(error.message); } var app=await cua.getApp('fixture'); nodeRepl.write(before);";
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["tool_name"] = json!("cua_repl_js");
        claim["input_json"] = json!(json!({"code":code}).to_string());
    }
    fixture.operation("describe").await.unwrap();
    assert!(catalog(
        &fixture.state,
        &owner,
        &fixture.broker,
        fixture.broker.snapshot().unwrap().epoch
    )
    .unwrap()
    .iter()
    .any(|tool| tool["name"] == "cua_repl_js"));
    assert!(fixture.state.connected_browser_tool_host().is_none());
    for name in [
        "browser_read_operation",
        "browser_write_operation",
        "browser_cdp_operation",
    ] {
        let tools = catalog(
            &fixture.state,
            &owner,
            &fixture.broker,
            fixture.broker.snapshot().unwrap().epoch,
        )
        .unwrap();
        let definition = tools.iter().find(|tool| tool["name"] == name).unwrap();
        assert_eq!(definition["inputSchema"]["x-cua-step-only"], true);
    }
    fixture.authority.release.add_permits(1);
    let first = fixture.operation("call").await.unwrap();
    let first: Value = serde_json::from_str(first["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(first["error"], "cua_permission_required");
    assert!(first["repl_continuation"]["cell_id"].is_string());
    let grant = serde_json::from_value(
        json!({"action":"grant","request_id":first["request"]["request_id"],"scope":"session"}),
    )
    .unwrap();
    api::operation(&fixture.state, &owner, grant).await.unwrap();
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["request_id"] = json!("resumed");
        claim["round"] = json!(5);
    }
    let mut input = fixture.input("call");
    input["request_id"] = json!("resumed");
    fixture.authority.release.add_permits(1);
    let resumed = cloud::operation(&fixture.state, &fixture.broker, input)
        .await
        .unwrap();
    let resumed: Value = serde_json::from_str(resumed["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(resumed["ok"], true, "{resumed}");
    assert!(resumed["outputs"]
        .as_array()
        .unwrap()
        .iter()
        .any(|output| output["text"] == "browser is unavailable"));
    assert_eq!(
        resumed["outputs"].as_array().unwrap().last().unwrap()["text"],
        "1"
    );
    let calls = fixture.authority.step_calls.lock().unwrap().clone();
    assert_eq!(calls.len(), 7);
    assert_eq!(calls[0]["tool_name"], "browser_read_operation");
    assert_eq!(
        calls[0]["target"],
        json!({"kind":"browser","id":"inventory"})
    );
    assert_eq!(calls[1]["receipt"], "fixture-step-receipt");
    assert_eq!(calls[4]["outcome"], "not_sent");
    assert_eq!(calls[2]["_step_id"], calls[5]["_step_id"]);
    assert_eq!(calls[2]["input_json"], calls[5]["input_json"]);
    assert_eq!(calls[5]["parent_request_id"], "request");
    fixture.operation("cancel").await.unwrap();
}
