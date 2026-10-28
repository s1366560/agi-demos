//! HTTP continuation receipts must match a live host-owned suspended operation.
use super::*;
use crate::local_runtime::execution_authority::with_cell_lifetime;

fn previous(admission: &Admission) -> ExecutionScope {
    let claim = &admission.claim;
    ExecutionScope {
        tenant_id: claim.tenant_id.clone(),
        project_id: claim.project_id.clone(),
        conversation_id: claim.conversation_id.clone(),
        run_id: claim.run_id.clone(),
        run_revision: claim.authorization_revision - 1,
        engine_session_id: claim.session_id.clone(),
        device_id: Some(claim.device_id.clone()),
        connection_epoch: Some(admission.lease.epoch),
        generation: admission.lease.factory.descriptor().generation,
    }
}

fn receipt() -> Value {
    json!({"kind":"hitl","hitl_request_id":"committed-hitl","origin_request_id":"original",
        "previous_authorization_revision":2,"authorization_revision":3,"cell_id":"cell","step_id":"step"})
}

async fn resumed(
    admission: &Admission,
    old: Option<ExecutionScope>,
    live: bool,
) -> CoreResult<Permit> {
    with_cell_lifetime(
        Arc::new(AtomicBool::new(live)),
        with_step_origin(
            StepOrigin {
                cell_id: "cell".into(),
                parent_request_id: Some("original".into()),
                continuation_scope: old,
            },
            with_step_id(
                "step".into(),
                admission.authorize(
                    "computer_click",
                    r#"{"app":"fixture","x":1,"y":2}"#,
                    &json!({"kind":"native","id":"fixture"}),
                ),
            ),
        ),
    )
    .await
}

#[tokio::test]
async fn consumed_continuation_requires_matching_live_pending_host_scope_and_both_receipt_phases() {
    let (fixture, admission) = fixture().await;
    *fixture.authority.step_continuation.lock().unwrap() = Some(receipt());
    let old = previous(&admission);
    let permit = resumed(&admission, Some(old.clone()), true).await.unwrap();
    assert!(matches!(permit, Permit::Authorized{continuation:Some(value),..} if value == old));
    assert!(resumed(&admission, None, true).await.is_err());
    assert!(resumed(&admission, Some(old.clone()), false).await.is_err());
    let mut foreign = old.clone();
    foreign.project_id = "foreign".into();
    assert!(resumed(&admission, Some(foreign), true).await.is_err());
    *fixture.authority.step_mode.lock().unwrap() = "changed-continuation".into();
    assert!(resumed(&admission, Some(old.clone()), true)
        .await
        .unwrap_err()
        .to_string()
        .contains("consumption_invalid"));
    *fixture.authority.step_mode.lock().unwrap() = String::new();
    for (field, value) in [
        ("cell_id", json!("other")),
        ("origin_request_id", json!("different")),
        ("previous_authorization_revision", json!(1)),
        ("authorization_revision", json!(9)),
    ] {
        let mut proof = receipt();
        proof[field] = value;
        *fixture.authority.step_continuation.lock().unwrap() = Some(proof);
        assert!(resumed(&admission, Some(old.clone()), true).await.is_err());
    }
}

#[cfg(target_os = "macos")]
#[tokio::test]
async fn actual_pending_cloud_cell_supplies_the_previous_scope_only_when_resumed() {
    let mut fixture = Fixture::new().await;
    let helper =
        crate::local_runtime::computer_use_v2::management_lifecycle_tests::Helper::new(false);
    let application = helper.root.join("application");
    let workspace = helper.root.join("workspace");
    std::fs::create_dir(&application).unwrap();
    std::fs::create_dir(&workspace).unwrap();
    Arc::get_mut(&mut fixture.state).unwrap().app_data_dir = Some(application);
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
    let code = "var count=(typeof count==='undefined'?0:count)+1; try { await cua.getBrowser({id:'missing'}); } catch(error) { nodeRepl.write(count); }";
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["tool_name"] = json!("cua_repl_js");
        claim["input_json"] = json!(json!({"code":code}).to_string());
    }
    fixture.operation("describe").await.unwrap();
    *fixture.authority.step_mode.lock().unwrap() = "pending".into();
    fixture.authority.release.add_permits(1);
    let first = fixture.operation("call").await.unwrap();
    let first: Value = serde_json::from_str(first["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(first["error"], "cua_permission_required");
    let cell = first["repl_continuation"]["cell_id"].clone();
    let step = first["request"]["step_id"].clone();
    *fixture.authority.step_mode.lock().unwrap() = String::new();
    *fixture.authority.step_continuation.lock().unwrap() = Some(
        json!({"kind":"hitl","hitl_request_id":"committed-hitl",
        "origin_request_id":"request","previous_authorization_revision":3,"authorization_revision":4,"cell_id":cell,"step_id":step}),
    );
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["request_id"] = json!("resumed");
        claim["round"] = json!(5);
        claim["authorization_revision"] = json!(4);
    }
    let mut input = fixture.input("call");
    input["request_id"] = json!("resumed");
    fixture.authority.release.add_permits(1);
    let result = cloud::operation(&fixture.state, &fixture.broker, input)
        .await
        .unwrap();
    let output: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(output["ok"], true, "{output}");
    assert_eq!(
        output["outputs"].as_array().unwrap().last().unwrap()["text"],
        "1"
    );
    let calls = fixture.authority.step_calls.lock().unwrap();
    assert_eq!(calls.len(), 3);
    assert_eq!(calls[0]["_step_id"], calls[2]["_step_id"]);
    assert_eq!(calls[2]["parent_request_id"], "request");
    drop(calls);
    fixture.operation("close").await.unwrap();
}
