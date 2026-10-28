use super::*;

fn mcp(broker: &Broker) -> authority::RunAuthority {
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .push(ToolDefinition::new(
            "mcp_owned",
            "Owned operation",
            json!({"type":"object",
            "x-cua-mcp-binding":{"server_id":"owned","server_name":"Owned",
                "revision":1,"catalog_digest":"catalog-one"}}),
        ));
    let mut run = run();
    run.permission_profile = "read_only".into();
    run.allowed_mcp_servers = vec!["owned".into()];
    run.agent_profile.allowed_mcp_servers = run.allowed_mcp_servers.clone();
    run
}

async fn pending(broker: &Broker, run: &authority::RunAuthority) -> Value {
    let result = broker
        .request(
            &owner(),
            "conversation",
            run,
            &context(1, "mcp_owned"),
            r#"{"value":1}"#,
        )
        .await
        .unwrap();
    let output: Value = serde_json::from_str(&result.output_json).unwrap();
    let witness = result.permission_required.as_ref().unwrap();
    assert_eq!(
        witness.kind(),
        agistack_core::ports::PermissionKind::ServerMcpTool
    );
    assert_eq!(witness.demand(), &output);
    assert_eq!(output["error"], "cua_permission_required");
    assert_eq!(output["scopes"], json!(["once"]));
    assert!(output["hint"]
        .as_str()
        .unwrap()
        .contains("target.kind=device_mcp_tool"));
    let claim = broker
        .requests
        .lock()
        .unwrap()
        .values()
        .next()
        .unwrap()
        .claim
        .clone();
    broker
        .verify_pending_outer(&claim, &output["request"])
        .await
        .unwrap()
}

#[tokio::test]
async fn large_integer_is_ordinary_mcp_data_but_cannot_manufacture_a_permission_receipt() {
    let (broker, _, mut receive) = fixture();
    let run = mcp(&broker);
    let input = r#"{"value":9007199254740992}"#;
    for round in 1..=2 {
        assert!(broker
            .request(
                &owner(),
                "conversation",
                &run,
                &context(round, "mcp_owned"),
                input
            )
            .await
            .is_err());
        assert!(receive.try_recv().is_err());
        assert!(broker.requests.lock().unwrap().is_empty());
        assert!(broker
            .objects
            .as_ref()
            .unwrap()
            .list("computer-use/outer-permissions/")
            .await
            .unwrap()
            .is_empty());
    }
    let mut allowed = run;
    allowed.permission_profile = "full_access".into();
    let owned = broker.clone();
    let call = tokio::spawn(async move {
        owned
            .request(
                &owner(),
                "conversation",
                &allowed,
                &context(3, "mcp_owned"),
                input,
            )
            .await
    });
    let event = receive.recv().await.unwrap();
    let id = event["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    broker
        .receive_result(
            "connection",
            id,
            json!({"value":9007199254740992_u64}).to_string(),
            false,
            vec![],
        )
        .unwrap();
    assert!(call.await.unwrap().unwrap().permission_required.is_none());
}

#[tokio::test]
async fn exact_outer_once_dispatches_once_without_expanding_run_permission() {
    let (broker, _, mut receive) = fixture();
    let run = mcp(&broker);
    let row = pending(&broker, &run).await;
    assert!(
        receive.try_recv().is_err(),
        "pending must never reach the device"
    );
    broker
        .resolve_outer_permission(&row, true, "committed-hitl")
        .await
        .unwrap();
    assert!(broker
        .resolve_outer_permission(&row, true, "duplicate")
        .await
        .is_err());
    let cloned = broker.clone();
    let authority = run.clone();
    let call = tokio::spawn(async move {
        cloned
            .request(
                &owner(),
                "conversation",
                &authority,
                &context(2, "mcp_owned"),
                r#"{"value":1}"#,
            )
            .await
    });
    let announced = receive.recv().await.unwrap();
    let id = announced["request_id"].as_str().unwrap();
    let (claim, _, _) = broker.claim(id, "user", "device").unwrap();
    assert_eq!(claim.permission_profile, "read_only");
    assert_eq!(claim.approved_tools, ["mcp_owned"]);
    assert!(broker.claim(id, "user", "device").is_err());
    broker
        .receive_result("connection", id, r#"{"ok":true}"#.into(), false, vec![])
        .unwrap();
    let result = call.await.unwrap().unwrap();
    let repeated = broker
        .request(
            &owner(),
            "conversation",
            &run,
            &context(2, "mcp_owned"),
            r#"{"value":1}"#,
        )
        .await
        .unwrap();
    assert_eq!(result.output_json, repeated.output_json);
    assert!(broker
        .request(
            &owner(),
            "conversation",
            &run,
            &context(3, "mcp_owned"),
            r#"{"value":1}"#
        )
        .await
        .is_err());
    assert!(receive.try_recv().is_err());
}

#[tokio::test]
async fn outer_permission_rejects_changed_binding_and_requires_new_input_approval() {
    for change in [
        "catalog",
        "device",
        "revision",
        "roster",
        "agent",
        "revoked",
        "cancelled",
        "denied",
        "input",
    ] {
        let (broker, authority, mut receive) = fixture();
        let mut run = mcp(&broker);
        let row = pending(&broker, &run).await;
        broker
            .resolve_outer_permission(&row, change != "denied", "committed-hitl")
            .await
            .unwrap();
        match change {
            "catalog" => {
                broker
                    .devices
                    .lock()
                    .unwrap()
                    .get_mut("connection")
                    .unwrap()
                    .tools
                    .last_mut()
                    .unwrap()
                    .description = Some("changed".into())
            }
            "device" => {
                broker
                    .devices
                    .lock()
                    .unwrap()
                    .get_mut("connection")
                    .unwrap()
                    .device_id = "other-device".into()
            }
            "revision" => run.authorization_revision += 1,
            "roster" => run.allowed_mcp_servers.clear(),
            "agent" => run.agent_profile.allowed_tools = Some(vec!["other".into()]),
            "revoked" => authority
                .current
                .store(false, std::sync::atomic::Ordering::SeqCst),
            "cancelled" => broker.cancel_conversation(&owner(), "conversation"),
            _ => {}
        }
        let result = broker
            .request(
                &owner(),
                "conversation",
                &run,
                &context(2, "mcp_owned"),
                if change == "input" {
                    r#"{"value":2}"#
                } else {
                    r#"{"value":1}"#
                },
            )
            .await;
        if change == "input" {
            let output: Value = serde_json::from_str(&result.unwrap().output_json).unwrap();
            assert_eq!(output["error"], "cua_permission_required");
        } else {
            assert!(result.is_err(), "{change}");
        }
        while let Ok(event) = receive.try_recv() {
            assert_ne!(event["type"], "computer_use_request", "{change} dispatched");
        }
    }
}

#[tokio::test]
async fn claim_rechecks_entire_mcp_definition_after_approval() {
    let (broker, _, mut receive) = fixture();
    let run = mcp(&broker);
    let row = pending(&broker, &run).await;
    broker
        .resolve_outer_permission(&row, true, "committed-hitl")
        .await
        .unwrap();
    let cloned = broker.clone();
    let call = tokio::spawn(async move {
        cloned
            .request(
                &owner(),
                "conversation",
                &run,
                &context(2, "mcp_owned"),
                r#"{"value":1}"#,
            )
            .await
    });
    let announced = receive.recv().await.unwrap();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .last_mut()
        .unwrap()
        .input_schema
        .as_mut()
        .unwrap()["required"] = json!(["new_field"]);
    assert!(broker
        .claim(announced["request_id"].as_str().unwrap(), "user", "device")
        .is_err());
    call.abort();
}
