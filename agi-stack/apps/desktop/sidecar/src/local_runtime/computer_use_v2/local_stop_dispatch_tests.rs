//! Existing model calls must reach the scoped Stop receipt after catalog removal.
use super::*;
use crate::local_runtime::{
    execution_profile::{ExecutionProfile, ProfiledToolHost, SelectedResource},
    fan_out_tool_host::FanOutToolHost,
};
use agistack_core::ports::ToolControlOutcome;

fn composed_host(fixture: &Fixture, allowed_tools: &[&str]) -> Arc<dyn ToolHost> {
    let native = tool_host(&fixture.state, &fixture.conversation, None).unwrap();
    let inner: Arc<dyn ToolHost> = Arc::new(FanOutToolHost::new(vec![native]));
    let profile = ExecutionProfile {
        agent: SelectedResource {
            id: "stop-dispatch-fixture".into(),
            name: "Stop dispatch fixture".into(),
        },
        skill: None,
        subagent: None,
        allowed_tools: allowed_tools
            .iter()
            .map(|tool| (*tool).to_owned())
            .collect(),
        allowed_mcp_servers: vec![],
        instructions: String::new(),
    };
    let profiled: Arc<dyn ToolHost> = Arc::new(ProfiledToolHost::new(inner, &profile));
    Arc::new(FanOutToolHost::new(vec![profiled]))
}

async fn begin_observation(fixture: &Fixture, host: &dyn ToolHost) {
    let context = ToolPolicyContext {
        session_id: "stop-dispatch-engine",
        round: 0,
        tool: "computer_get_app_state",
    };
    let result = call_identity::scope(
        &context,
        host.call_with_content(context.tool, r#"{"app":"fixture"}"#),
    )
    .await
    .unwrap();
    let result: Value = serde_json::from_str(&result.output_json).unwrap();
    assert_eq!(result["error"], "cua_permission_required");
    assert!(!fixture.helper.requests().is_empty());
}

#[tokio::test]
async fn local_stop_reaches_typed_receipt_through_both_fan_out_layers_without_native_dispatch() {
    for (action, allowed_tools) in [
        ("stop", &["*"][..]),
        ("stop_all", &["*"][..]),
        (
            "stop",
            &["computer_get_app_state", "computer_list_windows"][..],
        ),
        (
            "stop_all",
            &["computer_get_app_state", "computer_list_windows"][..],
        ),
    ] {
        let fixture = Fixture::new().await;
        agent_access::scope(Some(fixture.authorization.clone()), async {
            let host = composed_host(&fixture, allowed_tools);
            let advertised = host.list_tools();
            assert!(advertised.iter().any(|name| name == "computer_get_app_state"));
            begin_observation(&fixture, host.as_ref()).await;
            let session = fixture.state.computer_use.sessions_for(&fixture.owner)[0]
                ["session_id"]
                .as_str()
                .unwrap()
                .to_owned();
            api::operation(
                &fixture.state,
                &fixture.owner,
                serde_json::from_value(json!({"action":action,"session_id":session})).unwrap(),
            )
            .await
            .unwrap();
            let requests = fixture.helper.requests();
            assert!(host.list_tools().is_empty());
            assert!(host.tool_definitions().unwrap().is_empty());
            for tool in advertised {
                assert!(host.can_dispatch(&tool), "stopped tool must retain its receipt route: {tool}");
                let result = host.call_with_content(&tool, "{}").await.unwrap();
                assert_eq!(result.control_outcome, Some(ToolControlOutcome::UserStopped));
                assert_eq!(result.control_generation, None);
                assert!(result.media.is_empty());
                assert_eq!(
                    serde_json::from_str::<Value>(&result.output_json).unwrap(),
                    json!({"type":"computer_use_control","status":"user_stopped","retry_allowed":false})
                );
            }
            for tool in ["computer_get_app_state_unknown", "unregistered_tool"] {
                assert!(!host.can_dispatch(tool));
                assert!(host.call_with_content(tool, "{}").await.unwrap_err().to_string().contains("unknown tool"));
            }
            assert_eq!(fixture.helper.requests(), requests);
            assert!(fixture.state.computer_use.sessions_for(&fixture.owner).is_empty());
        })
        .await;
        fixture.helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn local_revocation_retains_failure_instead_of_synthesizing_user_stop() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let host = composed_host(&fixture, &["*"]);
        begin_observation(&fixture, host.as_ref()).await;
        fixture
            .state
            .computer_use
            .stop_owner(&fixture.state, &fixture.owner, "revoked")
            .await;
        let requests = fixture.helper.requests();
        assert!(host.list_tools().is_empty());
        let error = host
            .call_with_content("computer_get_app_state", "{}")
            .await
            .unwrap_err();
        assert!(error.to_string().contains("cua_authorization_revoked"));
        assert_eq!(fixture.helper.requests(), requests);
    })
    .await;
    fixture.helper.client.shutdown().await;
}
