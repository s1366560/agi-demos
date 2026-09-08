use super::*;

#[test]
fn graph_rejection_keeps_a_bounded_digest_and_replays_original_request() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    block_on(repo.delete(&s, "source", 1)).unwrap();
    let first = apply(&repo, &s, &lease, &input, true);
    let Some(CommunityAuditOutcome::Failed {
        code,
        response_digest,
    }) = &first.outcome
    else {
        panic!("expected rejected submission");
    };
    assert_eq!(*code, CommunityAuditFailure::GraphChanged);
    assert_eq!(response_digest.as_ref().unwrap().len(), 64);
    assert_eq!(apply(&repo, &s, &lease, &input, true), first);
    assert!(matches!(
        repo.finish_community_audit_durable(
            &s,
            &lease,
            CommunityAuditOutcome::Applied {
                submission: submission(&input, false)
            },
            1,
            &|| Ok(103)
        ),
        Err(KnowledgeError::IdempotencyConflict)
    ));
}

#[test]
fn wrong_scope_token_attempt_members_and_digest_do_not_complete_audit() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    for foreign in [scope("foreign", "project"), scope("tenant", "foreign")] {
        assert!(repo
            .finish_community_audit_durable(
                &foreign,
                &lease,
                CommunityAuditOutcome::Applied {
                    submission: submission(&input, true)
                },
                1,
                &|| Ok(102)
            )
            .is_err());
        assert!(repo
            .community_audit_durable(
                &foreign,
                &build.build_id,
                &lease.candidate_id,
                lease.attempt
            )
            .unwrap()
            .is_none());
        assert!(repo
            .community_results_durable(&foreign, &build.build_id)
            .unwrap()
            .is_empty());
        assert!(repo
            .active_community_build_durable(&foreign)
            .unwrap()
            .current
            .is_none());
        assert!(repo
            .select_community_build_durable(&foreign, &build.build_id, 0, &|| Ok(102))
            .is_err());
    }
    for field in 0..4 {
        let mut wrong = lease.clone();
        match field {
            0 => wrong.token = "wrong".into(),
            1 => wrong.worker_id = "wrong".into(),
            2 => wrong.attempt += 1,
            _ => wrong.graph_digest = "a".repeat(64),
        };
        assert!(repo
            .finish_community_audit_durable(
                &s,
                &wrong,
                CommunityAuditOutcome::Applied {
                    submission: submission(&input, true)
                },
                1,
                &|| Ok(102)
            )
            .is_err());
    }
    let mut wrong = submission(&input, true);
    wrong.members.swap(0, 1);
    assert!(repo
        .finish_community_audit_durable(
            &s,
            &lease,
            CommunityAuditOutcome::Applied { submission: wrong },
            1,
            &|| Ok(102)
        )
        .is_err());
    for response_digest in [Some("a".repeat(65)), Some("z".repeat(64))] {
        assert!(repo
            .finish_community_audit_durable(
                &s,
                &lease,
                CommunityAuditOutcome::Failed {
                    code: CommunityAuditFailure::InvalidSubmission,
                    response_digest
                },
                1,
                &|| Ok(102)
            )
            .is_err());
    }
    assert!(repo
        .community_audit_durable(&s, &build.build_id, &lease.candidate_id, lease.attempt)
        .unwrap()
        .unwrap()
        .outcome
        .is_none());
    apply(&repo, &s, &lease, &input, true);
}

#[test]
fn completion_deadline_crossing_rolls_back_before_old_attempt_records_failure() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    let tick = std::cell::Cell::new(1099);
    let clock = || {
        let now = tick.get();
        tick.set(now + 1);
        Ok(now)
    };
    assert!(matches!(
        repo.finish_community_audit_durable(
            &s,
            &lease,
            CommunityAuditOutcome::Applied {
                submission: submission(&input, true)
            },
            998,
            &clock
        ),
        Err(KnowledgeError::Conflict)
    ));
    assert!(repo
        .community_results_durable(&s, &build.build_id)
        .unwrap()
        .is_empty());
    assert!(repo
        .community_audit_durable(&s, &build.build_id, &lease.candidate_id, lease.attempt)
        .unwrap()
        .unwrap()
        .outcome
        .is_none());
    let record = repo
        .finish_community_audit_durable(
            &s,
            &lease,
            CommunityAuditOutcome::Failed {
                code: CommunityAuditFailure::LeaseLost,
                response_digest: None,
            },
            999,
            &|| Ok(1100),
        )
        .unwrap();
    assert!(matches!(
        record.outcome,
        Some(CommunityAuditOutcome::Failed { .. })
    ));
}

#[test]
fn same_revision_late_extraction_prevents_community_completion() {
    let (repo, s, _) = setup();
    block_on(create(
        &repo,
        &s,
        "pending",
        "Bob and group",
        "Bob joined a group.",
    ));
    let build = new_build(&repo, &s, "before-late-extraction");
    let (lease, input) = begin(&repo, &s, &build);
    block_on(finish(&repo, &s, true));
    let record = apply(&repo, &s, &lease, &input, true);
    assert!(matches!(
        record.outcome,
        Some(CommunityAuditOutcome::Failed {
            code: CommunityAuditFailure::GraphChanged,
            ..
        })
    ));
    assert!(repo
        .community_results_durable(&s, &build.build_id)
        .unwrap()
        .is_empty());
}

#[test]
fn terminal_audits_and_results_reject_direct_update_and_delete() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    apply(&repo, &s, &lease, &input, true);
    for sql in [
        "UPDATE knowledge_community_audits SET latency_ms=0",
        "DELETE FROM knowledge_community_audits",
        "UPDATE knowledge_community_results SET finished_at_ms=0",
        "DELETE FROM knowledge_community_results",
    ] {
        assert!(repo.conn.lock().unwrap().execute_batch(sql).is_err());
    }
    assert_eq!(
        repo.community_results_durable(&s, &build.build_id)
            .unwrap()
            .len(),
        1
    );
}
