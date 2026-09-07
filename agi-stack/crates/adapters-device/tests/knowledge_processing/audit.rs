use super::*;
use agistack_core::knowledge::processing::audit::*;
use agistack_core::knowledge::processing::worker::*;

fn invocation(lease: &ProcessingLease) -> ProcessingInvocation {
    ProcessingInvocation {
        agent_id: "knowledge-extractor-v1".into(),
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
fn submission(lease: &ProcessingLease) -> ProjectionSubmission {
    ProjectionSubmission {
        source: lease.source.clone(),
        entities: vec![ExtractedEntity {
            name: "Alice".into(),
            kind: "Person".into(),
        }],
        relationships: vec![],
        rationale: "The source identifies Alice.".into(),
    }
}

#[test]
fn audited_completion_requires_durable_matching_start_and_commits_atomically() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.create(&scope(), memory()).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 100, 100)
            .await
            .unwrap()
            .unwrap();
        let result = ProcessingAuditOutcome::Applied {
            submission: submission(&lease),
        };
        assert!(repo
            .finish_processing_audit_durable(&scope(), &lease, result.clone(), 101, 1)
            .is_err());
        repo.begin_processing_audit_durable(&scope(), &lease, invocation(&lease), 100)
            .unwrap();
        let audit = repo
            .processing_audit_durable(&scope(), &lease.source, lease.attempt)
            .unwrap()
            .unwrap();
        assert!(audit.outcome.is_none());
        assert!(repo
            .complete(&scope(), &lease, projection(), 101)
            .await
            .is_err());
        db.connection().execute_batch("CREATE TRIGGER fail_audit BEFORE UPDATE ON knowledge_processing_audits BEGIN SELECT RAISE(ABORT,'injected'); END;").unwrap();
        assert!(repo
            .finish_processing_audit_durable(&scope(), &lease, result.clone(), 101, 1)
            .is_err());
        assert!(repo.projection(&scope(), "memory").await.unwrap().is_none());
        assert_eq!(
            repo.processing_status(&scope(), &lease.source)
                .await
                .unwrap()
                .unwrap()
                .state,
            ProcessingState::Leased
        );
        db.connection()
            .execute_batch("DROP TRIGGER fail_audit")
            .unwrap();
        repo.finish_processing_audit_durable(&scope(), &lease, result.clone(), 102, 2)
            .unwrap();
        assert!(repo.projection(&scope(), "memory").await.unwrap().is_some());
        let audit = repo
            .processing_audit_durable(&scope(), &lease.source, lease.attempt)
            .unwrap()
            .unwrap();
        assert_eq!(audit.outcome, Some(result));
    });
}

#[test]
fn stale_attempt_can_record_safe_failure_but_never_complete_new_work() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        repo.create(&scope(), memory()).await.unwrap();
        let first = repo
            .claim(&scope(), "worker", 0, 10)
            .await
            .unwrap()
            .unwrap();
        repo.begin_processing_audit_durable(&scope(), &first, invocation(&first), 0)
            .unwrap();
        let next = repo
            .claim(&scope(), "next", 10, 100)
            .await
            .unwrap()
            .unwrap();
        assert!(repo
            .finish_processing_audit_durable(
                &scope(),
                &first,
                ProcessingAuditOutcome::Applied {
                    submission: submission(&first)
                },
                11,
                11
            )
            .is_err());
        repo.finish_processing_audit_durable(
            &scope(),
            &first,
            ProcessingAuditOutcome::Failed {
                code: ProcessingAuditFailure::LeaseLost,
                response_digest: None,
            },
            11,
            11,
        )
        .unwrap();
        assert_eq!(
            repo.processing_status(&scope(), &next.source)
                .await
                .unwrap()
                .unwrap()
                .state,
            ProcessingState::Leased
        );
        repo.complete(&scope(), &next, projection(), 12)
            .await
            .unwrap();
    });
}

#[test]
fn invocation_must_match_source_and_persist_before_any_result_and_reopen() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.create(&scope(), memory()).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 100, 100)
            .await
            .unwrap()
            .unwrap();
        let mut wrong = invocation(&lease);
        wrong.input.content = "forged source".into();
        assert!(repo
            .begin_processing_audit_durable(&scope(), &lease, wrong, 100)
            .is_err());
        assert!(repo
            .processing_audit_durable(&scope(), &lease.source, lease.attempt)
            .unwrap()
            .is_none());
        db.connection().execute_batch("CREATE TRIGGER fail_start BEFORE INSERT ON knowledge_processing_audits BEGIN SELECT RAISE(ABORT,'injected'); END;").unwrap();
        assert!(repo
            .begin_processing_audit_durable(&scope(), &lease, invocation(&lease), 100)
            .is_err());
        assert!(repo
            .processing_audit_durable(&scope(), &lease.source, lease.attempt)
            .unwrap()
            .is_none());
        db.connection()
            .execute_batch("DROP TRIGGER fail_start;")
            .unwrap();
        repo.begin_processing_audit_durable(&scope(), &lease, invocation(&lease), 100)
            .unwrap();
        assert!(repo
            .begin_processing_audit_durable(&scope(), &lease, invocation(&lease), 100)
            .is_err());
        drop(repo);
        let repo = db.open();
        let audit = repo
            .processing_audit_durable(&scope(), &lease.source, lease.attempt)
            .unwrap()
            .unwrap();
        assert!(audit.outcome.is_none());
        let outcome = ProcessingAuditOutcome::Applied {
            submission: submission(&lease),
        };
        repo.finish_processing_audit_durable(&scope(), &lease, outcome.clone(), 101, 1)
            .unwrap();
        drop(repo);
        let repo = db.open();
        assert_eq!(
            repo.processing_audit_durable(&scope(), &lease.source, lease.attempt)
                .unwrap()
                .unwrap()
                .outcome,
            Some(outcome)
        );
        assert!(repo.projection(&scope(), "memory").await.unwrap().is_some());
    });
}

#[test]
fn v8_audit_migration_keeps_existing_lease_and_never_invents_invocations() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.create(&scope(), memory()).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 100, 100)
            .await
            .unwrap()
            .unwrap();
        drop(repo);
        db.connection()
            .execute_batch(
                "DROP TABLE knowledge_processing_audits; UPDATE knowledge_schema SET version=8;",
            )
            .unwrap();
        let repo = db.open();
        assert!(repo
            .processing_audit_durable(&scope(), &lease.source, lease.attempt)
            .unwrap()
            .is_none());
        assert_eq!(
            repo.processing_status(&scope(), &lease.source)
                .await
                .unwrap()
                .unwrap()
                .state,
            ProcessingState::Leased
        );
        repo.begin_processing_audit_durable(&scope(), &lease, invocation(&lease), 101)
            .unwrap();
    });
}
