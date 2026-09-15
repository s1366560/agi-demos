use super::*;
use local_runtime::{
    execution_profile::ExecutionProfile, skill_discovery_tool_host::SkillDiscoveryToolHost,
    ManagedResourceKind,
};

fn save(
    state: &LocalRuntimeState,
    kind: ManagedResourceKind,
    scope: &str,
    owner: &str,
    id: &str,
    value: Value,
) {
    state
        .session_store
        .put_managed_resource(
            kind,
            scope,
            owner,
            id,
            "active",
            None,
            value,
            chrono::Utc::now().timestamp_millis(),
        )
        .unwrap();
}

#[tokio::test]
async fn skill_discovery_is_exact_scoped_current_and_does_not_expand_signed_tools() {
    let (state, bytes) = setup().await;
    import(&state, &bytes).await;
    let (conversation, run) = run(&state).await;
    let control = state
        .claim_agent_run(&conversation.id, Some(&run.id))
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
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    agent_access::scope(Some(capture), async {
        let plugin=Arc::new(LocalPluginToolHostV2::new(&state,&conversation,&run).await.unwrap().unwrap());
        let tool=plugin.list_tools().pop().unwrap();
        let skill=json!({"id":"scope-skill","name":"Exact guide","status":"active","tools":[tool,"write"],"full_content":"REAL_GUIDE"});
        save(&state,ManagedResourceKind::Skill,"project","local-project","scope-skill",skill.clone());
        save(&state,ManagedResourceKind::Skill,"project","other-project","foreign",json!({"id":"foreign","name":"Foreign guide","status":"active","tools":["*"],"full_content":"FOREIGN_SECRET"}));
        save(&state,ManagedResourceKind::Skill,"tenant","local","wrong-project",json!({"id":"wrong-project","name":"Wrong project","status":"active","project_id":"other-project","tools":["*"],"full_content":"FOREIGN_SECRET"}));
        save(&state,ManagedResourceKind::Agent,"project","local-project","discovery-agent",json!({"id":"discovery-agent","name":"Discovery agent","enabled":true,"status":"active","allowed_tools":["*"],"allowed_skills":["*"],"allowed_mcp_servers":[],"can_spawn":false,"spawn_policy":{"allowed_subagents":[]}}));
        state.session_store.save_execution_selection(&conversation.id,&run.message_id,&local_runtime::execution_selection::ExecutionSelection{agent_id:Some("discovery-agent".into()),..Default::default()},&local_runtime::now_iso()).unwrap();
        let profile=state.execution_profile(&conversation).unwrap();
        let host=SkillDiscoveryToolHost::new(&state,&conversation,Some(&run),&profile,plugin.clone()).unwrap().unwrap();
        let list:Value=serde_json::from_str(&host.call("skill_list","{}").await.unwrap()).unwrap();
        assert!(!list.to_string().contains("Foreign guide"));
        assert!(!list.to_string().contains("Wrong project"));
        let loaded:Value=serde_json::from_str(&host.call("skill_loader",r#"{"skill_id":"scope-skill"}"#).await.unwrap()).unwrap();
        assert_eq!(loaded["content"],"REAL_GUIDE");
        assert_eq!(loaded["available_tools"],json!([tool]));
        assert_eq!(loaded["declared_tools"],json!([tool,"write"]));
        assert_eq!(loaded["authority_changed"],false);
        assert_eq!(plugin.list_tools(),vec![tool.clone()]);
        for bad in [r#"{"skill_id":"foreign"}"#,r#"{"name":"Exact"}"#,r#"{"name":"Exact guide","skill_id":"scope-skill"}"#,r#"{"skill_id":"scope-skill","tenant_id":"other"}"#] {
            assert!(host.call("skill_loader",bad).await.is_err());
        }
        assert!(host.call("skill_list",r#"{"query":"guide"}"#).await.is_err());
        save(&state,ManagedResourceKind::Skill,"tenant","local","duplicate",json!({"id":"duplicate","name":"Exact guide","status":"active","tools":[tool],"full_content":"OTHER_GUIDE"}));
        assert!(host.call("skill_loader",r#"{"name":"Exact guide"}"#).await.is_err());
        assert!(host.call("skill_loader",r#"{"skill_id":"scope-skill"}"#).await.is_ok());
        let mut disabled=skill.clone(); disabled["enabled"]=json!(false);
        save(&state,ManagedResourceKind::Skill,"project","local-project","scope-skill",disabled);
        assert!(host.call("skill_loader",r#"{"skill_id":"scope-skill"}"#).await.is_err());
        save(&state,ManagedResourceKind::Skill,"project","local-project","scope-skill",skill.clone());
        let mut agent=state.session_store.managed_resource(ManagedResourceKind::Agent,"project","local-project","discovery-agent").unwrap().unwrap();
        let original=agent.clone(); agent["allowed_skills"]=json!([]);
        save(&state,ManagedResourceKind::Agent,"project","local-project","discovery-agent",agent);
        assert!(host.call("skill_loader",r#"{"skill_id":"scope-skill"}"#).await.is_err());
        save(&state,ManagedResourceKind::Agent,"project","local-project","discovery-agent",original.clone());
        assert!(host.call("skill_loader",r#"{"skill_id":"scope-skill"}"#).await.is_ok());
        let mut narrowed=original.clone(); narrowed["allowed_tools"]=json!(["skill_list"]);
        save(&state,ManagedResourceKind::Agent,"project","local-project","discovery-agent",narrowed);
        assert!(!host.list_tools().contains(&"skill_loader".into()));
        save(&state,ManagedResourceKind::Agent,"project","local-project","discovery-agent",original);
        state.session_store.save_execution_selection(&conversation.id,&run.message_id,&local_runtime::execution_selection::ExecutionSelection{agent_id:Some("builtin:all-access".into()),..Default::default()},&local_runtime::now_iso()).unwrap();
        assert!(host.list_tools().is_empty());
        state.session_store.save_execution_selection(&conversation.id,&run.message_id,&local_runtime::execution_selection::ExecutionSelection{agent_id:Some("discovery-agent".into()),..Default::default()},&local_runtime::now_iso()).unwrap();
        assert!(host.call("skill_loader",r#"{"skill_id":"scope-skill"}"#).await.is_ok());
        let (status,_) = request(&state,"POST","/api/v1/auth/signout",json!({})).await;
        assert_eq!(status,StatusCode::OK);
        assert!(host.call("skill_loader",r#"{"skill_id":"scope-skill"}"#).await.is_err());
        state.release_agent_run_if_control(&conversation.id,&control);
        assert!(host.list_tools().is_empty());
        assert!(host.call("skill_loader",r#"{"skill_id":"scope-skill"}"#).await.is_err());
    }).await;
}

#[tokio::test]
async fn child_skill_library_intersects_current_and_captured_agent_and_subagent_rosters() {
    use local_runtime::local_plugin_tool_host_v2::identity::{child_scope, ChildIdentityV2};
    let (state, bytes) = setup().await;
    import(&state, &bytes).await;
    let (conversation, run) = run(&state).await;
    let control = state
        .claim_agent_run(&conversation.id, Some(&run.id))
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
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    agent_access::scope(Some(capture),async {
        let agent=state.session_store.managed_resource(ManagedResourceKind::Agent,"project","local-project","builtin:all-access").unwrap().unwrap();
        let child=json!({"id":"skill-child","name":"Skill child","status":"active","enabled":true,"tenant_id":"local","project_id":"local-project","allowed_tools":["*"],"allowed_skills":["child-guide"],"allowed_mcp_servers":[]});
        save(&state,ManagedResourceKind::SubAgent,"tenant","local","skill-child",child.clone());
        for id in ["child-guide","parent-only"] {
            save(&state,ManagedResourceKind::Skill,"project","local-project",id,json!({"id":id,"name":id,"status":"active","tools":["*"],"full_content":"Guide"}));
        }
        let profile=ExecutionProfile::resolve("builtin:all-access",&agent,None,Some(&child)).unwrap();
        let plugin=Arc::new(LocalPluginToolHostV2::new_child(&state,&conversation,&run,"skill-child").await.unwrap().unwrap());
        let host=SkillDiscoveryToolHost::new(&state,&conversation,Some(&run),&profile,plugin).unwrap().unwrap();
        assert!(host.list_tools().is_empty());
        let identity=ChildIdentityV2{execution_id:"skill-child-execution".into(),subagent_id:"skill-child".into(),run_id:run.id.clone(),revision:run.revision};
        state.subagent_controls.register(&identity.execution_id,&conversation.id,&run,"skill-child","builtin:all-access",control.clone()).unwrap();
        child_scope(identity,async {
            assert!(host.call("skill_loader",r#"{"skill_id":"child-guide"}"#).await.is_ok());
            assert!(host.call("skill_loader",r#"{"skill_id":"parent-only"}"#).await.is_err());
            let mut read_only=child.clone(); read_only["allowed_tools"]=json!(["read"]);
            save(&state,ManagedResourceKind::SubAgent,"tenant","local","skill-child",read_only);
            assert!(host.list_tools().is_empty());
            assert!(host.call("skill_loader",r#"{"skill_id":"child-guide"}"#).await.is_err());
            save(&state,ManagedResourceKind::SubAgent,"tenant","local","skill-child",child.clone());
            let mut revoked=child.clone(); revoked["allowed_skills"]=json!([]);
            save(&state,ManagedResourceKind::SubAgent,"tenant","local","skill-child",revoked);
            assert!(host.call("skill_loader",r#"{"skill_id":"child-guide"}"#).await.is_err());
            let mut expanded=child.clone(); expanded["allowed_skills"]=json!(["*"]);
            save(&state,ManagedResourceKind::SubAgent,"tenant","local","skill-child",expanded);
            assert!(host.call("skill_loader",r#"{"skill_id":"parent-only"}"#).await.is_err());
        }).await;
        state.release_agent_run_if_control(&conversation.id,&control);
    }).await;
}
