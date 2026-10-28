use super::*;
use crate::local_runtime::execution_authority;
use agistack_core::ports::{permission_input_digest, PermissionKind, ToolResult};

async fn bound_native_call(
    host: &dyn ToolHost,
    round: u64,
    tool: &str,
    input: &str,
) -> CoreResult<ToolResult> {
    let context = ToolPolicyContext {
        session_id: "native-permission-engine",
        round,
        tool,
    };
    call_identity::scope(
        &context,
        execution_authority::with_step_origin(
            execution_authority::StepOrigin {
                cell_id: "native-permission-cell".into(),
                parent_request_id: None,
                continuation_scope: None,
            },
            execution_authority::with_step_id(
                format!("native-permission-step-{round}"),
                host.call_with_content(tool, input),
            ),
        ),
    )
    .await
}

#[tokio::test]
async fn app_and_device_gates_mint_bound_permission_before_native_dispatch() {
    let fixture = Fixture::new().await;
    store::update(
        &fixture.state.session_store.connection().unwrap(),
        &fixture.owner,
        1,
        "configure",
        Some(("microphone", true)),
    )
    .unwrap();
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let host = tool_host(&fixture.state, &fixture.conversation, None).unwrap();
        for (round, tool, input, capability) in [
            (
                1,
                "computer_get_app_state",
                " { \"app\" : \"fixture\" } ",
                "observe",
            ),
            (
                2,
                "computer_audio_start",
                r#"{ "source":"microphone", "max_duration_ms":30000 }"#,
                "microphone",
            ),
        ] {
            let result = bound_native_call(host.as_ref(), round, tool, input)
                .await
                .unwrap();
            let permission = result
                .permission_required
                .as_ref()
                .expect("trusted native consent witness");
            assert_eq!(permission.kind(), PermissionKind::NativeConsent);
            assert_eq!(permission.binding().tool_name, tool);
            assert_eq!(
                permission.binding().input_digest,
                permission_input_digest(input).unwrap()
            );
            assert_eq!(
                permission.binding().engine_session_id.as_deref(),
                Some("native-permission-engine")
            );
            assert_eq!(
                permission.binding().cell_id.as_deref(),
                Some("native-permission-cell")
            );
            assert_eq!(
                permission.binding().step_id.as_deref(),
                Some(format!("native-permission-step-{round}").as_str())
            );
            let output: Value = serde_json::from_str(&result.output_json).unwrap();
            assert_eq!(permission.demand(), &output);
            assert_eq!(output["request"]["tool_name"], tool);
            assert_eq!(output["request"]["capability"], capability);
            assert!(fixture
                .state
                .computer_use
                .pending_for(&fixture.owner)
                .iter()
                .any(|pending| Some(pending.request_id.as_str())
                    == output["request"]["request_id"].as_str()));
        }
        assert!(fixture.helper.requests().iter().all(|request| !matches!(
            request["method"].as_str(),
            Some("perform_action" | "audio_start" | "get_app_state")
        )));
        fixture
            .state
            .computer_use
            .stop_owner(&fixture.state, &fixture.owner, "revoked")
            .await;
    })
    .await;
    fixture.helper.client.shutdown().await;
}

#[tokio::test]
async fn native_exact_once_permission_dispatches_once_and_replay_has_no_permission() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let host = tool_host(&fixture.state, &fixture.conversation, None).unwrap();
        let tool = "computer_connector_call";
        let input =
            r#"{"connector":"calendar","operation":"create","arguments":{"title":"Fixture"}}"#;
        let first = bound_native_call(host.as_ref(), 1, tool, input)
            .await
            .unwrap();
        let permission = first.permission_required.as_ref().expect("native gate");
        assert_eq!(permission.kind(), PermissionKind::NativeConsent);
        assert_eq!(
            permission.binding().input_digest,
            permission_input_digest(input).unwrap()
        );
        let dispatch_count = || {
            fixture
                .helper
                .requests()
                .iter()
                .filter(|request| request["method"] == "connector_call")
                .count()
        };
        assert_eq!(dispatch_count(), 0);
        fixture
            .grant(&permission.demand()["request"]["request_id"], "once")
            .await
            .unwrap();
        assert_eq!(dispatch_count(), 0);

        let completed = bound_native_call(host.as_ref(), 1, tool, input)
            .await
            .unwrap();
        assert!(completed.permission_required.is_none());
        assert_eq!(
            serde_json::from_str::<Value>(&completed.output_json).unwrap()["ok"],
            true
        );
        assert_eq!(dispatch_count(), 1);
        let replay = bound_native_call(host.as_ref(), 1, tool, input)
            .await
            .unwrap();
        assert!(replay.permission_required.is_none());
        assert_eq!(replay.output_json, completed.output_json);
        assert_eq!(dispatch_count(), 1);

        let next_step = bound_native_call(host.as_ref(), 2, tool, input)
            .await
            .unwrap();
        assert_eq!(
            next_step
                .permission_required
                .as_ref()
                .expect("new action requires its own approval")
                .kind(),
            PermissionKind::NativeConsent
        );
        assert_eq!(dispatch_count(), 1);
        fixture
            .state
            .computer_use
            .stop_owner(&fixture.state, &fixture.owner, "revoked")
            .await;
    })
    .await;
    fixture.helper.client.shutdown().await;
}
