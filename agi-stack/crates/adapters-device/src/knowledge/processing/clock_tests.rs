use super::*;
use agistack_core::knowledge::KnowledgeMemory as Memory;
use agistack_core::knowledge::{
    processing::{audit::*, worker::*},
    ScopedMemoryRepository,
};
use std::{
    cell::Cell,
    sync::{
        atomic::{AtomicI64, AtomicUsize, Ordering},
        mpsc, Arc,
    },
    time::Duration,
};

struct Fixture {
    path: std::path::PathBuf,
    repo: Arc<SqliteKnowledgeRepository>,
    scope: KnowledgeScope,
    lease: ProcessingLease,
}
impl Fixture {
    fn new() -> Self {
        let path =
            std::env::temp_dir().join(format!("knowledge-clock-{}.db", uuid::Uuid::new_v4()));
        let repo = Arc::new(SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap());
        let scope = KnowledgeScope {
            tenant_id: "tenant".into(),
            project_id: "project".into(),
        };
        let memory = Memory {
            id: "memory".into(),
            project_id: scope.project_id.clone(),
            title: "Title".into(),
            content: "Source".into(),
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
        let lease = repo
            .claim_processing_durable(&scope, "worker", 100, 50)
            .unwrap()
            .unwrap();
        Self {
            path,
            repo,
            scope,
            lease,
        }
    }
    fn start(&self) {
        self.repo
            .begin_processing_audit_durable(&self.scope, &self.lease, invocation(&self.lease), 100)
            .unwrap();
    }
    fn no_projection(&self) {
        assert!(
            futures::executor::block_on(self.repo.projection(&self.scope, "memory"))
                .unwrap()
                .is_none()
        );
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}
fn invocation(lease: &ProcessingLease) -> ProcessingInvocation {
    ProcessingInvocation {
        agent_id: "agent".into(),
        provider_id: "provider".into(),
        model_id: "model".into(),
        tool_name: SUBMIT_PROJECTION_TOOL.into(),
        contract_version: 1,
        input: ProcessingInput {
            source: lease.source.clone(),
            title: "Title".into(),
            content: "Source".into(),
        },
    }
}
fn outcome(lease: &ProcessingLease) -> ProcessingAuditOutcome {
    ProcessingAuditOutcome::Applied {
        submission: ProjectionSubmission {
            source: lease.source.clone(),
            entities: vec![],
            relationships: vec![],
            rationale: "No extractable facts.".into(),
        },
    }
}
fn execute(
    repo: &SqliteKnowledgeRepository,
    scope: &KnowledgeScope,
    lease: &ProcessingLease,
    phase: &str,
    clock: &dyn Fn() -> KnowledgeResult<i64>,
) -> KnowledgeResult<()> {
    match phase {
        "claim" => {
            let claimed = repo
                .claim_processing_durable_with_clock(scope, "next", 50, clock)?
                .unwrap();
            assert_eq!(claimed.expires_at_ms, 250);
            assert_eq!(claimed.attempt, 2);
            Ok(())
        }
        "begin" => {
            repo.begin_processing_audit_durable_with_clock(scope, lease, invocation(lease), clock)
        }
        "renew" => repo
            .renew_processing_durable_with_clock(scope, lease, 500, clock)
            .map(|_| ()),
        "finish" => {
            repo.finish_processing_audit_durable_with_clock(scope, lease, outcome(lease), 0, clock)
        }
        _ => unreachable!(),
    }
}

#[test]
fn mutex_and_sqlite_contention_sample_clock_after_wait_without_reviving_expired_lease() {
    for sqlite_lock in [false, true] {
        for phase in ["claim", "begin", "renew", "finish"] {
            let f = Fixture::new();
            if phase == "finish" {
                f.start();
            }
            let external = rusqlite::Connection::open(&f.path).unwrap();
            let mutex = if sqlite_lock {
                external.execute_batch("BEGIN IMMEDIATE").unwrap();
                None
            } else {
                Some(f.repo.conn.lock().unwrap())
            };
            let clock = Arc::new(AtomicI64::new(100));
            let calls = Arc::new(AtomicUsize::new(0));
            let (started, wait) = mpsc::channel();
            let repo = f.repo.clone();
            let scope = f.scope.clone();
            let lease = f.lease.clone();
            let thread_clock = clock.clone();
            let thread_calls = calls.clone();
            let handle = std::thread::spawn(move || {
                started.send(()).unwrap();
                execute(&repo, &scope, &lease, phase, &|| {
                    thread_calls.fetch_add(1, Ordering::SeqCst);
                    Ok(thread_clock.load(Ordering::SeqCst))
                })
            });
            wait.recv_timeout(Duration::from_secs(2)).unwrap();
            std::thread::sleep(Duration::from_millis(80));
            assert_eq!(
                calls.load(Ordering::SeqCst),
                0,
                "clock must not be sampled before lock acquisition"
            );
            clock.store(200, Ordering::SeqCst);
            drop(mutex);
            if sqlite_lock {
                external.execute_batch("COMMIT").unwrap();
            }
            let result = handle.join().unwrap();
            if phase == "claim" {
                result.unwrap();
            } else {
                assert!(matches!(result, Err(KnowledgeError::Conflict)));
            }
            f.no_projection();
            if phase == "finish" {
                assert!(f
                    .repo
                    .processing_audit_durable(&f.scope, &f.lease.source, 1)
                    .unwrap()
                    .unwrap()
                    .outcome
                    .is_none());
            }
        }
    }
}

#[test]
fn expiry_between_transaction_work_and_commit_rolls_back_every_leased_mutation() {
    for phase in ["claim", "begin", "renew", "finish"] {
        let f = Fixture::new();
        if phase == "finish" {
            f.start();
        }
        let initial = if phase == "claim" { 200 } else { 100 };
        let calls = Cell::new(0);
        let result = execute(&f.repo, &f.scope, &f.lease, phase, &|| {
            let call = calls.get();
            calls.set(call + 1);
            Ok(initial + call * 100)
        });
        assert!(matches!(result, Err(KnowledgeError::Conflict)));
        assert_eq!(calls.get(), 2);
        let state =
            futures::executor::block_on(f.repo.processing_status(&f.scope, &f.lease.source))
                .unwrap()
                .unwrap();
        assert_eq!(state.state, ProcessingState::Leased);
        assert_eq!(state.attempt, 1);
        let persisted: (String, i64) = f
            .repo
            .conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT token,expires_at_ms FROM knowledge_processing_jobs",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        assert_eq!(persisted, (f.lease.token.clone(), f.lease.expires_at_ms));
        f.no_projection();
        let audit = f
            .repo
            .processing_audit_durable(&f.scope, &f.lease.source, 1)
            .unwrap();
        if phase == "finish" {
            assert!(audit.unwrap().outcome.is_none());
        } else {
            assert!(audit.is_none());
        }
    }
}
