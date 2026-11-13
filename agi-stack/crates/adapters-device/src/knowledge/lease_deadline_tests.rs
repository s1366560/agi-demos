//! The index lease returns one `Conflict` for three different gates.
//! These clocks separate them without moving the 200ms wall-clock period.

use super::*;
use agistack_core::knowledge::{
    index::{DesiredEmbeddingConfig, IndexBuild, IndexProfile},
    processing::{audit::*, worker::*},
    KnowledgeMemory as Memory, ScopedMemoryRepository,
};
use std::cell::Cell;
use std::num::NonZeroU32;

struct Fixture {
    path: std::path::PathBuf,
    repo: SqliteKnowledgeRepository,
    scope: KnowledgeScope,
}
impl Fixture {
    fn new() -> Self {
        let path =
            std::env::temp_dir().join(format!("knowledge-lease-{}.db", uuid::Uuid::new_v4()));
        let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        let scope = KnowledgeScope {
            tenant_id: "tenant".into(),
            project_id: "project".into(),
        };
        let memory = Memory {
            id: "one".into(),
            project_id: scope.project_id.clone(),
            title: "Title".into(),
            content: "Content".into(),
            author_id: "actor".into(),
            content_type: "text".into(),
            tags: vec![],
            entities: vec![],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1,
            metadata: Default::default(),
            embedding: None,
        };
        futures::executor::block_on(repo.create(&scope, memory)).unwrap();
        Self { path, repo, scope }
    }
    fn config(&self) -> DesiredEmbeddingConfig {
        let build = IndexBuild {
            scope: self.scope.clone(),
            build_id: "build".into(),
            profile: IndexProfile {
                provider_id: "provider".into(),
                provider_revision: 1,
                credential_binding_digest: "ab".repeat(32),
                model_id: "model".into(),
                dimensions: NonZeroU32::new(2).unwrap(),
                input_contract_version: 1,
                normalization_version: 1,
            },
        };
        let lease = self
            .repo
            .claim_processing_durable(&self.scope, "worker", 50, 50)
            .unwrap()
            .unwrap();
        let invocation = ProcessingInvocation {
            agent_id: "agent".into(),
            provider_id: "provider".into(),
            model_id: "model".into(),
            tool_name: SUBMIT_PROJECTION_TOOL.into(),
            contract_version: 1,
            input: ProcessingInput {
                source: lease.source.clone(),
                title: "Title".into(),
                content: "Content".into(),
            },
        };
        self.repo
            .begin_processing_audit_durable(&self.scope, &lease, invocation, 50)
            .unwrap();
        self.repo
            .finish_processing_audit_durable(
                &self.scope,
                &lease,
                ProcessingAuditOutcome::Applied {
                    submission: ProjectionSubmission {
                        source: lease.source.clone(),
                        entities: vec![],
                        relationships: vec![],
                        rationale: "No extractable facts.".into(),
                    },
                },
                60,
                10,
            )
            .unwrap();
        self.repo
            .begin_index_build_durable(&build, &|| Ok(100))
            .unwrap();
        self.repo
            .select_index_config_durable(&build, None, &|| Ok(101))
            .unwrap()
    }
    fn expires_at(&self) -> i64 {
        let connection = rusqlite::Connection::open(self.path.to_str().unwrap()).unwrap();
        connection
            .query_row(
                "SELECT expires_at_ms FROM knowledge_index_jobs",
                [],
                |row| row.get(0),
            )
            .unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

#[test]
fn renew_after_the_stored_deadline_conflicts_before_the_update() {
    let f = Fixture::new();
    let config = f.config();
    let lease = f
        .repo
        .claim_index_durable(&config, "worker", 200, &|| Ok(1_000))
        .unwrap()
        .unwrap();
    assert_eq!(lease.expires_at_ms, 1_200);
    let error = f
        .repo
        .renew_index_durable(&lease, 200, &|| Ok(1_200))
        .unwrap_err();
    assert!(matches!(error, KnowledgeError::Conflict));
    assert_eq!(f.expires_at(), 1_200);
    assert!(f
        .repo
        .claim_index_durable(&config, "other", 200, &|| Ok(1_200))
        .unwrap()
        .is_some());
}

#[test]
fn renew_transaction_that_crosses_the_previous_deadline_does_not_commit() {
    let f = Fixture::new();
    let config = f.config();
    let lease = f
        .repo
        .claim_index_durable(&config, "worker", 200, &|| Ok(1_000))
        .unwrap()
        .unwrap();
    let calls = Cell::new(0);
    let clock = || {
        let call = calls.get();
        calls.set(call + 1);
        Ok(if call == 0 { 1_100 } else { 1_200 })
    };
    let error = f.repo.renew_index_durable(&lease, 200, &clock).unwrap_err();
    assert!(matches!(error, KnowledgeError::Conflict));
    assert_eq!(calls.get(), 2);
    assert_eq!(f.expires_at(), 1_200);
    assert!(f
        .repo
        .claim_index_durable(&config, "other", 200, &|| Ok(1_200))
        .unwrap()
        .is_some());
}

#[test]
fn renewal_inside_the_previous_deadline_survives_the_original_expiry() {
    let f = Fixture::new();
    let config = f.config();
    let lease = f
        .repo
        .claim_index_durable(&config, "worker", 200, &|| Ok(1_000))
        .unwrap()
        .unwrap();
    let calls = Cell::new(0);
    let clock = || {
        let call = calls.get();
        calls.set(call + 1);
        Ok(if call == 0 { 1_100 } else { 1_101 })
    };
    let renewed = f.repo.renew_index_durable(&lease, 200, &clock).unwrap();
    assert_eq!(renewed.expires_at_ms, 1_300);
    assert_eq!(f.expires_at(), 1_300);
    f.repo
        .complete_index_durable(&renewed, &[1.0, 0.5], &|| Ok(1_250))
        .unwrap();
}
