use super::*;
use agistack_core::agent::ReActObserver;
use agistack_core::ports::CoreError;
use crate::local_runtime::{
    local_plugin_tool_host_v2::identity::{child_scope, ChildIdentityV2},
    tool_authority::{ToolEffect, ToolMetadata},
    PlanModeToolHost,
};
use std::collections::{BTreeMap, BTreeSet};

fn capture(
    state: &Arc<LocalRuntimeState>,
    conversation: &local_runtime::LocalConversation,
    message: &str,
    run: Option<&str>,
) -> Arc<RunAuthorization> {
    RunAuthorization::capture(
        state
            .session_store
            .validate_session_credential(TOKEN, chrono::Utc::now().timestamp_millis())
            .unwrap()
            .unwrap(),
        Some(Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        )),
        conversation,
        message,
        run,
    )
    .unwrap()
}

#[tokio::test]
async fn plan_signed_plugin_requires_live_native_message_control_and_explicit_read_metadata() {
    let (state, bytes) = setup().await;
    let reference = import(&state, &bytes).await;
    local_runtime::tests::seed_plan_conversation(&state, "plugin-plan");
    let conversation = state
        .session_store
        .conversation("plugin-plan")
        .unwrap()
        .unwrap();
    let native = capture(&state, &conversation, "plan-message-one", None);
    assert!(LocalPluginToolHostV2::new_plan(&state, &conversation)
        .await
        .unwrap()
        .is_none());
    agent_access::scope(Some(native.clone()), async {
        assert!(LocalPluginToolHostV2::new_plan(&state, &conversation)
            .await
            .unwrap()
            .is_none());
        let control = state.claim_agent_run(&conversation.id, None).unwrap();
        let host = Arc::new(
            LocalPluginToolHostV2::new_plan(&state, &conversation)
                .await
                .unwrap()
                .unwrap(),
        );
        let name = host.list_tools().pop().unwrap();
        let plain = PlanModeToolHost::new(
            host.clone(),
            state.session_store.clone(),
            conversation.id.clone(),
        );
        assert!(!plain.list_tools().contains(&name));
        assert!(plain.call(&name, r#"{"input":"blocked"}"#).await.is_err());
        let write_metadata = BTreeMap::from([(
            name.clone(),
            ToolMetadata {
                name: name.clone(),
                effect: ToolEffect::Mutate,
                sensitive_input_fields: BTreeSet::new(),
            },
        )]);
        assert!(!PlanModeToolHost::new(
            host.clone(),
            state.session_store.clone(),
            conversation.id.clone()
        )
        .with_dynamic_metadata(&write_metadata)
        .list_tools()
        .contains(&name));
        let wrapped = PlanModeToolHost::new(
            host.clone(),
            state.session_store.clone(),
            conversation.id.clone(),
        )
        .with_dynamic_metadata(&host.metadata());
        let result: Value =
            serde_json::from_str(&wrapped.call(&name, r#"{"input":"中"}"#).await.unwrap()).unwrap();
        assert_eq!(result, json!({"score":20260914,"input_bytes":15}));
        agent_access::scope(
            Some(capture(&state, &conversation, "plan-message-two", None)),
            async {
                assert!(host.list_tools().is_empty());
                assert!(wrapped
                    .call(&name, r#"{"input":"other message"}"#)
                    .await
                    .is_err());
            },
        )
        .await;
        assert!(host.list_tools().contains(&name));
        let (status, _) = request(
            &state,
            "POST",
            &format!(
                "/api/v1/local-plugins/v2/installations/{}/revoke",
                reference["bundle_id"].as_str().unwrap()
            ),
            json!({"tenant_id":"local","project_id":"local-project","reference":reference}),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert!(wrapped.call(&name, r#"{"input":"revoked"}"#).await.is_err());
        import(&state, &bytes).await;
        let fresh = LocalPluginToolHostV2::new_plan(&state, &conversation)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(fresh.list_tools().len(), 1);
        control.request_cancel();
        assert!(fresh.list_tools().is_empty());
        state.release_agent_run_if_control(&conversation.id, &control);
        let next = state.claim_agent_run(&conversation.id, None).unwrap();
        assert!(fresh.list_tools().is_empty());
        state.release_agent_run_if_control(&conversation.id, &next);
    })
    .await;
}

#[tokio::test]
async fn child_signed_plugin_uses_own_execution_and_rejects_parent_sibling_cancelled_context() {
    let (state, bytes) = setup().await;
    import(&state, &bytes).await;
    let (conversation, run) = run(&state).await;
    let parent = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    let native = capture(&state, &conversation, &run.message_id, Some(&run.id));
    agent_access::scope(Some(native),async {
        let parent_host=LocalPluginToolHostV2::new(&state,&conversation,&run).await.unwrap().unwrap();
        let host=Arc::new(LocalPluginToolHostV2::new_child(&state,&conversation,&run,"child-one").await.unwrap().unwrap());
        let name=host.metadata().keys().next().unwrap().clone();
        assert!(host.list_tools().is_empty());
        let wrapped=AuthorizedRunToolHost::with_dynamic_metadata(host.clone(),state.session_store.clone(),run.clone(),host.metadata());
        assert!(wrapped.call(&name,r#"{"input":"parent"}"#).await.is_err());
        let identity=ChildIdentityV2{execution_id:"child-execution-one".into(),subagent_id:"child-one".into(),run_id:run.id.clone(),revision:run.revision};
        let observer=local_runtime::subagent_runtime::child_timeline::ChildTimelineObserver::new(state.clone(),&conversation,&run,"child-one".into(),host.clone(),Some(host.clone()),BTreeMap::new());
        observer.on_tool_call(&identity.execution_id,0,&name,r#"{"password":"no-parent-leak"}"#).await.unwrap();
        assert!(state.session_store.timeline(&conversation.id,100).unwrap().is_empty());
        child_scope(identity.clone(),async { assert!(host.list_tools().is_empty()); }).await;
        state.subagent_controls.register(&identity.execution_id,&conversation.id,&run,"child-one","builtin:all-access",parent.clone()).unwrap();
        child_scope(identity.clone(),async {
            assert!(parent_host.list_tools().is_empty());
            assert_eq!(host.list_tools(),vec![name.clone()]);
            let value:Value=serde_json::from_str(&wrapped.call(&name,r#"{"input":"中"}"#).await.unwrap()).unwrap();
            assert_eq!(value,json!({"score":20260914,"input_bytes":15}));
            observer.on_tool_call("forged-execution",0,&name,"{}").await.unwrap();
            assert!(state.session_store.timeline(&conversation.id,100).unwrap().is_empty());
            observer.on_tool_call(&identity.execution_id,0,&name,r#"{"input":"visible","password":"child-secret","nested":{"api_key":"secret"}}"#).await.unwrap();
            let event=state.session_store.timeline(&conversation.id,100).unwrap().pop().unwrap();
            let redacted:Value=serde_json::from_str(event["payload"]["tool_input"].as_str().unwrap()).unwrap();
            assert_eq!(redacted["input"],"visible");
            assert_eq!(redacted["password"],"[REDACTED]");
            assert_eq!(redacted["nested"]["api_key"],"[REDACTED]");
            observer.on_tool_error(&identity.execution_id,0,"plugin__forged",r#"{"password":"forged-secret"}"#,&CoreError::Tool("raw-secret-error".into())).await.unwrap();
            let event=state.session_store.timeline(&conversation.id,100).unwrap().pop().unwrap();
            assert_eq!(event["payload"]["tool_input"],"[UNAVAILABLE]");
            assert!(!event.to_string().contains("raw-secret-error"));
            // Production profile filtering still intersects the verified tool with the actor surface.
            let agent=json!({"id":"parent","name":"parent","status":"active","enabled":true,"allowed_tools":[name,"read"],"allowed_skills":["*"],"allowed_mcp_servers":[],"can_spawn":true,"spawn_policy":{"allowed_subagents":["*"]}});
            let child=json!({"id":"child-one","name":"child-one","status":"active","enabled":true,"allowed_tools":["read"],"allowed_skills":["*"],"allowed_mcp_servers":[]});
            let profile=local_runtime::execution_profile::ExecutionProfile::resolve("parent",&agent,None,Some(&child)).unwrap();
            let filtered=local_runtime::execution_profile::ProfiledToolHost::new(host.clone(),&profile);
            assert!(filtered.list_tools().is_empty());
            assert!(filtered.call(&name,r#"{"input":"excluded"}"#).await.is_err());
            let filtered_observer=local_runtime::subagent_runtime::child_timeline::ChildTimelineObserver::new(state.clone(),&conversation,&run,"child-one".into(),Arc::new(filtered),Some(host.clone()),BTreeMap::new());
            filtered_observer.on_tool_call(&identity.execution_id,1,&name,r#"{"input":"excluded-secret"}"#).await.unwrap();
            assert_eq!(state.session_store.timeline(&conversation.id,100).unwrap().last().unwrap()["payload"]["tool_input"],"[UNAVAILABLE]");
        }).await;
        let mut sibling=identity.clone(); sibling.subagent_id="child-two".into();
        let event_count=state.session_store.timeline(&conversation.id,100).unwrap().len();
        child_scope(sibling,async {assert!(wrapped.call(&name,r#"{"input":"sibling"}"#).await.is_err());observer.on_tool_call(&identity.execution_id,2,&name,"{}").await.unwrap();}).await;
        let mut other_execution=identity.clone();other_execution.execution_id="unregistered".into();
        child_scope(other_execution,async {assert!(host.list_tools().is_empty());}).await;
        parent.request_cancel();
        child_scope(identity.clone(), async { assert!(host.list_tools().is_empty()); observer.on_tool_result(&identity.execution_id,2,&name,"{}",r#"{"input":"after-cancel"}"#).await.unwrap(); }).await;
        state.subagent_controls.complete(&identity.execution_id);
        child_scope(identity,async {assert!(wrapped.call(&name,r#"{"input":"completed"}"#).await.is_err());}).await;
        assert_eq!(state.session_store.timeline(&conversation.id,100).unwrap().len(),event_count);
        state.release_agent_run_if_control(&conversation.id,&parent);
    }).await;
}

#[tokio::test]
async fn production_subagent_factory_delegates_real_signed_read_plugin_through_approved_parent() {
    use agistack_adapters_mem::ScriptedLlm;
    use agistack_core::agent::types::AgentAction;
    let (state, bytes) = setup().await;
    import(&state, &bytes).await;
    let (conversation, run) = run(&state).await;
    let parent = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    let native = capture(&state, &conversation, &run.message_id, Some(&run.id));
    agent_access::scope(Some(native),async {
        let name=LocalPluginToolHostV2::new(&state,&conversation,&run).await.unwrap().unwrap().list_tools().pop().unwrap();
        let agent=json!({"id":"qa-plugin-parent","name":"qa-plugin-parent","enabled":true,"status":"active","allowed_tools":[name,"subagent"],"allowed_skills":["*"],"allowed_mcp_servers":[],"can_spawn":true,"spawn_policy":{"allowed_subagents":["qa-plugin-child"]}});
        let child=json!({"id":"qa-plugin-child","name":"qa-plugin-child","display_name":"QA plugin child","tenant_id":"local","project_id":"local-project","status":"active","enabled":true,"allowed_tools":[name],"allowed_skills":["*"],"allowed_mcp_servers":[]});
        for (kind,scope,owner,id,value) in [(local_runtime::ManagedResourceKind::Agent,"project","local-project","qa-plugin-parent",agent.clone()),(local_runtime::ManagedResourceKind::SubAgent,"tenant","local","qa-plugin-child",child)] {
            state.session_store.put_managed_resource(kind,scope,owner,id,"active",None,value,chrono::Utc::now().timestamp_millis()).unwrap();
        }
        let profile=local_runtime::execution_profile::ExecutionProfile::resolve("qa-plugin-parent",&agent,None,None).unwrap();
        let host=state.subagent_agent_tool_host(&conversation,&run,&profile,&[],Arc::new(ScriptedLlm::new(vec![AgentAction::CallTool {tool:name.clone(), input_json:r#"{"input":"中"}"#.into()},AgentAction::Finish {answer:"child completed".into()}])),4).await.unwrap().unwrap();
        let metadata=host.authority_metadata_by_name();
        assert_eq!(metadata["subagent"].effect,ToolEffect::Read);
        let wrapped=AuthorizedRunToolHost::with_dynamic_metadata(Arc::new(host),state.session_store.clone(),run.clone(),metadata);
        let output=wrapped.call("subagent",r#"{"subagent_id":"qa-plugin-child","task":"Call marker"}"#).await.unwrap();
        assert!(output.contains("child completed"));
        let result: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(result["run_id"], run.id);
        assert_eq!(result["run_revision"], run.revision);
        let timeline = state.session_store.timeline(&conversation.id, 100).unwrap();
        let child_events = timeline.iter().filter(|item| item["type"] == "subagent_tool_call" || item["type"] == "subagent_tool_result").collect::<Vec<_>>();
        assert_eq!(child_events.len(), 2);
        for event in &child_events {
            assert_eq!(event["payload"]["execution_id"], result["execution_id"]);
            assert_eq!(event["payload"]["parent_run_id"], run.id);
            assert_eq!(event["payload"]["parent_run_revision"], run.revision);
            assert_eq!(event["payload"]["subagent_id"], "qa-plugin-child");
            assert_eq!(event["payload"]["tool_name"], name);
            assert!(event.get("toolName").is_none());
        }
        assert_eq!(serde_json::from_str::<Value>(child_events[1]["payload"]["tool_output"].as_str().unwrap()).unwrap(), json!({"score":20260914,"input_bytes":15}));
        assert!(!timeline.iter().any(|item| item["type"] == "act" || item["type"] == "observe"));
        let invocations=state.session_store.list_tool_invocations(&conversation.id).unwrap();
        assert!(invocations.iter().any(|row| row.tool_name==name && row.status==local_runtime::tool_authority::InvocationStatus::Completed));
        state.release_agent_run_if_control(&conversation.id,&parent);
    }).await;
}

#[tokio::test]
async fn authenticated_plan_http_request_advertises_and_executes_signed_plugin() {
    native_plan_request_advertises_and_executes_signed_plugin(false, false).await;
}
#[tokio::test]
async fn authenticated_plan_websocket_request_advertises_and_executes_signed_plugin() {
    native_plan_request_advertises_and_executes_signed_plugin(true, false).await;
}
#[tokio::test]
async fn unbound_native_http_and_websocket_discover_load_skill_then_call_real_plugin() {
    native_plan_request_advertises_and_executes_signed_plugin(false, true).await;
    native_plan_request_advertises_and_executes_signed_plugin(true, true).await;
}
async fn native_plan_request_advertises_and_executes_signed_plugin(websocket: bool, discover_skill: bool) {
    use agistack_core::{
        agent::types::{AgentAction, TranscriptEntry},
        model::Episode,
        ports::{CoreResult, LlmPort, MemoryDraft, ToolDefinition},
    };
    struct InspectLlm(std::sync::Mutex<Vec<ToolDefinition>>, bool);
    #[async_trait::async_trait]
    impl LlmPort for InspectLlm {
        async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
            unreachable!()
        }
        async fn decide(
            &self,
            _: &str,
            _: u64,
            _: &[TranscriptEntry],
            _: &[String],
        ) -> CoreResult<AgentAction> {
            panic!("typed catalog required")
        }
        async fn decide_with_tools(
            &self,
            _: &str,
            round: u64,
            transcript: &[TranscriptEntry],
            tools: &[ToolDefinition],
        ) -> CoreResult<AgentAction> {
            *self.0.lock().unwrap() = tools.to_vec();
            if self.1 && round < 2 {
                let tool = if round == 0 { "skill_list" } else { "skill_loader" };
                assert!(tools.iter().any(|item| item.name == tool), "unbound Plan must advertise {tool}");
                if round == 1 { assert!(transcript.iter().any(|item| item.content.contains("native-marker-skill"))); }
                return Ok(AgentAction::CallTool { tool: tool.into(), input_json: if round == 0 { "{}".into() } else { r#"{"skill_id":"native-marker-skill"}"#.into() }});
            }
            if round == if self.1 { 2 } else { 0 } {
                if self.1 { assert!(transcript.iter().any(|item| item.content.contains("SIGNED_SKILL_GUIDANCE") && item.content.contains("available_tools"))); }
                let tool = tools
                    .iter()
                    .find(|tool| {
                        tool.description
                            .as_deref()
                            .is_some_and(|value| value.contains("qa_marketplace_marker"))
                    })
                    .expect("real native Plan catalog must include verified marker");
                Ok(AgentAction::CallTool {
                    tool: tool.name.clone(),
                    input_json: r#"{"input":"中"}"#.into(),
                })
            } else {
                assert!(transcript
                    .iter()
                    .any(|item| item.content.contains("20260914") && item.content.contains("15")));
                Ok(AgentAction::Finish {
                    answer: "real HTTP plugin completed".into(),
                })
            }
        }
    }
    let (state, bytes) = setup().await;
    let (status,body)=request(&state,"POST","/api/v1/workspace-context/switch",json!({"tenant_id":"northstar","project_id":"desktop-client","expected_revision":0,"idempotency_key":"native-scope-switch"})).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let payload = json!({"tenant_id":"northstar","project_id":"desktop-client","archive_base64":STANDARD.encode(&bytes)});
    let (status, preview) = request(
        &state,
        "POST",
        "/api/v1/local-plugins/v2/installations/inspect",
        payload.clone(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    let mut payload = payload;
    payload["reference"] = preview["reference"].clone();
    payload["approved_permissions"] = preview["declared_permissions"].clone();
    let (status, body) = request(
        &state,
        "POST",
        "/api/v1/local-plugins/v2/installations/import",
        payload,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let mut reconciler = desktop_reconciler(&state);
    activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
        .await
        .unwrap();
    let (status,conversation)=request(&state,"POST","/api/v1/agent/conversations",json!({"project_id":"desktop-client","title":"HTTP native work scope","agent_config":{"capability_mode":"work","selected_agent_id":"builtin:all-access"}})).await;
    assert_eq!(status, StatusCode::OK, "{conversation}");
    let id = conversation["id"].as_str().unwrap();
    assert!(conversation["workspace_id"].is_null());
    if discover_skill {
        state.session_store.put_managed_resource(local_runtime::ManagedResourceKind::Skill,"project","desktop-client","native-marker-skill","active",None,json!({"id":"native-marker-skill","name":"Native marker guide","status":"active","tools":["*"],"full_content":"SIGNED_SKILL_GUIDANCE: call the exact currently available marker tool and report its structured result."}),chrono::Utc::now().timestamp_millis()).unwrap();
    }
    let llm = Arc::new(InspectLlm(std::sync::Mutex::new(vec![]), discover_skill));
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    let mut ws_server = None;
    let mut ws_client = None;
    if websocket {
        use futures_util::{SinkExt, StreamExt};
        use tokio_tungstenite::tungstenite::client::IntoClientRequest;
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let app = local_runtime::local_router_with_generation_required(state.clone());
        ws_server = Some(tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        }));
        let mut request = format!("ws://{address}/api/v1/agent/ws")
            .into_client_request()
            .unwrap();
        request
            .headers_mut()
            .insert("authorization", format!("Bearer {TOKEN}").parse().unwrap());
        request
            .headers_mut()
            .insert("x-agistack-launch", TOKEN.parse().unwrap());
        let mut invalid = request.clone();
        invalid.headers_mut().insert(
            "authorization",
            "Bearer invalid-fixture-session".parse().unwrap(),
        );
        assert!(tokio_tungstenite::connect_async(invalid).await.is_err());
        let (mut socket, _) = tokio_tungstenite::connect_async(request).await.unwrap();
        socket.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"send_message","project_id":"other-project","conversation_id":id,"message":"Must reject scope","message_id":"wrong-scope-message"}).to_string())).await.unwrap();
        let rejected = socket.next().await.unwrap().unwrap().into_text().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&rejected).unwrap()["code"],
            "project_context_mismatch"
        );
        assert!(llm.0.lock().unwrap().is_empty());
        socket.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"send_message","project_id":"desktop-client","conversation_id":id,"message":"Call signed marker","message_id":"ws-plugin-plan-message"}).to_string())).await.unwrap();
        ws_client = Some(socket);
    } else {
        let (status,body)=request(&state,"POST",&format!("/api/v1/agent/conversations/{id}/messages"),json!({"project_id":"desktop-client","message":"Call signed marker","message_id":"http-plugin-plan-message"})).await;
        assert_eq!(status, StatusCode::OK, "{body}");
    }
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            if state
                .session_store
                .timeline(id, 100)
                .unwrap()
                .iter()
                .any(|item| item["type"] == "assistant_message")
            {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    assert!(llm
        .0
        .lock()
        .unwrap()
        .iter()
        .any(|tool| tool.name.starts_with("plugin__")));
    let timeline = state.session_store.timeline(id, 100).unwrap();
    if discover_skill {
        assert!(state.session_store.execution_selection(id).unwrap().unwrap_or_default().forced_skill_id.is_none());
        let loaded=timeline.iter().find(|item|item["type"] == "observe" && item["toolName"] == "skill_loader").unwrap();
        let output:Value=serde_json::from_str(loaded["toolOutput"].as_str().unwrap()).unwrap();
        assert_eq!(output["execution_started"],false);
        assert_eq!(output["authority_changed"],false);
        assert!(output["available_tools"].as_array().unwrap().iter().any(|name|name.as_str().is_some_and(|name| name.starts_with("plugin__"))));
    }
    let observed = timeline
        .iter()
        .find(|item| {
            item["type"] == "observe"
                && item["toolName"]
                    .as_str()
                    .is_some_and(|name| name.starts_with("plugin__"))
        })
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(observed["toolInput"].as_str().unwrap()).unwrap(),
        json!({"input":"中"})
    );
    assert_eq!(
        serde_json::from_str::<Value>(observed["toolOutput"].as_str().unwrap()).unwrap(),
        json!({"score":20260914,"input_bytes":15})
    );
    if let Some(mut socket) = ws_client {
        socket.close(None).await.unwrap();
    }
    if let Some(server) = ws_server {
        server.abort();
    }
}
