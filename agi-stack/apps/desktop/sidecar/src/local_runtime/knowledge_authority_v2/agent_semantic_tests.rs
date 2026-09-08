use super::*;
use crate::local_runtime::{
    knowledge_authority_v2::agent_access::{self, RunAuthorization},
    ConversationRunMode, LocalConversation,
};

#[tokio::test]
async fn agent_access_semantic_uses_current_configuration_and_discards_late_model_switch() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let a = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "a")
        .await
        .unwrap();
    let config = f
        .operation
        .select_index_build(&f.state, &f.auth, &a, None)
        .unwrap();
    f.operation
        .index_one(&f.state, &f.auth, &config, IndexRunOptions::default())
        .await
        .unwrap();
    f.operation
        .promote_index_build(&f.state, &f.auth, &config, None)
        .unwrap();
    let b = f
        .operation
        .prepare_index_build(
            &f.state,
            &f.auth,
            &EmbeddingRoute {
                model_id: "other-embedding-model".into(),
                ..route
            },
            "b",
        )
        .await
        .unwrap();
    let c = LocalConversation {
        id: uuid::Uuid::new_v4().to_string(),
        tenant_id: f.auth.workspace.tenant_id.clone(),
        project_id: f.auth.workspace.project_id.clone(),
        title: "Semantic test".into(),
        workspace_id: None,
        capability_mode: Default::default(),
        current_mode: ConversationRunMode::Plan,
        created_at: crate::local_runtime::now_iso(),
        updated_at: crate::local_runtime::now_iso(),
    };
    f.state.session_store.insert_conversation(&c).unwrap();
    let grant = RunAuthorization::capture(
        f.auth.clone(),
        Some(f.operation._lease.clone()),
        &c,
        "semantic-message",
        None,
    )
    .unwrap();
    agent_access::scope(Some(grant),async {
        let host=agent_access::tool_host(&f.state,&c,None,"semantic-agent").unwrap();
        let input=r#"{"mode":"semantic","query":"query","limit":10,"rationale":"Find supporting concepts"}"#;
        let output:Value=serde_json::from_str(&host.call("knowledge_search",input).await.unwrap()).unwrap();
        assert_eq!(output["hits"][0]["source"]["memory_id"],f.source.memory_id);
        assert_eq!(output["hits"][0]["config_revision"],1);
        let source=json!({"reference":output["hits"][0]["reference"],"rationale":"Read supporting source"}).to_string();
        assert!(host.call("knowledge_source",&source).await.unwrap().contains("generation-owned content"));
        endpoint.pause();
        let query=host.call("knowledge_search",input);
        let change=async {
            endpoint.entered().await;
            f.operation.select_index_build(&f.state,&f.auth,&b,Some(1)).unwrap();
            endpoint.release();
        };
        let (result,())=tokio::join!(query,change);
        assert!(result.is_err());
        assert!(host.call("knowledge_source",&source).await.is_err());
        let requests=endpoint.state.requests.lock().unwrap().len();
        assert!(host.call("knowledge_search",input).await.is_err());
        assert_eq!(requests,endpoint.state.requests.lock().unwrap().len());
        let audits=f.state.session_store.timeline(&c.id,100).unwrap();
        let serialized=serde_json::to_string(&audits).unwrap();
        assert!(!serialized.contains("embedding-fixture-key"));
        assert!(serialized.contains("semantic-agent"));
    }).await;
}
