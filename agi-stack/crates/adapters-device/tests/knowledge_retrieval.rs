use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::KnowledgeMemory as Memory;
use agistack_core::knowledge::{
    processing::{audit::*, worker::*, *},
    retrieval::*,
    *,
};
use agistack_core::Entity;
use futures::executor::block_on;
use rusqlite::Connection;

#[path = "knowledge_retrieval/pagination.rs"]
mod pagination;
#[path = "knowledge_retrieval/visibility.rs"]
mod visibility;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-retrieval-{}.db", uuid::Uuid::new_v4())))
    }
    fn open(&self) -> SqliteKnowledgeRepository {
        SqliteKnowledgeRepository::open(self.0.to_str().unwrap()).unwrap()
    }
    fn sql(&self) -> Connection {
        Connection::open(&self.0).unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn scope(tenant: &str, project: &str) -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: tenant.into(),
        project_id: project.into(),
    }
}
fn request(limit: usize) -> RetrievalRequest {
    RetrievalRequest {
        source: None,
        cursor: None,
        limit,
    }
}
async fn create(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    id: &str,
    title: &str,
    content: &str,
) -> Memory {
    repo.create(
        scope,
        Memory {
            id: id.into(),
            project_id: scope.project_id.clone(),
            title: title.into(),
            content: content.into(),
            author_id: "actor".into(),
            content_type: "text".into(),
            tags: vec![],
            entities: vec![],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1,
            metadata: Default::default(),
            embedding: None,
        },
    )
    .await
    .unwrap()
}
async fn finish(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    audited: bool,
) -> ProcessingSource {
    let lease = repo
        .claim(scope, "worker", 100, 100)
        .await
        .unwrap()
        .unwrap();
    let memory = repo
        .get(scope, &lease.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    let projection = ProcessingProjection {
        entities: vec![
            Entity {
                name: "Alice".into(),
                kind: "Person".into(),
            },
            Entity {
                name: "Team".into(),
                kind: "Organization".into(),
            },
        ],
        relationships: vec![ProcessingRelationship {
            source_index: 0,
            target_index: 1,
            relation_type: "MEMBER_OF".into(),
            fact: "Alice is a member of Team".into(),
            score: 0.9,
        }],
    };
    if audited {
        repo.begin_processing_audit_durable(
            scope,
            &lease,
            ProcessingInvocation {
                agent_id: "extractor".into(),
                provider_id: "provider".into(),
                model_id: "model".into(),
                tool_name: SUBMIT_PROJECTION_TOOL.into(),
                contract_version: 1,
                input: ProcessingInput {
                    source: lease.source.clone(),
                    title: memory.title,
                    content: memory.content,
                },
            },
            100,
        )
        .unwrap();
        repo.finish_processing_audit_durable(
            scope,
            &lease,
            ProcessingAuditOutcome::Applied {
                submission: ProjectionSubmission {
                    source: lease.source.clone(),
                    entities: projection
                        .entities
                        .iter()
                        .map(|e| ExtractedEntity {
                            name: e.name.clone(),
                            kind: e.kind.clone(),
                        })
                        .collect(),
                    relationships: projection.relationships,
                    rationale: "Explicit source facts.".into(),
                },
            },
            101,
            1,
        )
        .unwrap();
    } else {
        repo.complete(scope, &lease, projection, 101).await.unwrap();
    }
    lease.source
}
