use super::*;
use crate::local_runtime::{
    knowledge_authority_v2::agent_access::{self, RunAuthorization},
    ConversationRunMode, LocalConversation,
};

fn conversation(f: &Fixture) -> LocalConversation {
    let value = LocalConversation {
        id: uuid::Uuid::new_v4().to_string(),
        tenant_id: f.auth.workspace.tenant_id.clone(),
        project_id: f.auth.workspace.project_id.clone(),
        title: "Knowledge access test".into(),
        workspace_id: None,
        capability_mode: Default::default(),
        current_mode: ConversationRunMode::Plan,
        created_at: crate::local_runtime::now_iso(),
        updated_at: crate::local_runtime::now_iso(),
    };
    f.state.session_store.insert_conversation(&value).unwrap();
    value
}
fn authorization(f: &Fixture, c: &LocalConversation) -> Arc<RunAuthorization> {
    RunAuthorization::capture(
        f.auth.clone(),
        Some(f.operation._lease.clone()),
        c,
        "message",
        None,
    )
    .unwrap()
}
const SEARCH: &str = r#"{"mode":"literal","query":"generation-owned","limit":10,"rationale":"Locate the documented source"}"#;

#[tokio::test]
async fn agent_access_requires_explicit_scope_and_does_not_escape_spawn_or_future() {
    let f = Fixture::new("viewer").await;
    let c = conversation(&f);
    assert!(agent_access::tool_host(&f.state, &c, None, "agent").is_none());
    let grant = authorization(&f, &c);
    let host = agent_access::scope(Some(grant), async {
        let host = agent_access::tool_host(&f.state, &c, None, "agent").unwrap();
        assert!(host.call("knowledge_search", SEARCH).await.is_ok());
        let escaped = host.clone();
        assert!(
            tokio::spawn(async move { escaped.call("knowledge_search", SEARCH).await })
                .await
                .unwrap()
                .is_err()
        );
        host
    })
    .await;
    assert!(host.call("knowledge_search", SEARCH).await.is_err());
}

#[tokio::test]
async fn agent_access_hydrates_only_returned_current_source_and_rejects_invented_scope() {
    let f = Fixture::new("viewer").await;
    let c = conversation(&f);
    agent_access::scope(Some(authorization(&f,&c)),async {
        let host = agent_access::tool_host(&f.state,&c,None,"agent").unwrap();
        assert!(host.call("knowledge_source",r#"{"reference":"knowledge-test-memory","rationale":"Invented"}"#).await.is_err());
        let hits:Value=serde_json::from_str(&host.call("knowledge_search",SEARCH).await.unwrap()).unwrap();
        assert_eq!(hits["hits"][0]["source"]["memory_id"],f.source.memory_id);
        let input=json!({"reference":hits["hits"][0]["reference"],"rationale":"Inspect exact source"}).to_string();
        let source:Value=serde_json::from_str(&host.call("knowledge_source",&input).await.unwrap()).unwrap();
        assert_eq!(source["content"],"generation-owned content");
        let other=agent_access::tool_host(&f.state,&c,None,"child").unwrap();
        assert!(other.call("knowledge_source",&input).await.is_err());
        let forged=json!({"mode":"literal","query":"generation-owned","limit":10,"rationale":"query","project_id":"other"}).to_string();
        assert!(host.call("knowledge_search",&forged).await.is_err());
        f.operation.authority.repository().unwrap().delete(&f.operation.scope,&f.source.memory_id,1).await.unwrap();
        assert!(host.call("knowledge_source",&input).await.is_err());
    }).await;
}

#[tokio::test]
async fn agent_access_live_session_context_generation_and_capabilities_revoke_existing_host() {
    for sql in [
        "UPDATE desktop_user_sessions SET status='revoked'",
        "UPDATE desktop_workspace_contexts SET revision=revision+1",
        "UPDATE desktop_tenant_memberships SET status='suspended'",
        "UPDATE desktop_user_sessions SET expires_at_ms=1",
    ] {
        let f = Fixture::new("viewer").await;
        let c = conversation(&f);
        agent_access::scope(Some(authorization(&f, &c)), async {
            let host = agent_access::tool_host(&f.state, &c, None, "agent").unwrap();
            f.state
                .session_store
                .connection()
                .unwrap()
                .execute(sql, [])
                .unwrap();
            assert!(
                host.call("knowledge_search", SEARCH).await.is_err(),
                "{sql}"
            );
        })
        .await;
    }
    let f = Fixture::new("viewer").await;
    let c = conversation(&f);
    agent_access::scope(Some(authorization(&f, &c)), async {
        let host = agent_access::tool_host(&f.state, &c, None, "agent").unwrap();
        publish(&f.state, &f.directory, 2, true).await;
        assert!(host.call("knowledge_search", SEARCH).await.is_err());
    })
    .await;
}

struct ScriptedKnowledgeLlm;
#[async_trait]
impl agistack_core::ports::LlmPort for ScriptedKnowledgeLlm {
    async fn extract_memory(
        &self,
        _: &agistack_core::model::Episode,
    ) -> agistack_core::ports::CoreResult<agistack_core::ports::MemoryDraft> {
        Err(agistack_core::ports::CoreError::Llm(
            "unused fixture".into(),
        ))
    }
    async fn decide(
        &self,
        _: &str,
        round: u64,
        transcript: &[agistack_core::agent::types::TranscriptEntry],
        tools: &[String],
    ) -> agistack_core::ports::CoreResult<agistack_core::agent::types::AgentAction> {
        use agistack_core::agent::types::AgentAction;
        assert!(
            tools.iter().any(|t| t == "knowledge_search"),
            "HTTP run must forward trusted authority"
        );
        if round == 0 {
            return Ok(AgentAction::CallTool {
                tool: "knowledge_search".into(),
                input_json: SEARCH.into(),
            });
        }
        let result = transcript
            .iter()
            .rev()
            .find_map(|entry| serde_json::from_str::<Value>(&entry.content).ok());
        if let Some(hits) = result.as_ref().and_then(|v| v.get("hits")) {
            return Ok(AgentAction::CallTool {
                tool: "knowledge_source".into(),
                input_json: json!({"reference":hits[0]["reference"],"rationale":"Verify citation"})
                    .to_string(),
            });
        }
        assert_eq!(result.unwrap()["content"], "generation-owned content");
        Ok(AgentAction::Finish {
            answer: "KNOWLEDGE_HTTP_PRODUCER_OK".into(),
        })
    }
}

#[tokio::test]
async fn agent_access_explicit_http_producer_carries_session_into_real_engine_and_tool_calls() {
    use axum::{
        body::{to_bytes, Body},
        http::Request,
    };
    use tower::ServiceExt;
    for build in [false, true] {
        let f = Fixture::new("member").await;
        let c = conversation(&f);
        *f.state.test_llm_override.lock().unwrap() = Some(Arc::new(ScriptedKnowledgeLlm));
        let (path, request_body) = if build {
            f.state.session_store.replace_agent_plan_tasks(&c.id,&[json!({"id":"knowledge-plan-task","conversation_id":c.id,"content":"Inspect knowledge","status":"pending","priority":"high","order_index":0})]).unwrap();
            let plan = f
                .state
                .session_store
                .latest_draft_plan(&c.id)
                .unwrap()
                .unwrap();
            (
                "/api/v1/agent/plans/approve-and-start".to_owned(),
                json!({"conversation_id":c.id,"project_id":c.project_id,
            "plan_version_id":plan.id,"expected_plan_version":plan.version,"permission_profile":"read_only",
            "message":"Inspect project knowledge","message_id":"http-knowledge-message","idempotency_key":"knowledge-approval"}),
            )
        } else {
            (
                format!("/api/v1/agent/conversations/{}/messages", c.id),
                json!({"message":"Inspect project knowledge","message_id":"http-knowledge-message"}),
            )
        };
        let response = crate::local_runtime::local_router_with_generation_required(f.state.clone())
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(path)
                    .header("content-type", "application/json")
                    .header("x-agistack-launch", TOKEN)
                    .header("authorization", format!("Bearer {TOKEN}"))
                    .body(Body::from(request_body.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        let status = response.status();
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(
            status,
            axum::http::StatusCode::OK,
            "{}",
            String::from_utf8_lossy(&body)
        );
        tokio::time::timeout(std::time::Duration::from_secs(10), async {
            loop {
                let timeline = f.state.session_store.timeline(&c.id, 100).unwrap();
                if timeline
                    .iter()
                    .any(|e| e.to_string().contains("KNOWLEDGE_HTTP_PRODUCER_OK"))
                {
                    assert_eq!(
                        timeline
                            .iter()
                            .filter(|e| e["type"] == "knowledge_tool_audit")
                            .count(),
                        2
                    );
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("HTTP spawned engine must complete knowledge search and source");
    }
}

#[tokio::test]
async fn agent_access_capability_denial_and_closed_release_never_expose_or_read_knowledge() {
    let f = Fixture::new("viewer").await;
    let c = conversation(&f);
    agent_access::scope(Some(authorization(&f, &c)), async {
        let host = agent_access::tool_host(&f.state, &c, None, "agent").unwrap();
        f.operation
            .authority
            .inner
            .lock()
            .unwrap()
            .validation_actions = Some(Default::default());
        assert!(agent_access::tool_host(&f.state, &c, None, "agent").is_none());
        assert!(host.call("knowledge_search", SEARCH).await.is_err());
    })
    .await;
    publish(&f.state, &f.directory, 2, false).await;
    let lease = Arc::new(
        f.state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let grant =
        RunAuthorization::capture(f.auth.clone(), Some(lease), &c, "closed-message", None).unwrap();
    agent_access::scope(Some(grant), async {
        assert!(agent_access::tool_host(&f.state, &c, None, "agent").is_none());
    })
    .await;
}
