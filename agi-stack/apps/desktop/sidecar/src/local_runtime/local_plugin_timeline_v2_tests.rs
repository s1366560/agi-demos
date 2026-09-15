use super::*;

#[tokio::test]
async fn child_read_observer_rejects_late_results_after_native_signout_or_scope_switch() {
    use agistack_core::agent::ReActObserver;
    use local_runtime::local_plugin_tool_host_v2::identity::{child_scope, ChildIdentityV2};
    for signout in [true, false] {
        let (state, _) = setup().await;
        let (conversation, run) = run(&state).await;
        let control = state.claim_agent_run(&conversation.id, Some(&run.id)).unwrap();
        let auth = state.session_store.validate_session_credential(TOKEN, chrono::Utc::now().timestamp_millis()).unwrap().unwrap();
        let native = RunAuthorization::capture(auth, Some(Arc::new(state.platform_plugin_authority_v2.acquire_generation().unwrap())), &conversation, &run.message_id, Some(&run.id)).unwrap();
        agent_access::scope(Some(native), async {
            let root = &run.environment.as_ref().unwrap().workspace_path;
            std::fs::write(std::path::Path::new(root).join("observer-read.txt"), "CHILD_READ_BEFORE_SIGNOUT").unwrap();
            let tools = Arc::new(local_runtime::LocalToolHost::new(root).unwrap());
            let observer = local_runtime::subagent_runtime::child_timeline::ChildTimelineObserver::new(
                state.clone(), &conversation, &run, "read-child".into(), tools.clone(), None, Default::default(),
            );
            let identity = ChildIdentityV2 { execution_id:"read-child-execution".into(), subagent_id:"read-child".into(), run_id:run.id.clone(), revision:run.revision };
            state.subagent_controls.register(&identity.execution_id, &conversation.id, &run, "read-child", "builtin:all-access", control.clone()).unwrap();
            child_scope(identity.clone(), async {
                let input = r#"{"path":"observer-read.txt"}"#;
                let output = tools.call("read", input).await.unwrap();
                assert!(output.contains("CHILD_READ_BEFORE_SIGNOUT"));
                observer.on_tool_result(&identity.execution_id, 0, "read", input, &output).await.unwrap();
                let events = state.session_store.timeline(&conversation.id, 100).unwrap();
                assert_eq!(events.len(), 1);
                assert!(events[0]["payload"]["tool_output"].as_str().unwrap().contains("CHILD_READ_BEFORE_SIGNOUT"));
                let (status, response) = if signout {
                    request(&state, "POST", "/api/v1/auth/signout", json!({})).await
                } else {
                    request(&state, "POST", "/api/v1/workspace-context/switch", json!({"tenant_id":"northstar","project_id":"desktop-client","expected_revision":0,"idempotency_key":"observer-scope-switch"})).await
                };
                assert_eq!(status, StatusCode::OK, "{response}");
                observer.on_tool_call(&identity.execution_id, 1, "read", input).await.unwrap();
                observer.on_tool_result(&identity.execution_id, 1, "read", input, &output).await.unwrap();
                observer.on_tool_error(&identity.execution_id, 1, "read", input, &agistack_core::ports::CoreError::Tool("private error".into())).await.unwrap();
                assert_eq!(state.session_store.timeline(&conversation.id,100).unwrap().len(), 1, "late child events must not persist after native authority is invalidated");
            }).await;
            state.release_agent_run_if_control(&conversation.id, &control);
        }).await;
    }
}

#[tokio::test]
async fn signed_timeline_metadata_rejects_unknown_filtered_expired_and_rebound_authority() {
    let (state, bytes) = setup().await;
    let reference = import(&state, &bytes).await;
    local_runtime::tests::seed_plan_conversation(&state, "plugin-timeline");
    let conversation = state
        .session_store
        .conversation("plugin-timeline")
        .unwrap()
        .unwrap();
    let auth = state
        .session_store
        .validate_session_credential(TOKEN, chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let capture = RunAuthorization::capture(
        auth,
        Some(Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        )),
        &conversation,
        "timeline-message",
        None,
    )
    .unwrap();
    agent_access::scope(Some(capture),async {
        let control=state.claim_agent_run(&conversation.id,None).unwrap();
        let host=Arc::new(LocalPluginToolHostV2::new_plan(&state,&conversation).await.unwrap().unwrap());
        let name=host.list_tools().pop().unwrap();
        let metadata=host.timeline_metadata();
        assert_eq!(metadata.redact("plugin__forged",r#"{"password":"never-visible"}"#),None);
        assert_eq!(host.timeline_metadata().restrict_to(&["read".into()]).redact(&name,"{}"),None);
        assert_eq!(metadata.redact(&name,"invalid JSON"),Some("[UNPARSEABLE]".into()));
        let redacted:Value=serde_json::from_str(&metadata.redact(&name,r#"{"input":"marker","password":"never-visible","nested":[{"api_key":"also-hidden"}]}"#).unwrap()).unwrap();
        assert_eq!(redacted["input"],"marker");
        assert_eq!(redacted["password"],"[REDACTED]");
        assert_eq!(redacted["nested"][0]["api_key"],"[REDACTED]");
        state.session_store.put_managed_resource(local_runtime::ManagedResourceKind::Agent,"project",&conversation.project_id,"timeline-read-agent","active",None,json!({"id":"timeline-read-agent","name":"timeline-read-agent","enabled":true,"status":"active","allowed_tools":["read"],"allowed_skills":[],"allowed_mcp_servers":[],"can_spawn":false,"spawn_policy":{"allowed_subagents":[]}}),chrono::Utc::now().timestamp_millis()).unwrap();
        state.session_store.save_execution_selection(&conversation.id,"timeline-message",&local_runtime::execution_selection::ExecutionSelection {agent_id:Some("timeline-read-agent".into()),..Default::default()},&local_runtime::now_iso()).unwrap();
        let (_,filtered)=state.agent_engine_for_role_with_plugin_metadata(&conversation,None,None).await.unwrap();
        assert_eq!(filtered.redact(&name,r#"{"input":"excluded-by-profile"}"#),None);
        state.session_store.save_execution_selection(&conversation.id,"timeline-message",&local_runtime::execution_selection::ExecutionSelection {agent_id:Some("builtin:all-access".into()),..Default::default()},&local_runtime::now_iso()).unwrap();
        let observer=local_runtime::LocalTimelineObserver::new(state.clone(),conversation.id.clone(),"timeline-message".into(),state.execution_profile(&conversation).unwrap(),"Inspect signed result".into());
        assert_eq!(observer.redact_tool_payload(&name,"{}"),"[UNAVAILABLE]");
        observer.set_plugin_metadata(metadata);
        assert_eq!(observer.redact_tool_payload("plugin__forged","{}"),"[UNAVAILABLE]");
        assert_eq!(observer.redact_tool_payload(&name,r#"{"score":20260914,"input_bytes":15}"#),r#"{"input_bytes":15,"score":20260914}"#);
        // Reimport is an actual verified publication with a new generation, even for the same bytes.
        import(&state,&bytes).await;
        assert_eq!(observer.redact_tool_payload(&name,"{}"),"[UNAVAILABLE]");
        let fresh=Arc::new(LocalPluginToolHostV2::new_plan(&state,&conversation).await.unwrap().unwrap());
        observer.set_plugin_metadata(fresh.timeline_metadata());
        assert_eq!(observer.redact_tool_payload(&name,"{}"),"{}");
        let (status,body)=request(&state,"POST",&format!("/api/v1/local-plugins/v2/installations/{}/revoke",reference["bundle_id"].as_str().unwrap()),json!({"tenant_id":"local","project_id":"local-project","reference":reference})).await;
        assert_eq!(status,StatusCode::OK,"{body}");
        assert_eq!(observer.redact_tool_payload(&name,r#"{"input":"revoked-secret"}"#),"[UNAVAILABLE]");
        import(&state,&bytes).await;
        let fresh=Arc::new(LocalPluginToolHostV2::new_plan(&state,&conversation).await.unwrap().unwrap());
        observer.set_plugin_metadata(fresh.timeline_metadata());
        state.release_agent_run_if_control(&conversation.id,&control);
        assert_eq!(observer.redact_tool_payload(&name,r#"{"input":"after-turn"}"#),"[UNAVAILABLE]");
    }).await;
}
