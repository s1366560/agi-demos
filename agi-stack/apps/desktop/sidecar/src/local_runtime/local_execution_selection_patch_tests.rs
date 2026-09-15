use super::*;

#[tokio::test]
async fn explicit_selection_patch_reads_preserves_clears_and_rejects_invalid_or_active_mutations() {
    let (state,_) = setup().await;
    let (status,conversation)=request(&state,"POST","/api/v1/agent/conversations",json!({"project_id":"local-project","title":"Persistent binding"})).await;
    assert_eq!(status,StatusCode::OK,"{conversation}");
    let id=conversation["id"].as_str().unwrap();
    assert!(conversation["execution_selection"]["forced_skill_id"].is_null());
    state.session_store.put_managed_resource(local_runtime::ManagedResourceKind::Skill,"project","local-project","binding-skill","active",None,json!({"id":"binding-skill","name":"Binding skill","status":"active","tools":["*"],"full_content":"Scope guide"}),chrono::Utc::now().timestamp_millis()).unwrap();
    let path=format!("/api/v1/agent/conversations/{id}/config");
    let (status,_)=request(&state,"PATCH",&path,json!({"execution_selection":null})).await;
    assert!(status.is_client_error());
    let (status,bound)=request(&state,"PATCH",&path,json!({"execution_selection":{"forced_skill_id":"binding-skill"}})).await;
    assert_eq!(status,StatusCode::OK,"{bound}");
    assert_eq!(bound["execution_selection"]["forced_skill_id"],"binding-skill");
    let (status,preserved)=request(&state,"PATCH",&path,json!({"execution_selection":{}})).await;
    assert_eq!(status,StatusCode::OK);
    assert_eq!(preserved["execution_selection"],bound["execution_selection"]);
    let (status,reloaded)=request(&state,"GET",&format!("/api/v1/agent/conversations/{id}/session?tenant_id=local&project_id=local-project"),json!({})).await;
    assert_eq!(status,StatusCode::OK);
    assert_eq!(reloaded["conversation"]["execution_selection"],bound["execution_selection"]);
    for patch in [json!({"forced_skill_id":"foreign"}),json!({"agent_id":"missing-agent"}),json!({"subagent_id":"missing-child"}),json!({"forced_skill_id":""}),json!({"unrecognized":null})] {
        let (status,_)=request(&state,"PATCH",&path,json!({"execution_selection":patch})).await;
        assert!(status.is_client_error());
        assert_eq!(state.session_store.execution_selection(id).unwrap().unwrap().forced_skill_id.as_deref(),Some("binding-skill"));
    }
    let control=state.claim_agent_run(id,None).unwrap();
    let (status,_)=request(&state,"PATCH",&path,json!({"execution_selection":{"forced_skill_id":null}})).await;
    assert_eq!(status,StatusCode::CONFLICT);
    state.release_agent_run_if_control(id,&control);
    let (status,cleared)=request(&state,"PATCH",&path,json!({"execution_selection":{"forced_skill_id":null,"agent_id":null,"subagent_id":null}})).await;
    assert_eq!(status,StatusCode::OK,"{cleared}");
    assert_eq!(cleared["execution_selection"],json!({"agent_id":null,"forced_skill_id":null,"subagent_id":null}));
    state.session_store.save_execution_selection(id,"next-empty-message",&local_runtime::execution_selection::ExecutionSelection::default(),&local_runtime::now_iso()).unwrap();
    assert_eq!(state.session_store.execution_selection(id).unwrap().unwrap(),local_runtime::execution_selection::ExecutionSelection::default());
    let (status,_) = request(&state,"POST","/api/v1/workspace-context/switch",json!({"tenant_id":"northstar","project_id":"desktop-client","expected_revision":0,"idempotency_key":"selection-context-switch"})).await;
    assert_eq!(status,StatusCode::OK);
    let (status,_)=request(&state,"PATCH",&path,json!({"execution_selection":{"forced_skill_id":"binding-skill"}})).await;
    assert!(status.is_client_error());
    assert!(state.session_store.execution_selection(id).unwrap().unwrap().forced_skill_id.is_none());
}

#[tokio::test]
async fn selection_patch_cannot_change_a_persisted_approved_run_without_live_worker() {
    let (state,_) = setup().await;
    let (conversation,_run)=run(&state).await;
    let (status,_)=request(&state,"PATCH",&format!("/api/v1/agent/conversations/{}/config",conversation.id),json!({"execution_selection":{"forced_skill_id":null}})).await;
    assert_eq!(status,StatusCode::CONFLICT);
}
