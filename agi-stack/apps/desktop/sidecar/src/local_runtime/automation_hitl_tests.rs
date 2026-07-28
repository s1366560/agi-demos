#[cfg(test)]
mod tests {
    use std::{path::PathBuf, sync::Arc, time::Duration};

    use agistack_adapters_device::SqliteCheckpointStore;
    use agistack_adapters_local_tools::LocalToolHost;
    use agistack_core::{
        agent::types::{HitlKind, HitlRequest, SessionState, SessionStatus},
        ports::CheckpointStore,
    };
    use async_trait::async_trait;
    use chrono::{DateTime, Utc};
    use serde_json::{json, Value};
    use uuid::Uuid;

    use crate::local_runtime::{
        authority_store::{DesktopHitlRequest, DesktopHitlStatus},
        automation_dispatcher::{
            claim_next_operation, enqueue_manual_run, list_runs, settle_operation_with_result,
            AutomationClock, AutomationExecutionRecord, AutomationLedgerError, AutomationRunStatus,
            ManualRunCommand,
        },
        automation_hitl::{
            authority_for_request, claim_answered_for_recovery, commit_answered_wait,
            reconcile_waiting_human, reserve_authority, respond_to_request, resume_answered_wait,
            AutomationHitlAuthority, AutomationHitlResponse, AutomationHitlResponseError,
            AutomationHitlResumeOutcome,
        },
        automation_store,
        automation_worker::{
            AutomationExecutor, AutomationExecutorError, AutomationExecutorOutcome,
            AutomationWorker, AutomationWorkerConfig, AutomationWorkerExecution,
        },
        session_store::DesktopSessionStore,
        ConversationCapabilityMode, ConversationRunMode, LocalConversation, LocalRuntimeState,
    };

    const PROJECT_ID: &str = "local-project";
    const JOB_ID: &str = "job-hitl";
    const CONVERSATION_ID: &str = "conversation-hitl";
    const REQUEST_ID: &str = "automation-hitl-request";

    #[derive(Clone)]
    struct FixedClock(DateTime<Utc>);

    impl FixedClock {
        fn at(value: &str) -> Self {
            Self(
                DateTime::parse_from_rfc3339(value)
                    .expect("fixed automation HITL clock")
                    .with_timezone(&Utc),
            )
        }
    }

    impl AutomationClock for FixedClock {
        fn now(&self) -> DateTime<Utc> {
            self.0
        }
    }

    struct CompletingExecutor;

    #[async_trait]
    impl AutomationExecutor for CompletingExecutor {
        async fn execute(
            &self,
            claim: &crate::local_runtime::automation_dispatcher::AutomationOperationClaim,
        ) -> Result<AutomationExecutorOutcome, AutomationExecutorError> {
            Ok(AutomationExecutorOutcome::Completed(
                AutomationWorkerExecution {
                    result_summary: json!({ "resumed_run_id": claim.run_id }),
                    event_count: 1,
                    execution_time_ms: 5,
                    conversation_id: CONVERSATION_ID.to_string(),
                },
            ))
        }

        async fn recover_answered_hitl(
            &self,
            _authority: &AutomationHitlAuthority,
        ) -> Result<(), AutomationExecutorError> {
            Ok(())
        }
    }

    #[test]
    fn answered_wait_requeues_the_exact_operation_only_once() {
        let waiting_at = FixedClock::at("2099-11-01T10:00:00Z");
        let answered_at = FixedClock::at("2099-11-01T10:00:05Z");
        let store = DesktopSessionStore::in_memory().expect("session store");
        let run_id = seed_waiting_run(&store, &waiting_at, 300);

        let authority = authority_for_request(&store, REQUEST_ID)
            .expect("load automation HITL authority")
            .expect("automation HITL authority");
        assert_eq!(authority.run_id, run_id);
        assert_eq!(authority.conversation_id, CONVERSATION_ID);

        assert_eq!(
            commit_answered_wait(
                &store,
                REQUEST_ID,
                "continue",
                &json!({ "decision": "continue" }),
                Some("automation-hitl-answer"),
                answered_at.now(),
            )
            .expect("commit answered wait"),
            AutomationHitlResumeOutcome::Requeued
        );
        assert_eq!(
            commit_answered_wait(
                &store,
                REQUEST_ID,
                "continue",
                &json!({ "decision": "continue" }),
                Some("automation-hitl-answer"),
                answered_at.now(),
            )
            .expect("replay answered wait"),
            AutomationHitlResumeOutcome::AlreadyResumed
        );

        let claim = claim_next_operation(
            &store,
            "hitl-resume-worker",
            Duration::from_secs(30),
            &answered_at,
        )
        .expect("claim resumed operation")
        .expect("resumed operation");
        assert_eq!(claim.run_id, run_id);
        assert!(claim_next_operation(
            &store,
            "hitl-resume-worker",
            Duration::from_secs(30),
            &answered_at,
        )
        .expect("look for duplicate operation")
        .is_none());
    }

    #[test]
    fn restart_reconciles_an_answered_wait_without_creating_a_second_run() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create restart root");
        let path = root.join("sessions.db");
        let waiting_at = FixedClock::at("2099-12-02T08:00:00Z");
        let answered_at = FixedClock::at("2099-12-02T08:00:10Z");
        let run_id = {
            let store = DesktopSessionStore::open(&path).expect("open first store");
            let run_id = seed_waiting_run(&store, &waiting_at, 300);
            mark_answered(&store, answered_at.now());
            run_id
        };

        let reopened = DesktopSessionStore::open(&path).expect("reopen session store");
        let first =
            reconcile_waiting_human(&reopened, &answered_at).expect("reconcile answered wait");
        assert_eq!(first.expired, 0);
        assert_eq!(first.answered.len(), 1);
        assert_eq!(
            resume_answered_wait(&reopened, REQUEST_ID, answered_at.now())
                .expect("resume recovered answer"),
            AutomationHitlResumeOutcome::Requeued
        );
        let replay =
            reconcile_waiting_human(&reopened, &answered_at).expect("replay reconciliation");
        assert_eq!(replay.expired, 0);
        assert!(replay.answered.is_empty());

        let claim = claim_next_operation(
            &reopened,
            "restart-hitl-worker",
            Duration::from_secs(30),
            &answered_at,
        )
        .expect("claim restart operation")
        .expect("restart operation");
        assert_eq!(claim.run_id, run_id);
        let (_, total) =
            list_runs(&reopened, PROJECT_ID, JOB_ID, 10, 0).expect("run history after restart");
        assert_eq!(total, 1);

        std::fs::remove_dir_all(root).expect("remove restart root");
    }

    #[test]
    fn expired_wait_is_terminal_and_cannot_be_requeued() {
        let waiting_at = FixedClock::at("2099-12-03T09:00:00Z");
        let expired_at = FixedClock::at("2099-12-03T09:00:02Z");
        let store = DesktopSessionStore::in_memory().expect("session store");
        let run_id = seed_waiting_run(&store, &waiting_at, 1);

        let summary =
            reconcile_waiting_human(&store, &expired_at).expect("expire waiting automation");
        assert_eq!(summary.expired, 1);
        assert!(summary.answered.is_empty());
        assert_eq!(
            resume_answered_wait(&store, REQUEST_ID, expired_at.now()).expect("expired replay"),
            AutomationHitlResumeOutcome::Expired
        );
        assert!(claim_next_operation(
            &store,
            "expired-hitl-worker",
            Duration::from_secs(30),
            &expired_at,
        )
        .expect("look for expired operation")
        .is_none());

        let (runs, total) =
            list_runs(&store, PROJECT_ID, JOB_ID, 10, 0).expect("expired run history");
        assert_eq!(total, 1);
        assert_eq!(runs[0]["id"], run_id);
        assert_eq!(runs[0]["status"], "timeout");
        assert_eq!(runs[0]["error_message"], "local_automation_hitl_expired");
        assert_eq!(
            runs[0]["result_summary"]["reason_code"],
            "local_automation_hitl_expired"
        );
        let request = store
            .hitl_request(REQUEST_ID)
            .expect("load expired HITL request")
            .expect("expired HITL request");
        assert_eq!(request.status, DesktopHitlStatus::Responded);
        assert_eq!(
            request.response_actor.as_deref(),
            Some("local_automation_expiry")
        );
        assert_eq!(
            request
                .response_data
                .as_ref()
                .and_then(|value| value.get("status"))
                .and_then(Value::as_str),
            Some("expired")
        );
    }

    #[test]
    fn authority_survives_terminal_result_summary_replacement() {
        let waiting_at = FixedClock::at("2099-12-03T09:30:00Z");
        let answered_at = FixedClock::at("2099-12-03T09:30:02Z");
        let store = DesktopSessionStore::in_memory().expect("session store");
        let run_id = seed_waiting_run(&store, &waiting_at, 300);
        commit_answered_wait(
            &store,
            REQUEST_ID,
            "continue",
            &json!({ "decision": "continue" }),
            Some("automation-hitl-terminal-answer"),
            answered_at.now(),
        )
        .expect("answer waiting run");
        let claim = claim_next_operation(
            &store,
            "terminal-hitl-worker",
            Duration::from_secs(30),
            &answered_at,
        )
        .expect("claim answered operation")
        .expect("answered operation");
        settle_operation_with_result(
            &store,
            &claim,
            AutomationRunStatus::Success,
            AutomationExecutionRecord {
                error_code: None,
                result_summary: Some(json!({ "answer": "done" })),
                event_count: 1,
                execution_time_ms: 5,
                conversation_id: Some(CONVERSATION_ID.to_string()),
            },
            &answered_at,
        )
        .expect("settle terminal run");

        let authority = authority_for_request(&store, REQUEST_ID)
            .expect("load terminal authority")
            .expect("terminal authority");
        assert_eq!(authority.run_id, run_id);
        assert_eq!(authority.runtime_execution_id, claim.runtime_execution_id);
    }

    #[test]
    fn authority_reservation_rejects_an_unrelated_hitl_request_collision() {
        let clock = FixedClock::at("2099-12-03T09:45:00Z");
        let store = DesktopSessionStore::in_memory().expect("session store");
        seed_job(&store, 300, clock.now());
        enqueue_manual_run(
            &store,
            ManualRunCommand {
                user_id: "local-user",
                project_id: PROJECT_ID,
                job_id: JOB_ID,
                expected_revision: 1,
                idempotency_key: "automation-hitl-collision-run",
                request_hash: "automation-hitl-collision-hash",
                conversation_id: Some(CONVERSATION_ID),
            },
            &clock,
        )
        .expect("enqueue collision run");
        let claim =
            claim_next_operation(&store, "collision-worker", Duration::from_secs(30), &clock)
                .expect("claim collision operation")
                .expect("collision operation");
        store
            .insert_hitl_request(&DesktopHitlRequest {
                id: REQUEST_ID.to_string(),
                conversation_id: "unrelated-conversation".to_string(),
                run_id: None,
                round: 1,
                kind: HitlKind::Decision,
                prompt: "Unrelated request".to_string(),
                decision: None,
                status: DesktopHitlStatus::Pending,
                authority_revision: 1,
                created_at: clock.now().to_rfc3339(),
                responded_at: None,
                response_data: None,
                response_actor: None,
                response_revision: None,
                idempotency_key: None,
            })
            .expect("insert unrelated request");

        assert_eq!(
            reserve_authority(
                &store,
                &claim,
                CONVERSATION_ID,
                REQUEST_ID,
                &clock.now().to_rfc3339(),
            ),
            Err(AutomationLedgerError::IdempotencyConflict)
        );
    }

    #[tokio::test]
    async fn worker_poll_reconciles_answered_waits_before_claiming() {
        let waiting_at = FixedClock::at("2099-12-03T10:00:00Z");
        let answered_at = Arc::new(FixedClock::at("2099-12-03T10:00:02Z"));
        let store = DesktopSessionStore::in_memory().expect("session store");
        let run_id = seed_waiting_run(&store, &waiting_at, 300);
        mark_answered(&store, answered_at.now());
        let worker = AutomationWorker::new(
            store.clone(),
            Arc::new(CompletingExecutor),
            answered_at,
            worker_config("poll-reconcile-worker"),
        )
        .expect("automation worker");

        let report = worker.drain_once().await.expect("reconcile worker poll");
        assert_eq!(report.hitl_requeued, 1);
        assert_eq!(report.hitl_expired, 0);
        assert_eq!(report.claimed, 1);
        assert_eq!(report.succeeded, 1);
        let (runs, total) =
            list_runs(&store, PROJECT_ID, JOB_ID, 10, 0).expect("reconciled run history");
        assert_eq!(total, 1);
        assert_eq!(runs[0]["id"], run_id);
        assert_eq!(runs[0]["status"], "success");
    }

    #[tokio::test]
    async fn worker_poll_expires_unanswered_waits_without_invoking_the_executor() {
        let waiting_at = FixedClock::at("2099-12-03T11:00:00Z");
        let expired_at = Arc::new(FixedClock::at("2099-12-03T11:00:02Z"));
        let store = DesktopSessionStore::in_memory().expect("session store");
        seed_waiting_run(&store, &waiting_at, 1);
        let worker = AutomationWorker::new(
            store.clone(),
            Arc::new(CompletingExecutor),
            expired_at,
            worker_config("poll-expiry-worker"),
        )
        .expect("automation worker");

        let report = worker.drain_once().await.expect("expire worker poll");
        assert_eq!(report.hitl_requeued, 0);
        assert_eq!(report.hitl_expired, 1);
        assert_eq!(report.claimed, 0);
        let (runs, _) = list_runs(&store, PROJECT_ID, JOB_ID, 10, 0).expect("expired run history");
        assert_eq!(runs[0]["status"], "timeout");
    }

    #[tokio::test]
    async fn response_uses_the_exact_runtime_checkpoint_and_replay_is_idempotent() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create checkpoint root");
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let checkpoint_store: Arc<dyn CheckpointStore> = checkpoints.clone();
        let store = DesktopSessionStore::in_memory().expect("session store");
        let state = LocalRuntimeState::new(
            root.clone(),
            tool_host,
            checkpoint_store,
            "automation-hitl-token".to_string(),
            store.clone(),
        )
        .expect("local runtime state");
        store
            .insert_conversation(&LocalConversation {
                id: CONVERSATION_ID.to_string(),
                project_id: PROJECT_ID.to_string(),
                tenant_id: "local".to_string(),
                title: "Automation HITL".to_string(),
                workspace_id: Some("local-workspace".to_string()),
                capability_mode: ConversationCapabilityMode::Work,
                current_mode: ConversationRunMode::Plan,
                created_at: "2099-12-04T10:00:00Z".to_string(),
                updated_at: "2099-12-04T10:00:00Z".to_string(),
            })
            .expect("insert automation conversation");
        let waiting_at = FixedClock::at("2099-12-04T10:00:00Z");
        let answered_at = FixedClock::at("2099-12-04T10:00:05Z");
        seed_waiting_run(&store, &waiting_at, 300);
        let authority = authority_for_request(&store, REQUEST_ID)
            .expect("load checkpoint authority")
            .expect("checkpoint authority");
        let mut checkpoint = SessionState::new(
            authority.runtime_execution_id.clone(),
            "Run until a human response is required",
            Some(PROJECT_ID),
        );
        checkpoint.round = 1;
        checkpoint.status = SessionStatus::AwaitingInput;
        checkpoint.pending_hitl = Some(HitlRequest::new(
            REQUEST_ID,
            HitlKind::Decision,
            "Continue the automation?",
        ));
        checkpoints
            .save(&checkpoint)
            .await
            .expect("save waiting checkpoint");

        let response_data = json!({ "decision": "continue" });
        let first = respond_to_request(
            &state,
            REQUEST_ID,
            "continue",
            &response_data,
            Some("automation-hitl-checkpoint-answer"),
            answered_at.now(),
        )
        .await
        .expect("respond to automation HITL");
        assert!(matches!(
            first,
            AutomationHitlResponse::Queued {
                duplicate: false,
                ..
            }
        ));
        let saved = checkpoints
            .load(&authority.runtime_execution_id)
            .await
            .expect("load answered checkpoint")
            .expect("answered checkpoint");
        assert_eq!(saved.status, SessionStatus::Running);
        assert_eq!(saved.hitl_answer(REQUEST_ID), Some("continue"));

        let competing = respond_to_request(
            &state,
            REQUEST_ID,
            "stop",
            &json!({ "decision": "stop" }),
            Some("automation-hitl-competing-answer"),
            answered_at.now(),
        )
        .await;
        assert_eq!(
            competing,
            Err(AutomationHitlResponseError::Ledger(
                AutomationLedgerError::IdempotencyConflict
            ))
        );
        let after_competing = checkpoints
            .load(&authority.runtime_execution_id)
            .await
            .expect("load checkpoint after competing response")
            .expect("checkpoint after competing response");
        assert_eq!(after_competing.hitl_answer(REQUEST_ID), Some("continue"));

        let replay = respond_to_request(
            &state,
            REQUEST_ID,
            "continue",
            &response_data,
            Some("automation-hitl-checkpoint-answer"),
            answered_at.now(),
        )
        .await
        .expect("replay automation HITL response");
        assert!(matches!(
            replay,
            AutomationHitlResponse::Queued {
                duplicate: true,
                ..
            }
        ));
        std::fs::remove_dir_all(root).expect("remove checkpoint root");
    }

    fn seed_waiting_run(
        store: &DesktopSessionStore,
        clock: &FixedClock,
        timeout_seconds: u64,
    ) -> String {
        seed_job(store, timeout_seconds, clock.now());
        let receipt = enqueue_manual_run(
            store,
            ManualRunCommand {
                user_id: "local-user",
                project_id: PROJECT_ID,
                job_id: JOB_ID,
                expected_revision: 1,
                idempotency_key: "automation-hitl-run",
                request_hash: "automation-hitl-run-hash",
                conversation_id: Some(CONVERSATION_ID),
            },
            clock,
        )
        .expect("enqueue HITL run");
        let claim =
            claim_next_operation(store, "waiting-hitl-worker", Duration::from_secs(30), clock)
                .expect("claim HITL operation")
                .expect("HITL operation");
        reserve_authority(
            store,
            &claim,
            CONVERSATION_ID,
            REQUEST_ID,
            &clock.now().to_rfc3339(),
        )
        .expect("reserve automation HITL authority");
        let request = DesktopHitlRequest {
            id: REQUEST_ID.to_string(),
            conversation_id: CONVERSATION_ID.to_string(),
            run_id: None,
            round: 1,
            kind: HitlKind::Decision,
            prompt: "Continue the automation?".to_string(),
            decision: None,
            status: DesktopHitlStatus::Pending,
            authority_revision: 1,
            created_at: clock.now().to_rfc3339(),
            responded_at: None,
            response_data: None,
            response_actor: None,
            response_revision: None,
            idempotency_key: None,
        };
        store
            .insert_hitl_request(&request)
            .expect("insert automation HITL request");
        settle_operation_with_result(
            store,
            &claim,
            AutomationRunStatus::WaitingHuman,
            AutomationExecutionRecord {
                error_code: None,
                result_summary: Some(json!({
                    "authority": "local_scoped_agent",
                    "status": "waiting_human",
                    "hitl_request_id": REQUEST_ID,
                    "runtime_execution_id": claim.runtime_execution_id,
                })),
                event_count: 2,
                execution_time_ms: 10,
                conversation_id: Some(CONVERSATION_ID.to_string()),
            },
            clock,
        )
        .expect("settle waiting operation");
        receipt.run_id
    }

    fn seed_job(store: &DesktopSessionStore, timeout_seconds: u64, now: DateTime<Utc>) {
        let job = json!({
            "id": JOB_ID,
            "project_id": PROJECT_ID,
            "tenant_id": "local",
            "name": "HITL automation",
            "description": null,
            "enabled": true,
            "delete_after_run": false,
            "revision": 1,
            "schedule_revision": 1,
            "trigger": {
                "kind": "schedule",
                "schedule": {
                    "kind": "every",
                    "config": { "interval_seconds": 60 }
                }
            },
            "schedule": {
                "kind": "every",
                "config": { "interval_seconds": 60 }
            },
            "payload": {
                "kind": "agent_turn",
                "config": { "message": "Run until a human response is required" }
            },
            "delivery": { "kind": "none", "config": {} },
            "conversation_mode": "reuse",
            "workspace_id": "local-workspace",
            "conversation_id": CONVERSATION_ID,
            "timezone": "UTC",
            "stagger_seconds": 0,
            "timeout_seconds": timeout_seconds,
            "max_retries": 0,
            "state": {},
            "created_by": "local-user",
            "created_at": now.to_rfc3339(),
            "updated_at": null,
        });
        automation_store::create(
            store,
            "local-user",
            PROJECT_ID,
            "seed-hitl-job",
            "seed-hitl-job-hash",
            &job,
            &now.to_rfc3339(),
        )
        .expect("seed HITL job");
    }

    fn mark_answered(store: &DesktopSessionStore, now: DateTime<Utc>) {
        claim_answered_for_recovery(
            store,
            REQUEST_ID,
            "continue",
            &json!({ "decision": "continue" }),
            Some("automation-hitl-answer"),
            now,
        )
        .expect("mark automation HITL answered");
    }

    fn test_root() -> PathBuf {
        std::env::temp_dir().join(format!("agistack-local-automation-hitl-{}", Uuid::new_v4()))
    }

    fn worker_config(worker_id: &str) -> AutomationWorkerConfig {
        AutomationWorkerConfig {
            worker_id: worker_id.to_string(),
            batch_size: 1,
            lease_duration: Duration::from_secs(30),
            heartbeat_interval: Duration::from_secs(10),
            poll_interval: Duration::from_millis(10),
            retry_backoff: Duration::ZERO,
            shutdown_grace: Duration::from_millis(100),
        }
    }
}
