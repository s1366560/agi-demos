use agistack_core::knowledge::{
    community::{build::*, result::*, worker::*},
    processing::{audit::*, worker::*, *},
};
use agistack_core::Entity;
use futures::executor::block_on;

use super::*;

include!("../tests/fixtures.rs");

fn setup() -> (
    SqliteKnowledgeRepository,
    KnowledgeScope,
    CommunityBuildReceipt,
) {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let s = scope("tenant", "project");
    block_on(async {
        create(
            &repo,
            &s,
            "source",
            "Alice and team",
            "Alice joined the team.",
        )
        .await;
        finish(&repo, &s, true).await;
    });
    let build = new_build(&repo, &s, "initial");
    (repo, s, build)
}

fn new_build(
    repo: &SqliteKnowledgeRepository,
    s: &KnowledgeScope,
    key: &str,
) -> CommunityBuildReceipt {
    repo.create_community_build_durable(
        s,
        &CommunityBuildRequest {
            actor_id: "actor".into(),
            idempotency_key: key.into(),
            min_community_size: 2,
        },
        &|| Ok(100),
    )
    .unwrap()
}

fn begin(
    repo: &SqliteKnowledgeRepository,
    s: &KnowledgeScope,
    build: &CommunityBuildReceipt,
) -> (CommunityJobLease, CommunityInput) {
    let lease = repo
        .claim_community_job_durable(s, &build.build_id, "worker", 1000, &|| Ok(100))
        .unwrap()
        .unwrap();
    let input = repo
        .community_candidate_input_durable(s, &build.build_id, &lease.candidate_id)
        .unwrap()
        .unwrap();
    repo.begin_community_audit_durable(
        s,
        &lease,
        CommunityInvocation {
            agent_id: "community-agent".into(),
            provider_id: "provider".into(),
            model_id: "model".into(),
            tool_name: SUBMIT_COMMUNITY_TOOL.into(),
            contract_version: 1,
            input: input.clone(),
        },
        &|| Ok(101),
    )
    .unwrap();
    (lease, input)
}

fn submission(input: &CommunityInput, ready: bool) -> CommunitySubmission {
    let member = &input.candidate.members[0];
    let evidence = vec![CommunityEvidence {
        source: member.source.clone(),
        entity_index: member.entity_index,
        relationship_index: None,
    }];
    CommunitySubmission {
        build_id: input.build_id.clone(),
        graph_digest: input.graph_digest.clone(),
        candidate_id: input.candidate.membership_digest.clone(),
        members: input.candidate.members.clone(),
        decision: if ready {
            CommunityDecision::Ready {
                name: "Alice's team".into(),
                summary: "Alice joined this team.".into(),
                rationale: "The source explicitly connects these members.".into(),
                evidence,
            }
        } else {
            CommunityDecision::InsufficientEvidence {
                rationale: "The source does not establish a useful summary.".into(),
                evidence,
            }
        },
    }
}

fn apply(
    repo: &SqliteKnowledgeRepository,
    s: &KnowledgeScope,
    lease: &CommunityJobLease,
    input: &CommunityInput,
    ready: bool,
) -> CommunityAuditRecord {
    repo.finish_community_audit_durable(
        s,
        lease,
        CommunityAuditOutcome::Applied {
            submission: submission(input, ready),
        },
        1,
        &|| Ok(102),
    )
    .unwrap()
}

#[test]
fn ready_result_audit_and_job_complete_atomically_and_replay_is_immutable() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    let first = apply(&repo, &s, &lease, &input, true);
    assert_eq!(apply(&repo, &s, &lease, &input, true), first);
    assert_eq!(
        repo.community_results_durable(&s, &build.build_id)
            .unwrap()
            .len(),
        1
    );
    let status = repo
        .community_build_status_durable(&s, &build.build_id)
        .unwrap()
        .unwrap();
    assert_eq!(status.state, CommunityProgressState::Completed);
    assert_eq!(status.ready_count, 1);
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
    assert_eq!(
        repo.community_job_status_durable(&s, &build.build_id, &lease.candidate_id)
            .unwrap()
            .unwrap()
            .state,
        CommunityJobState::Completed
    );
}

#[test]
fn insufficient_evidence_is_audited_terminal_output_without_a_fake_name() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    apply(&repo, &s, &lease, &input, false);
    let status = repo
        .community_build_status_durable(&s, &build.build_id)
        .unwrap()
        .unwrap();
    assert_eq!(status.insufficient_evidence_count, 1);
    assert_eq!(status.ready_count, 0);
    let selected = repo
        .select_community_build_durable(&s, &build.build_id, 0, &|| Ok(103))
        .unwrap();
    assert!(repo
        .activate_community_build_durable(&s, &build.build_id, selected.revision, &|| Ok(104))
        .unwrap());
    let active = repo.active_community_build_durable(&s).unwrap();
    assert_eq!(
        active.current.unwrap().status.insufficient_evidence_count,
        1
    );
}

#[test]
fn source_change_rejects_result_and_old_active_build_becomes_historical() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    let mut memory = block_on(repo.get(&s, "source")).unwrap().unwrap();
    memory.metadata.insert("new".into(), true.into());
    block_on(repo.update(&s, memory, 1)).unwrap();
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
    assert_eq!(
        repo.community_build_status_durable(&s, &build.build_id)
            .unwrap()
            .unwrap()
            .state,
        CommunityProgressState::Failed
    );
}

#[test]
fn expired_worker_may_finish_own_failure_audit_but_cannot_mutate_reclaimed_job() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    let newer = repo
        .claim_community_job_durable(&s, &build.build_id, "new", 1000, &|| Ok(1100))
        .unwrap()
        .unwrap();
    let record = repo
        .finish_community_audit_durable(
            &s,
            &lease,
            CommunityAuditOutcome::Applied {
                submission: submission(&input, true),
            },
            1000,
            &|| Ok(1101),
        )
        .unwrap();
    assert!(matches!(
        record.outcome,
        Some(CommunityAuditOutcome::Failed {
            code: CommunityAuditFailure::LeaseLost,
            ..
        })
    ));
    let status = repo
        .community_job_status_durable(&s, &build.build_id, &lease.candidate_id)
        .unwrap()
        .unwrap();
    assert_eq!(status.attempt, newer.attempt);
    assert_eq!(status.state, CommunityJobState::Leased);
    assert!(repo
        .community_results_durable(&s, &build.build_id)
        .unwrap()
        .is_empty());
}

#[test]
fn selection_revision_prevents_late_old_build_from_replacing_new_request() {
    let (repo, s, first) = setup();
    let first_selected = repo
        .select_community_build_durable(&s, &first.build_id, 0, &|| Ok(100))
        .unwrap();
    let second = new_build(&repo, &s, "second");
    let second_selected = repo
        .select_community_build_durable(&s, &second.build_id, first_selected.revision, &|| Ok(100))
        .unwrap();
    let (lease, input) = begin(&repo, &s, &first);
    apply(&repo, &s, &lease, &input, true);
    assert!(matches!(
        repo.activate_community_build_durable(
            &s,
            &first.build_id,
            first_selected.revision,
            &|| Ok(103)
        ),
        Err(KnowledgeError::Conflict)
    ));
    assert!(!repo
        .activate_community_build_durable(&s, &second.build_id, second_selected.revision, &|| Ok(
            103
        ))
        .unwrap());
    let (lease, input) = begin(&repo, &s, &second);
    apply(&repo, &s, &lease, &input, true);
    assert!(repo
        .activate_community_build_durable(&s, &second.build_id, second_selected.revision, &|| Ok(
            103
        ))
        .unwrap());
    assert_eq!(
        repo.active_community_build_durable(&s)
            .unwrap()
            .current
            .unwrap()
            .status
            .build_id,
        second.build_id
    );
}

#[test]
fn failed_result_insert_rolls_back_audit_and_job_and_allows_replay() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    repo.conn.lock().unwrap().execute_batch("CREATE TRIGGER fail_result BEFORE INSERT ON knowledge_community_results BEGIN SELECT RAISE(ABORT,'fixture failure'); END").unwrap();
    assert!(repo
        .finish_community_audit_durable(
            &s,
            &lease,
            CommunityAuditOutcome::Applied {
                submission: submission(&input, true)
            },
            1,
            &|| Ok(102)
        )
        .is_err());
    assert!(repo
        .community_audit_durable(&s, &build.build_id, &lease.candidate_id, lease.attempt)
        .unwrap()
        .unwrap()
        .outcome
        .is_none());
    assert_eq!(
        repo.community_job_status_durable(&s, &build.build_id, &lease.candidate_id)
            .unwrap()
            .unwrap()
            .state,
        CommunityJobState::Leased
    );
    repo.conn
        .lock()
        .unwrap()
        .execute_batch("DROP TRIGGER fail_result")
        .unwrap();
    apply(&repo, &s, &lease, &input, true);
}

mod activation;
mod audit_boundaries;

mod migration;
