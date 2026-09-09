use super::*;
use agistack_core::knowledge::{
    index::{IndexBuild, IndexProfile},
    processing::{audit::*, worker::*},
    sync::{KnowledgeSyncLink, KnowledgeSyncRepository},
    KnowledgeMemory as Memory, ScopedMemoryRepository,
};
use std::num::NonZeroU32;

struct Fixture {
    path: std::path::PathBuf,
    repo: std::sync::Arc<SqliteKnowledgeRepository>,
    scope: KnowledgeScope,
}
impl Fixture {
    fn new() -> Self {
        Self::with_memories(&["one", "two"])
    }
    fn with_memories(ids: &[&str]) -> Self {
        let path =
            std::env::temp_dir().join(format!("knowledge-export-{}.db", uuid::Uuid::new_v4()));
        let repo = std::sync::Arc::new(SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap());
        let scope = KnowledgeScope {
            tenant_id: "tenant".into(),
            project_id: "project".into(),
        };
        for id in ids {
            let memory = Memory {
                id: (*id).into(),
                project_id: scope.project_id.clone(),
                title: format!("Title {id}"),
                content: format!("Content {id}"),
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
        }
        Self { path, repo, scope }
    }
    fn apply(&self, now: i64) {
        let lease = self
            .repo
            .claim_processing_durable(&self.scope, "worker", now, 50)
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
                title: format!("Title {}", lease.source.memory_id),
                content: format!("Content {}", lease.source.memory_id),
            },
        };
        self.repo
            .begin_processing_audit_durable(&self.scope, &lease, invocation, now)
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
                now + 10,
                10,
            )
            .unwrap();
    }
    fn build(&self) -> IndexBuild {
        IndexBuild {
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
        }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

#[test]
fn success_timestamps_track_applied_audits_and_exact_build_completions() {
    let f = Fixture::new();
    let read = |build: Option<&str>| {
        f.repo
            .diagnostics_success_timestamps_durable(&f.scope, build, &|| Ok(1_000))
            .unwrap()
    };
    assert_eq!(
        read(Some("build")),
        DiagnosticsSuccessTimestamps {
            processing_ms: None,
            index_ms: None
        }
    );
    f.apply(100);
    assert_eq!(read(None).processing_ms, Some(110));
    let build = f.build();
    f.repo.begin_index_build_durable(&build, &|| Ok(200)).unwrap();
    let config = f
        .repo
        .select_index_config_durable(&build, None, &|| Ok(201))
        .unwrap();
    assert_eq!(read(Some("build")).index_ms, None);
    let lease = f
        .repo
        .claim_index_durable(&config, "worker", 100, &|| Ok(202))
        .unwrap()
        .unwrap();
    f.repo
        .complete_index_durable(&lease, &[1.0, 0.5], &|| Ok(203))
        .unwrap();
    let timestamps = read(Some("build"));
    assert_eq!(timestamps.index_ms, Some(203));
    assert_eq!(timestamps.processing_ms, Some(110));
    // A failed audit never counts as a success, and another build reports None.
    let pending = f
        .repo
        .claim_processing_durable(&f.scope, "worker", 300, 50)
        .unwrap()
        .unwrap();
    let invocation = ProcessingInvocation {
        agent_id: "agent".into(),
        provider_id: "provider".into(),
        model_id: "model".into(),
        tool_name: SUBMIT_PROJECTION_TOOL.into(),
        contract_version: 1,
        input: ProcessingInput {
            source: pending.source.clone(),
            title: format!("Title {}", pending.source.memory_id),
            content: format!("Content {}", pending.source.memory_id),
        },
    };
    f.repo
        .begin_processing_audit_durable(&f.scope, &pending, invocation, 300)
        .unwrap();
    f.repo
        .finish_processing_audit_durable(
            &f.scope,
            &pending,
            ProcessingAuditOutcome::Failed {
                code: ProcessingAuditFailure::ProviderUnavailable,
                response_digest: None,
            },
            320,
            20,
        )
        .unwrap();
    let timestamps = read(Some("other-build"));
    assert_eq!(timestamps.processing_ms, Some(110));
    assert_eq!(timestamps.index_ms, None);
}

#[test]
fn sync_diagnostics_report_counts_cursors_and_receipt_positions_without_content() {
    let f = Fixture::new();
    let read = || {
        f.repo
            .sync_diagnostics_durable(&f.scope, &|| Ok(1_000))
            .unwrap()
    };
    let initial = read();
    assert_eq!(
        initial,
        SyncDiagnostics {
            linked: false,
            pending_changes: 2,
            pending_graph_changes: 0,
            pull_conflicts: 0,
            push_conflicts: 0,
            graph_pull_conflicts: 0,
            graph_push_conflicts: 0,
            pull_cursor: 0,
            graph_pull_cursor: 0,
            last_receipt_sequence: None,
        }
    );
    futures::executor::block_on(f.repo.configure_sync_link(
        &f.scope,
        KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: "remote-actor".into(),
        },
    ))
    .unwrap();
    {
        let conn = f.repo.conn.lock().unwrap();
        conn.execute_batch(
            "INSERT INTO knowledge_sync_pull_cursors(tenant_id,project_id,cursor)
                 VALUES('tenant','project',42);
             INSERT INTO knowledge_sync_graph_pull_cursors(tenant_id,project_id,cursor)
                 VALUES('tenant','project',7);
             INSERT INTO knowledge_sync_pull_conflicts(tenant_id,project_id,sequence,memory_id,conflict_json)
                 VALUES('tenant','project',1,'one','{\"local\":1}');
             INSERT INTO knowledge_sync_graph_pull_conflicts(tenant_id,project_id,sequence,object_id,conflict_json)
                 VALUES('tenant','project',1,'object','{\"local\":1}');
             INSERT INTO knowledge_sync_pushes(sequence,request_json,receipt_json,conflict_json)
                 VALUES(1,'{}','{\"ack\":1}',NULL);
             INSERT INTO knowledge_sync_pushes(sequence,request_json,receipt_json,conflict_json)
                 VALUES(2,'{}',NULL,'{\"conflict\":1}');",
        )
        .unwrap();
    }
    let current = read();
    assert!(current.linked);
    assert_eq!(current.pending_changes, 1);
    assert_eq!(current.pull_conflicts, 1);
    assert_eq!(current.push_conflicts, 1);
    assert_eq!(current.graph_pull_conflicts, 1);
    assert_eq!(current.pull_cursor, 42);
    assert_eq!(current.graph_pull_cursor, 7);
    assert_eq!(current.last_receipt_sequence, Some(1));
    // A resolved pull conflict no longer counts.
    {
        let conn = f.repo.conn.lock().unwrap();
        conn.execute_batch(
            "INSERT INTO knowledge_sync_resolutions(resolution_id,tenant_id,project_id,actor_id,idempotency_key,memory_id,request_json,receipt_json,archive_json)
                 VALUES('resolution','tenant','project','actor','key','one','{}','{}','{}');
             INSERT INTO knowledge_sync_resolved_pull_conflicts(tenant_id,project_id,sequence,resolution_id)
                 VALUES('tenant','project',1,'resolution');",
        )
        .unwrap();
    }
    assert_eq!(read().pull_conflicts, 0);
}

#[test]
fn schema_18_upgrade_adds_completion_timestamps_and_preserves_jobs() {
    let f = Fixture::new();
    f.apply(100);
    let build = f.build();
    f.repo.begin_index_build_durable(&build, &|| Ok(200)).unwrap();
    let config = f
        .repo
        .select_index_config_durable(&build, None, &|| Ok(201))
        .unwrap();
    let lease = f
        .repo
        .claim_index_durable(&config, "worker", 100, &|| Ok(202))
        .unwrap()
        .unwrap();
    f.repo
        .complete_index_durable(&lease, &[1.0, 0.5], &|| Ok(203))
        .unwrap();
    let path = f.path.clone();
    let scope = f.scope.clone();
    {
        let conn = rusqlite::Connection::open(&path).unwrap();
        conn.execute_batch(
            "ALTER TABLE knowledge_index_jobs DROP COLUMN completed_at_ms;
             UPDATE knowledge_schema SET version=18;",
        )
        .unwrap();
    }
    let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
    // Completions recorded before the upgrade have no timestamp to report.
    let timestamps = repo
        .diagnostics_success_timestamps_durable(&scope, Some("build"), &|| Ok(1_000))
        .unwrap();
    assert_eq!(timestamps.index_ms, None);
    assert_eq!(timestamps.processing_ms, Some(110));
    // New completions after the upgrade are timestamped again.
    let failed = repo.claim_index_durable(&config, "worker", 100, &|| Ok(300)).unwrap();
    assert!(failed.is_none());
    let version: i64 = rusqlite::Connection::open(&path)
        .unwrap()
        .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
        .unwrap();
    assert_eq!(version, crate::knowledge::KNOWLEDGE_SCHEMA_VERSION);
}
