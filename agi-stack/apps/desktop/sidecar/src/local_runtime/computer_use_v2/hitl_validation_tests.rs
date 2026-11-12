use super::*;
use agistack_core::agent::tool_policy::{
    ToolExecutionPolicy, ToolPolicyDecision, ToolPolicyResult,
};
use async_trait::async_trait;

struct EngineIdentityPolicy(std::sync::Mutex<Vec<(String, u64)>>);
#[async_trait]
impl ToolExecutionPolicy for EngineIdentityPolicy {
    async fn before_execute(
        &self,
        _: &ToolPolicyContext<'_>,
        input: &str,
        _: Option<&Value>,
    ) -> CoreResult<ToolPolicyDecision> {
        Ok(ToolPolicyDecision::Allow {
            input_json: input.into(),
        })
    }
    async fn execute_with_content(
        &self,
        context: &ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input: &str,
    ) -> CoreResult<ToolResult> {
        self.0
            .lock()
            .unwrap()
            .push((context.session_id.into(), context.round));
        call_identity::scope(context, tools.call_with_content(context.tool, input)).await
    }
    async fn transform_result(
        &self,
        _: &ToolPolicyContext<'_>,
        result: ToolPolicyResult,
    ) -> CoreResult<ToolPolicyResult> {
        Ok(result)
    }
}
use agistack_core::agent::{
    hitl_validation::HitlValidationContext,
    types::{DecisionContext, HitlKind, HitlRequest, SessionState, SessionStatus},
};

fn request(pending: &Value, id: &str) -> HitlRequest {
    let decision: DecisionContext = serde_json::from_value(json!({
        "action":{"name":pending["tool_name"],"label":"Fixture calendar read"},
        "target":{"kind":"computer_app","id":id},
        "data":{"summary":"Read fixture calendar"}, "reason":"Fixture agent rationale",
        "risk":{"level":"medium","rationale":"Fixture agent risk assessment"},
        "reversibility":{"mode":"partial","recovery":"Fixture recovery"},
        "scope":{"kind":"account","ids":[pending["app"]]},
        "evidence":[{"kind":"native_request","id":id,"label":"Actual native request"}]
    }))
    .unwrap();
    HitlRequest::new(
        "human-native-validation",
        HitlKind::Permission,
        "Approve fixture?",
    )
    .with_decision(decision)
}

async fn assert_rejected_without_card(
    fixture: &Fixture,
    port: &dyn agistack_core::agent::hitl_validation::HitlValidationPort,
    request: &HitlRequest,
) {
    let context = HitlValidationContext {
        session_id: "logical-engine-session",
        round: 2,
    };
    assert!(port.validate(&context, request).await.is_err());
    let prior = fixture
        .state
        .session_store
        .timeline_count(&fixture.conversation.id)
        .unwrap();
    let mut checkpoint = SessionState::new(
        context.session_id,
        "fixture",
        Some(&fixture.owner.project_id),
    );
    checkpoint.status = SessionStatus::AwaitingInput;
    checkpoint.pending_hitl = Some(request.clone());
    assert!(fixture
        .state
        .persist_pending_hitl(&fixture.conversation.id, None, &checkpoint)
        .is_err());
    assert!(fixture
        .state
        .session_store
        .hitl_request(&request.id)
        .unwrap()
        .is_none());
    assert_eq!(
        fixture
            .state
            .session_store
            .timeline_count(&fixture.conversation.id)
            .unwrap(),
        prior
    );
}

#[tokio::test]
async fn native_human_request_rejects_fake_foreign_expired_and_changed_tool_before_card() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let host = tool_host(&fixture.state, &fixture.conversation, None).unwrap();
        let output = fixture
            .call(
                host.as_ref(),
                1,
                json!({"connector":"calendar","operation":"list","arguments":{}}),
            )
            .await
            .unwrap();
        let pending = &output["request"];
        let id = pending["request_id"].as_str().unwrap();
        let port = hitl_validation::NativeHitlValidation::capture(
            &fixture.state,
            &fixture.conversation,
            None,
            "native-message",
            None,
        );
        assert_rejected_without_card(&fixture, &*port, &request(pending, "invented-id")).await;
        let real = request(pending, id);
        let mut changed_tool = real.clone();
        changed_tool.decision.as_mut().unwrap().action.name = "computer_click".into();
        assert_rejected_without_card(&fixture, &*port, &changed_tool).await;
        let original = fixture
            .state
            .computer_use
            .pending
            .lock()
            .unwrap()
            .get(id)
            .unwrap()
            .clone();
        fixture
            .state
            .computer_use
            .pending
            .lock()
            .unwrap()
            .get_mut(id)
            .unwrap()
            .owner
            .user_id = "foreign-user".into();
        assert_rejected_without_card(&fixture, &*port, &real).await;
        fixture
            .state
            .computer_use
            .pending
            .lock()
            .unwrap()
            .insert(id.into(), original);
        let wrong_engine = HitlValidationContext {
            session_id: "another-engine",
            round: 2,
        };
        assert!(port.validate(&wrong_engine, &real).await.is_err());
        store::remove_pending(
            &fixture.state.session_store.connection().unwrap(),
            &fixture.owner,
            id,
        )
        .unwrap();
        assert_rejected_without_card(&fixture, &*port, &real).await;
    })
    .await;
    fixture.helper.client.shutdown().await;
}

#[tokio::test]
async fn actual_native_request_persists_and_generic_human_requests_remain_compatible() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let host = tool_host(&fixture.state, &fixture.conversation, None).unwrap();
        let output = fixture.call(host.as_ref(), 1, json!({"connector":"calendar","operation":"list","arguments":{}})).await.unwrap();
        let pending = &output["request"];
        assert_eq!(pending["engine_session_id"], "logical-engine-session");
        let request = request(pending, pending["request_id"].as_str().unwrap());
        let port = hitl_validation::NativeHitlValidation::capture(&fixture.state, &fixture.conversation, None, "native-message", None);
        let context = HitlValidationContext { session_id: "logical-engine-session", round: 2 };
        port.validate(&context, &request).await.unwrap();
        let mut checkpoint = SessionState::new(context.session_id, "fixture", Some(&fixture.owner.project_id));
        checkpoint.status = SessionStatus::AwaitingInput;
        checkpoint.pending_hitl = Some(request.clone());
        let saved = fixture.state.persist_pending_hitl(&fixture.conversation.id, None, &checkpoint).unwrap().unwrap();
        let identity = crate::local_runtime::knowledge_authority_v2::agent_access::PluginNativeIdentityV2::capture(
            &fixture.state, &fixture.conversation, None).unwrap();
        assert!(hitl::prepare(&fixture.state, identity.auth(), &saved,
            &json!({"action":"allow","granted":true,"scope":"once"})).unwrap().is_some());
        let generic = HitlRequest::new("generic-question", HitlKind::Clarification, "Choose an option");
        port.validate(&context, &generic).await.unwrap();
        checkpoint.pending_hitl = Some(generic);
        assert!(fixture.state.persist_pending_hitl(&fixture.conversation.id, None, &checkpoint).unwrap().is_some());
        let child_port = hitl_validation::NativeHitlValidation::capture(&fixture.state, &fixture.conversation, None, "native-message", Some("child".into()));
        assert!(child_port.validate(&context, &request).await.is_err(), "a parent pending request cannot acquire child authority");
        crate::local_runtime::local_plugin_tool_host_v2::identity::child_scope(
            crate::local_runtime::local_plugin_tool_host_v2::identity::ChildIdentityV2 {
                execution_id: context.session_id.into(), subagent_id: "child".into(),
                run_id: "native-message".into(), revision: 1,
            }, async {
                assert!(child_port.validate(&context, &request).await.is_err(),
                    "an exact child task identity cannot reuse a parent native session");
            }).await;
    }).await;
    fixture.helper.client.shutdown().await;
}

#[tokio::test]
async fn actual_fenced_child_native_request_validates_persists_and_prepares() {
    use crate::local_runtime::local_plugin_tool_host_v2::identity::{child_scope, ChildIdentityV2};
    let fixture = Fixture::new().await;
    let (conversation, run) =
        crate::local_runtime::tests::seed_controlled_run(&fixture.state, "native-child-hitl");
    let auth = fixture
        .state
        .session_store
        .validate_session_credential(
            "cua-native-consent-fixture",
            chrono::Utc::now().timestamp_millis(),
        )
        .unwrap()
        .unwrap();
    let authorization = RunAuthorization::capture(
        auth.clone(),
        Some(cloud::factory_lease(&fixture.state, &fixture.owner).unwrap()),
        &conversation,
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    let parent_control = fixture
        .state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    fixture
        .state
        .subagent_controls
        .register(
            "native-child-execution",
            &conversation.id,
            &run,
            "native-child",
            "builtin:all-access",
            parent_control,
        )
        .unwrap();
    agent_access::scope(Some(authorization), async {
        let host = tool_host(&fixture.state, &conversation, Some(&run)).unwrap();
        let port = hitl_validation::NativeHitlValidation::capture(
            &fixture.state,
            &conversation,
            Some(&run),
            &run.message_id,
            Some("native-child".into()),
        );
        let child = ChildIdentityV2 {
            execution_id: "native-child-execution".into(),
            subagent_id: "native-child".into(),
            run_id: run.id.clone(),
            revision: run.revision,
        };
        child_scope(child, async {
            let call = ToolPolicyContext {
                session_id: "native-child-execution",
                round: 3,
                tool: "computer_connector_call",
            };
            let output = call_identity::scope(
                &call,
                host.call_with_content(
                    call.tool,
                    r#"{"connector":"calendar","operation":"list","arguments":{}}"#,
                ),
            )
            .await
            .unwrap();
            let output: Value = serde_json::from_str(&output.output_json).unwrap();
            assert_eq!(output["request"]["engine_session_id"], call.session_id);
            let request = request(
                &output["request"],
                output["request"]["request_id"].as_str().unwrap(),
            );
            let policy = Arc::new(EngineIdentityPolicy(std::sync::Mutex::new(Vec::new())));
            let engine = agistack_core::ReActEngine::new(
                Arc::new(agistack_adapters_mem::ScriptedLlm::new(vec![
                    agistack_core::AgentAction::CallTool {
                        tool: call.tool.into(),
                        input_json: r#"{"connector":"calendar","operation":"list","arguments":{}}"#
                            .into(),
                    },
                    agistack_core::AgentAction::RequestHuman { request },
                    agistack_core::AgentAction::Finish {
                        answer: "approved".into(),
                    },
                ])),
                host,
                fixture.state.checkpoints.clone(),
                fixture.state.clock.clone(),
            )
            .with_tool_policy(policy.clone())
            .with_hitl_validation(port);
            let checkpoint = engine
                .run(
                    call.session_id,
                    "child fixture",
                    Some(&fixture.owner.project_id),
                )
                .await
                .unwrap();
            assert_eq!(checkpoint.status, SessionStatus::AwaitingInput);
            assert_eq!(checkpoint.round, 1);
            assert_eq!(
                *policy.0.lock().unwrap(),
                vec![(checkpoint.session_id.clone(), 0)]
            );
            let real_output: Value =
                serde_json::from_str(&checkpoint.completed_tool_calls[0].output_json).unwrap();
            assert_eq!(
                real_output["request"]["engine_session_id"],
                checkpoint.session_id
            );
            let saved = fixture
                .state
                .persist_pending_hitl(&conversation.id, Some(&run.id), &checkpoint)
                .unwrap()
                .unwrap();
            assert!(hitl::prepare(
                &fixture.state,
                &auth,
                &saved,
                &json!({"action":"allow","granted":true,"scope":"once"})
            )
            .unwrap()
            .is_some());
        })
        .await;
    })
    .await;
    fixture.state.release_agent_run(&conversation.id);
    fixture.helper.client.shutdown().await;
}
