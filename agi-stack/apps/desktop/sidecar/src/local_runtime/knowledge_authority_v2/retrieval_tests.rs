use super::*;
use agistack_core::knowledge::{
    processing::{audit::*, worker::*, *},
    retrieval::*,
};

#[path = "retrieval_lifecycle_tests.rs"]
mod lifecycle;
#[path = "agent_access_tests.rs"]
mod agent_access_tests;
#[path = "retrieval_rpc_tests.rs"]
mod rpc;

struct Fixture {
    directory: TestDirectory,
    state: Arc<LocalRuntimeState>,
    auth: AuthenticatedContext,
    operation: Arc<KnowledgeOperationV2>,
    source: ProcessingSource,
}
impl Fixture {
    async fn new(role: &str) -> Self {
        let directory = TestDirectory::new();
        let state = test_state(TOKEN);
        publish(&state, &directory, 1, true).await;
        state
            .session_store
            .connection()
            .unwrap()
            .execute("UPDATE desktop_tenant_memberships SET role=?1", [role])
            .unwrap();
        let auth = authenticated(&state);
        let lease = Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        );
        let operation = Arc::new(
            KnowledgeOperationV2::admit(lease.clone(), &auth, &operation_scope(&auth, &lease))
                .unwrap(),
        );
        let MemoryMutation::Create { memory } = mutation(&auth) else {
            panic!("fixture");
        };
        let repo = operation.authority.repository().unwrap();
        repo.create(&operation.scope, memory.clone()).await.unwrap();
        let claim = repo
            .claim(&operation.scope, "worker", 100, 100)
            .await
            .unwrap()
            .unwrap();
        repo.begin_processing_audit_durable(
            &operation.scope,
            &claim,
            ProcessingInvocation {
                agent_id: "extractor".into(),
                provider_id: "provider".into(),
                model_id: "model".into(),
                tool_name: SUBMIT_PROJECTION_TOOL.into(),
                contract_version: 1,
                input: ProcessingInput {
                    source: claim.source.clone(),
                    title: memory.title,
                    content: memory.content,
                },
            },
            100,
        )
        .unwrap();
        repo.finish_processing_audit_durable(
            &operation.scope,
            &claim,
            ProcessingAuditOutcome::Applied {
                submission: ProjectionSubmission {
                    source: claim.source.clone(),
                    entities: vec![ExtractedEntity {
                        name: "Knowledge".into(),
                        kind: "Concept".into(),
                    }],
                    relationships: vec![ProcessingRelationship {
                        source_index: 0,
                        target_index: 0,
                        relation_type: "REFERENCES".into(),
                        fact: "Knowledge references itself".into(),
                        score: 1.0,
                    }],
                    rationale: "Declared concept".into(),
                },
            },
            101,
            1,
        )
        .unwrap();
        Self {
            directory,
            state,
            auth,
            operation,
            source: claim.source,
        }
    }
}
fn request() -> RetrievalRequest {
    RetrievalRequest {
        source: None,
        cursor: None,
        limit: 20,
    }
}

#[tokio::test]
async fn viewer_can_read_current_audited_entities_relationships_and_literal_text() {
    let f = Fixture::new("viewer").await;
    let entities = f.operation.entities(&f.state, &f.auth, &request()).unwrap();
    assert_eq!(entities.items.len(), 1);
    assert_eq!(entities.items[0].reference.source, f.source);
    let relationships = f
        .operation
        .relationships(&f.state, &f.auth, &request())
        .unwrap();
    assert_eq!(
        relationships.items[0].source_entity,
        entities.items[0].reference
    );
    assert_eq!(
        f.operation
            .search_text(&f.state, &f.auth, "generation-owned", &request())
            .unwrap()
            .items
            .len(),
        1
    );
    let mut scoped = request();
    scoped.source = Some(f.source.clone());
    assert_eq!(
        f.operation
            .entities(&f.state, &f.auth, &scoped)
            .unwrap()
            .items
            .len(),
        1
    );
    assert!(matches!(
        f.operation.mutate("denied", mutation(&f.auth)).await,
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    assert!(matches!(
        super::super::processing_context::with_current(&f.operation, &f.state, &f.auth, |_| Ok(())),
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
}

#[tokio::test]
async fn live_read_guard_rejects_revocation_inactive_scope_and_context_changes() {
    for sql in [
        "UPDATE desktop_user_sessions SET status='revoked'",
        "UPDATE desktop_user_sessions SET expires_at_ms=0",
        "UPDATE desktop_users SET status='disabled'",
        "UPDATE desktop_tenants SET status='archived'",
        "UPDATE desktop_projects SET status='archived'",
        "UPDATE desktop_tenant_memberships SET status='suspended'",
        "UPDATE desktop_tenant_memberships SET role='guest'",
        "UPDATE desktop_workspace_contexts SET revision=revision+1",
        "UPDATE desktop_workspace_contexts SET updated_at_ms=updated_at_ms+1",
    ] {
        let f = Fixture::new("viewer").await;
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute_batch(sql)
            .unwrap();
        assert!(f.operation.entities(&f.state, &f.auth, &request()).is_err());
        assert!(f
            .operation
            .relationships(&f.state, &f.auth, &request())
            .is_err());
        assert!(f
            .operation
            .search_text(&f.state, &f.auth, "Knowledge", &request())
            .is_err());
    }
}

#[tokio::test]
async fn admitted_read_identity_cannot_be_replaced_with_fresh_or_forged_context() {
    let f = Fixture::new("viewer").await;
    for field in 0..5 {
        let mut auth = f.auth.clone();
        match field {
            0 => auth.session_id = "other".into(),
            1 => auth.workspace.tenant_id = "other".into(),
            2 => auth.workspace.project_id = "other".into(),
            3 => auth.workspace.revision += 1,
            _ => auth.user.user_id = "other".into(),
        };
        assert!(f.operation.entities(&f.state, &auth, &request()).is_err());
    }
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_workspace_contexts SET revision=revision+1")
        .unwrap();
    let fresh = authenticated(&f.state);
    assert!(matches!(
        f.operation.entities(&f.state, &fresh, &request()),
        Err(KnowledgeAuthorityErrorV2::ScopeMismatch)
    ));
    let mut other = request();
    other.source = Some(ProcessingSource {
        tenant_id: "other".into(),
        ..f.source.clone()
    });
    assert!(f.operation.entities(&f.state, &f.auth, &other).is_err());
}
