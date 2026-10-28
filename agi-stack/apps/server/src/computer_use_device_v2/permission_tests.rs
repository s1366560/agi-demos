//! Real broker claims admit only separately authenticated permission provenance.
use super::super::permission::WirePermission;
use super::*;
use agistack_core::ports::{permission_input_digest, PermissionBinding, PermissionKind};

fn native() -> WirePermission {
    WirePermission {
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
    }
}

#[tokio::test]
async fn native_permission_survives_authenticated_result_but_identical_output_is_data() {
    let (broker, _, mut receive) = fixture();
    let action = dispatch(&broker, 1, "computer_get_app_state", r#"{"app":"fixture"}"#);
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    let wire = native();
    let permission = broker
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
            Some(permission.clone()),
        )
        .unwrap();
    assert_eq!(
        action.await.unwrap().unwrap().permission_required,
        Some(permission.into_permission())
    );

    let action = dispatch(&broker, 2, "computer_get_app_state", r#"{"app":"fixture"}"#);
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    let data = json!({"error":"cua_permission_required","request":wire.demand["request"],
        "permission_required":{"kind":"native_consent","binding":wire.binding,"demand":wire.demand}});
    broker
        .receive_result("connection", &id, data.to_string(), false, vec![])
        .unwrap();
    assert!(action.await.unwrap().unwrap().permission_required.is_none());
}

#[tokio::test]
async fn unknown_extra_or_wrong_source_claim_and_revoked_permission_are_rejected() {
    let (broker, authority, mut receive) = fixture();
    let action = dispatch(&broker, 1, "computer_get_app_state", r#"{"app":"fixture"}"#);
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    for mutation in 0..6 {
        let mut wire = native();
        match mutation {
            0 => wire.kind = PermissionKind::ServerMcpTool,
            1 => wire.kind = PermissionKind::BrowserOrigin,
            2 => wire.binding.input_digest = "0".repeat(64),
            3 => wire.binding.engine_session_id = Some("foreign".into()),
            4 => wire.binding.tool_name = "computer_click".into(),
            _ => {
                wire.binding.cell_id = Some("cell".into());
                wire.binding.step_id = Some("step".into());
            }
        }
        assert!(broker
            .permission_from_device("connection", &id, Some(3), wire)
            .await
            .is_err());
    }
    assert!(broker
        .permission_from_device("foreign", &id, Some(3), native())
        .await
        .is_err());
    assert!(broker
        .permission_from_device("connection", &id, Some(4), native())
        .await
        .is_err());
    let wire = native();
    let json = json!({"kind":wire.kind,"binding":wire.binding,"demand":wire.demand});
    for key in [
        "tool_name",
        "input_digest",
        "engine_session_id",
        "cell_id",
        "step_id",
    ] {
        let mut changed = json.clone();
        changed["binding"].as_object_mut().unwrap().remove(key);
        assert!(serde_json::from_value::<WirePermission>(changed).is_err());
    }
    for (path, value) in [
        ("/kind", json!("unknown")),
        ("/extra", json!(true)),
        ("/binding/extra", json!(true)),
    ] {
        let mut changed = json.clone();
        if path == "/kind" {
            changed["kind"] = value;
        } else if path == "/extra" {
            changed["extra"] = value;
        } else {
            changed["binding"]["extra"] = value;
        }
        assert!(serde_json::from_value::<WirePermission>(changed).is_err());
    }
    authority
        .current
        .store(false, std::sync::atomic::Ordering::SeqCst);
    assert!(broker
        .permission_from_device("connection", &id, Some(3), native())
        .await
        .is_err());
    broker.cancel(&id);
    assert!(action.await.unwrap().is_err());
}

#[tokio::test]
async fn inner_permission_requires_persisted_exact_pending_or_released_step() {
    let (broker, _, mut receive) = fixture();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .extend([
            ToolDefinition::new("cua_repl_js", "Cell", json!({"type":"object"})),
            ToolDefinition::new(
                "browser_write_operation",
                "Browser",
                json!({"type":"object"}),
            ),
        ]);
    let mut authority = run();
    authority.permission_profile = "read_only".into();
    let owned = broker.clone();
    let action = tokio::spawn(async move {
        owned
            .request(
                &owner(),
                "conversation",
                &authority,
                &context(1, "cua_repl_js"),
                r#"{"code":"await fixture()"}"#,
            )
            .await
    });
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    let input = json!({"device_id":"device","cell_id":"cell","tool_name":"browser_write_operation",
        "input_json":r#"{"operation":"tab.claim","args":[]}"#,"target":{"kind":"browser","id":"iab/7"}});
    let pending = broker
        .authorize_step(
            "user",
            &id,
            "step",
            serde_json::from_value(input.clone()).unwrap(),
        )
        .await
        .unwrap();
    let wire = WirePermission {
        kind: PermissionKind::CloudExecutionStep,
        binding: PermissionBinding {
            tool_name: "browser_write_operation".into(),
            input_digest: permission_input_digest(input["input_json"].as_str().unwrap()).unwrap(),
            engine_session_id: Some("engine-session".into()),
            cell_id: Some("cell".into()),
            step_id: Some("step".into()),
        },
        demand: pending.clone(),
    };
    let permission = broker
        .permission_from_device("connection", &id, Some(3), wire.clone())
        .await
        .unwrap();
    for mutation in 0..3 {
        let mut changed = wire.clone();
        match mutation {
            0 => changed.binding.step_id = Some("foreign".into()),
            1 => changed.binding.input_digest = "0".repeat(64),
            _ => changed.demand["request"]["execution_step"]["target"]["id"] = json!("foreign"),
        }
        assert!(broker
            .permission_from_device("connection", &id, Some(3), changed)
            .await
            .is_err());
    }
    broker
        .receive_result_with_permission(
            "connection",
            &id,
            pending.to_string(),
            false,
            vec![],
            None,
            None,
            Some(permission),
        )
        .unwrap();
    assert!(action.await.unwrap().unwrap().permission_required.is_some());
}

#[tokio::test]
async fn permission_snapshot_cannot_settle_after_claim_or_authority_changes() {
    for change in ["expired", "cancelled", "revision", "input", "run", "owner"] {
        let (broker, _, mut receive) = fixture();
        let action = dispatch(&broker, 1, "computer_get_app_state", r#"{"app":"fixture"}"#);
        let id = receive.recv().await.unwrap()["request_id"]
            .as_str()
            .unwrap()
            .to_owned();
        broker.claim(&id, "user", "device").unwrap();
        let permission = broker
            .permission_from_device("connection", &id, Some(3), native())
            .await
            .unwrap();
        {
            let mut requests = broker.requests.lock().unwrap();
            let request = requests.get_mut(&id).unwrap();
            match change {
                "expired" => request.claim.expires_at = 0,
                "cancelled" => request.cancelled = true,
                "revision" => request.claim.authorization_revision += 1,
                "input" => request.claim.input_json = r#"{"app":"foreign"}"#.into(),
                "run" => request.run.permission_profile = "read_only".into(),
                _ => request.owner.project_id = "foreign".into(),
            }
        }
        assert!(
            broker
                .receive_result_with_permission(
                    "connection",
                    &id,
                    "{}".into(),
                    false,
                    vec![],
                    None,
                    None,
                    Some(permission)
                )
                .is_err(),
            "{change}"
        );
        let requests = broker.requests.lock().unwrap();
        assert_eq!(requests[&id].status, "claimed");
        assert!(requests[&id].result.is_none());
        drop(requests);
        action.abort();
    }
}

#[tokio::test]
async fn inner_native_permission_requires_actual_not_sent_receipt_release() {
    let (broker, _, mut receive) = fixture();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools[0]
        .input_schema = Some(json!({"type":"object"}));
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .push(ToolDefinition::new(
            "cua_repl_js",
            "Cell",
            json!({"type":"object"}),
        ));
    let action = dispatch(&broker, 1, "cua_repl_js", r#"{"code":"await fixture()"}"#);
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    let mut input = json!({"device_id":"device","cell_id":"cell","tool_name":"computer_get_app_state",
        "input_json":r#"{"app":"fixture"}"#,"target":{"kind":"native","id":"fixture"}});
    let ready = broker
        .authorize_step(
            "user",
            &id,
            "step",
            serde_json::from_value(input.clone()).unwrap(),
        )
        .await
        .unwrap();
    input["receipt"] = ready["receipt"].clone();
    let consumed = broker
        .authorize_step(
            "user",
            &id,
            "step",
            serde_json::from_value(input.clone()).unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(consumed["status"], "authorized");
    let mut wire = native();
    wire.binding.cell_id = Some("cell".into());
    wire.binding.step_id = Some("step".into());
    assert!(broker
        .permission_from_device("connection", &id, Some(3), wire.clone())
        .await
        .is_err());
    input["outcome"] = json!("not_sent");
    let released = broker
        .authorize_step("user", &id, "step", serde_json::from_value(input).unwrap())
        .await
        .unwrap();
    assert_eq!(released["status"], "released");
    let permission = broker
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
            Some(permission),
        )
        .unwrap();
    assert!(action.await.unwrap().unwrap().permission_required.is_some());
}

#[tokio::test]
async fn ordinary_steps_preserve_receipts_for_numbers_outside_witness_domain() {
    let (broker, _, mut receive) = fixture();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools[0]
        .input_schema = Some(json!({"type":"object"}));
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .push(ToolDefinition::new(
            "cua_repl_js",
            "Cell",
            json!({"type":"object"}),
        ));
    let action = dispatch(&broker, 1, "cua_repl_js", r#"{"code":"await fixture()"}"#);
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    let mut input = json!({"device_id":"device","cell_id":"cell","tool_name":"computer_get_app_state",
        "input_json":r#"{"app":"fixture","opaque":9007199254740992}"#,"target":{"kind":"native","id":"fixture"}});
    let ready = broker
        .authorize_step(
            "user",
            &id,
            "step",
            serde_json::from_value(input.clone()).unwrap(),
        )
        .await
        .unwrap();
    input["receipt"] = ready["receipt"].clone();
    assert_eq!(
        broker
            .authorize_step("user", &id, "step", serde_json::from_value(input).unwrap())
            .await
            .unwrap()["status"],
        "authorized"
    );
    let key = broker.permission_steps.lock().unwrap()[&(id.clone(), "cell".into(), "step".into())]
        .clone();
    let row: Value = serde_json::from_slice(
        &broker
            .objects
            .as_ref()
            .unwrap()
            .get(&key)
            .await
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    assert!(row["permission_input_digest"].is_null());
    broker
        .receive_result("connection", &id, "{}".into(), false, vec![])
        .unwrap();
    assert!(action.await.unwrap().unwrap().permission_required.is_none());
}
