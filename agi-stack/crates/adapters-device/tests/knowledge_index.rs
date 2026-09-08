use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::{
    index::*,
    processing::{audit::*, worker::*, *},
    *,
};
use agistack_core::Memory;
use futures::executor::block_on;
use rusqlite::Connection;
use std::num::NonZeroU32;

#[path = "knowledge_index/clock.rs"]
mod clock;
#[path = "knowledge_index/configuration.rs"]
mod configuration;
#[path = "knowledge_index/lifecycle.rs"]
mod lifecycle;
#[path = "knowledge_index/visibility.rs"]
mod visibility;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-index-{}.db", uuid::Uuid::new_v4())))
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
fn build(tenant: &str, project: &str, id: &str) -> IndexBuild {
    IndexBuild {
        scope: KnowledgeScope {
            tenant_id: tenant.into(),
            project_id: project.into(),
        },
        build_id: id.into(),
        profile: IndexProfile {
            provider_id: "configured-provider".into(),
            provider_revision: 0,
            credential_binding_digest: "ab".repeat(32),
            model_id: "explicit-embedding-model".into(),
            dimensions: NonZeroU32::new(2).unwrap(),
            input_contract_version: 1,
            normalization_version: 1,
        },
    }
}
async fn create(repo: &SqliteKnowledgeRepository, scope: &KnowledgeScope, id: &str) -> Memory {
    repo.create(
        scope,
        Memory {
            id: id.into(),
            project_id: scope.project_id.clone(),
            title: "Title\"\\中".into(),
            content: format!("Content {id}"),
            author_id: "actor".into(),
            content_type: "text".into(),
            tags: vec![],
            entities: vec![],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1,
            embedding: None,
        },
    )
    .await
    .unwrap()
}
async fn finish(repo: &SqliteKnowledgeRepository, scope: &KnowledgeScope) -> ProcessingSource {
    let lease = repo
        .claim(scope, "extractor", 100, 100)
        .await
        .unwrap()
        .unwrap();
    apply(repo, scope, &lease, 101).await;
    lease.source
}
async fn apply(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    lease: &ProcessingLease,
    now: i64,
) {
    let memory = repo
        .get(scope, &lease.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    repo.begin_processing_audit_durable(
        scope,
        lease,
        ProcessingInvocation {
            agent_id: "extractor".into(),
            provider_id: "extract-provider".into(),
            model_id: "extract-model".into(),
            tool_name: SUBMIT_PROJECTION_TOOL.into(),
            contract_version: 1,
            input: ProcessingInput {
                source: lease.source.clone(),
                title: memory.title,
                content: memory.content,
            },
        },
        now,
    )
    .unwrap();
    repo.finish_processing_audit_durable(
        scope,
        lease,
        ProcessingAuditOutcome::Applied {
            submission: ProjectionSubmission {
                source: lease.source.clone(),
                entities: vec![],
                relationships: vec![],
                rationale: "No entity projection needed for this document.".into(),
            },
        },
        now,
        0,
    )
    .unwrap();
}
fn claim(repo: &SqliteKnowledgeRepository, b: &IndexBuild, now: i64) -> IndexLease {
    repo.claim_index_durable(&config(repo, b), "embed-worker", 100, &|| Ok(now))
        .unwrap()
        .unwrap()
}

fn select_initial(repo: &SqliteKnowledgeRepository, build: &IndexBuild) {
    if repo
        .desired_index_config_durable(&build.scope, &|| Ok(0))
        .unwrap()
        .is_none()
    {
        repo.select_index_config_durable(build, None, &|| Ok(0))
            .unwrap();
    }
}
fn config(repo: &SqliteKnowledgeRepository, build: &IndexBuild) -> DesiredEmbeddingConfig {
    DesiredEmbeddingConfig {
        revision: repo
            .desired_index_config_durable(&build.scope, &|| Ok(0))
            .unwrap()
            .unwrap()
            .revision,
        build: build.clone(),
    }
}
