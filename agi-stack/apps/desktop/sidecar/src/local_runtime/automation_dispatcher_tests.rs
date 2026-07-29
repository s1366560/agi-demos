#[cfg(test)]
mod tests {
    use std::{path::PathBuf, time::Duration};

    use chrono::{DateTime, TimeZone, Utc};
    use serde_json::{json, Value};
    use uuid::Uuid;

    use crate::local_runtime::automation_dispatcher::{
        claim_next_operation, dispatch_due_schedules, enqueue_manual_run, list_runs,
        lookup_manual_run_receipt, recover_startup_state, renew_operation_lease, settle_operation,
        settle_operation_with_result, AutomationClock, AutomationExecutionRecord,
        AutomationLedgerError, AutomationRunStatus, ManualRunCommand,
    };
    use crate::local_runtime::{automation_store, session_store::DesktopSessionStore};

    #[derive(Clone)]
    struct FixedAutomationClock {
        now: DateTime<Utc>,
    }

    impl FixedAutomationClock {
        fn at(value: &str) -> Self {
            Self {
                now: DateTime::parse_from_rfc3339(value)
                    .expect("fixed automation clock")
                    .with_timezone(&Utc),
            }
        }
    }

    impl AutomationClock for FixedAutomationClock {
        fn now(&self) -> DateTime<Utc> {
            self.now
        }
    }

    fn test_root() -> PathBuf {
        std::env::temp_dir().join(format!(
            "agistack-local-automation-dispatcher-{}",
            Uuid::new_v4()
        ))
    }

    fn seed_job(
        store: &DesktopSessionStore,
        job_id: &str,
        revision: u64,
        schedule_revision: u64,
        enabled: bool,
        now: DateTime<Utc>,
    ) -> Value {
        let job = json!({
            "id": job_id,
            "project_id": "local-project",
            "tenant_id": "local",
            "name": "Durable local automation",
            "description": null,
            "enabled": enabled,
            "delete_after_run": false,
            "revision": revision,
            "schedule_revision": schedule_revision,
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
                "config": { "message": "Run the durable automation" }
            },
            "delivery": { "kind": "none", "config": {} },
            "conversation_mode": "fresh",
            "workspace_id": "local-workspace",
            "conversation_id": null,
            "timezone": "UTC",
            "stagger_seconds": 0,
            "timeout_seconds": 300,
            "max_retries": 0,
            "state": {},
            "created_by": "local-user",
            "created_at": now.to_rfc3339(),
            "updated_at": null,
        });
        automation_store::create(
            store,
            "local-user",
            "local-project",
            &format!("seed-{job_id}"),
            &format!("seed-hash-{job_id}"),
            &job,
            &now.to_rfc3339(),
        )
        .expect("seed automation job");
        job
    }

    #[test]
    fn run_now_v2_is_durable_replayable_and_payload_conflicts_fail_closed() {
        let clock = FixedAutomationClock::at("2099-03-01T10:00:00Z");
        let store = DesktopSessionStore::in_memory().expect("session store");
        seed_job(&store, "job-manual", 4, 2, true, clock.now());
        let command = ManualRunCommand {
            user_id: "local-user",
            project_id: "local-project",
            job_id: "job-manual",
            expected_revision: 4,
            idempotency_key: "run-manual-1",
            request_hash: "request-hash-a",
            conversation_id: Some("conversation-manual"),
        };

        let first = enqueue_manual_run(&store, command, &clock).expect("enqueue run");
        let replay = enqueue_manual_run(&store, command, &clock).expect("replay run");
        assert!(!first.duplicate);
        assert!(replay.duplicate);
        assert_eq!(first.receipt_id, replay.receipt_id);
        assert_eq!(first.run_id, replay.run_id);
        assert_eq!(first.status, AutomationRunStatus::Queued);

        let conflict = enqueue_manual_run(
            &store,
            ManualRunCommand {
                request_hash: "request-hash-b",
                ..command
            },
            &clock,
        )
        .expect_err("same key cannot bind another payload");
        assert_eq!(conflict, AutomationLedgerError::IdempotencyConflict);

        let (runs, total) =
            list_runs(&store, "local-project", "job-manual", 50, 0).expect("run history");
        assert_eq!(total, 1);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0]["id"], first.run_id);
        assert_eq!(runs[0]["status"], "queued");
        assert_eq!(runs[0]["conversation_id"], "conversation-manual");
        assert_eq!(
            runs[0]["result_summary"]["reason_code"],
            "local_automation_execution_runtime_unavailable"
        );
    }

    #[test]
    fn sqlite_restart_recovers_expired_claim_and_fences_the_old_worker() {
        let root = test_root();
        std::fs::create_dir_all(&root).expect("create test root");
        let path = root.join("sessions.db");
        let started = FixedAutomationClock::at("2099-04-05T08:00:00Z");
        let first_claim = {
            let store = DesktopSessionStore::open(&path).expect("open session store");
            seed_job(&store, "job-restart", 1, 1, true, started.now());
            enqueue_manual_run(
                &store,
                ManualRunCommand {
                    user_id: "local-user",
                    project_id: "local-project",
                    job_id: "job-restart",
                    expected_revision: 1,
                    idempotency_key: "run-restart-1",
                    request_hash: "restart-hash",
                    conversation_id: None,
                },
                &started,
            )
            .expect("enqueue restart run");
            claim_next_operation(
                &store,
                "worker-before-restart",
                Duration::from_secs(30),
                &started,
            )
            .expect("claim operation")
            .expect("queued operation")
        };

        let recovered_at = FixedAutomationClock::at("2099-04-05T08:01:00Z");
        let store = DesktopSessionStore::open(&path).expect("reopen session store");
        let replay = lookup_manual_run_receipt(
            &store,
            ManualRunCommand {
                user_id: "local-user",
                project_id: "local-project",
                job_id: "job-restart",
                expected_revision: 1,
                idempotency_key: "run-restart-1",
                request_hash: "restart-hash",
                conversation_id: None,
            },
        )
        .expect("lookup recovered receipt")
        .expect("recovered receipt");
        assert_eq!(replay.status, AutomationRunStatus::Queued);
        assert_eq!(
            recover_startup_state(&store, &recovered_at).expect("recovery is idempotent"),
            Default::default()
        );

        let second_claim = claim_next_operation(
            &store,
            "worker-after-restart",
            Duration::from_secs(30),
            &recovered_at,
        )
        .expect("reclaim operation")
        .expect("recovered operation");
        assert_eq!(second_claim.operation_id, first_claim.operation_id);
        assert!(second_claim.fence_token > first_claim.fence_token);

        let stale = settle_operation(
            &store,
            &first_claim,
            AutomationRunStatus::Success,
            None,
            &recovered_at,
        )
        .expect_err("old worker must be fenced");
        assert_eq!(stale, AutomationLedgerError::LeaseLost);

        settle_operation(
            &store,
            &second_claim,
            AutomationRunStatus::Success,
            None,
            &recovered_at,
        )
        .expect("current worker settles operation");
        drop(store);

        let restored = DesktopSessionStore::open(&path).expect("reopen completed ledger");
        let (runs, total) =
            list_runs(&restored, "local-project", "job-restart", 50, 0).expect("history");
        assert_eq!(total, 1);
        assert_eq!(runs[0]["status"], "success");
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn schedule_state_reconciles_enabled_revision_and_disabled_authority() {
        let clock = FixedAutomationClock::at("2099-05-10T09:30:00Z");
        let store = DesktopSessionStore::in_memory().expect("session store");
        seed_job(&store, "job-schedule", 1, 3, true, clock.now());

        let initial = schedule_state(&store, "job-schedule");
        assert_eq!(initial.0, 3);
        assert!(initial.1);
        assert_eq!(initial.2, "degraded");
        assert_eq!(
            initial.3.as_deref(),
            Some("local_automation_schedule_runtime_unavailable")
        );

        automation_store::update(
            &store,
            "local-user",
            "local-project",
            "job-schedule",
            "schedule-update",
            "schedule-update-key",
            "schedule-update-hash",
            1,
            &clock.now().to_rfc3339(),
            |job| {
                job["revision"] = json!(1);
                job["schedule_revision"] = json!(4);
                job["enabled"] = json!(false);
                Ok(())
            },
        )
        .expect("update schedule authority");
        let disabled = schedule_state(&store, "job-schedule");
        assert_eq!(disabled.0, 4);
        assert!(!disabled.1);
        assert_eq!(disabled.2, "not_applicable");
        assert_eq!(
            disabled.3.as_deref(),
            Some("local_automation_schedule_disabled")
        );
    }

    fn schedule_state(
        store: &DesktopSessionStore,
        job_id: &str,
    ) -> (u64, bool, String, Option<String>) {
        store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT schedule_revision, enabled, availability, reason_code
                 FROM desktop_automation_schedule_state WHERE job_id = ?1",
                [job_id],
                |row| {
                    Ok((
                        row.get::<_, u64>(0)?,
                        row.get::<_, bool>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, Option<String>>(3)?,
                    ))
                },
            )
            .expect("schedule state")
    }

    #[test]
    fn fixed_clock_uses_unambiguous_utc_milliseconds() {
        let clock = FixedAutomationClock {
            now: Utc
                .with_ymd_and_hms(2099, 6, 1, 12, 0, 0)
                .single()
                .expect("UTC timestamp"),
        };
        assert_eq!(clock.now().timestamp_millis(), 4_083_998_400_000);
    }

    #[test]
    fn due_schedule_dispatch_is_exactly_once_and_advances_the_cursor() {
        let created = FixedAutomationClock::at("2099-07-01T09:30:00Z");
        let store = DesktopSessionStore::in_memory().expect("session store");
        seed_job(&store, "job-due", 1, 1, true, created.now());

        let projected =
            dispatch_due_schedules(&store, &created, 8).expect("project initial schedule");
        assert_eq!(projected.due, 0);
        assert_eq!(projected.enqueued, 0);
        assert_eq!(
            schedule_cursor(&store, "job-due"),
            (
                "active".to_string(),
                Some("2099-07-01T09:31:00+00:00".to_string()),
                None,
            )
        );

        let due = FixedAutomationClock::at("2099-07-01T09:31:00Z");
        let first = dispatch_due_schedules(&store, &due, 8).expect("dispatch due schedule");
        let replay = dispatch_due_schedules(&store, &due, 8).expect("replay due schedule");
        assert_eq!(first.due, 1);
        assert_eq!(first.enqueued, 1);
        assert_eq!(replay.due, 0);
        assert_eq!(replay.enqueued, 0);

        let (runs, total) =
            list_runs(&store, "local-project", "job-due", 50, 0).expect("scheduled history");
        assert_eq!(total, 1);
        assert_eq!(runs[0]["trigger_type"], "scheduled");
        assert_eq!(runs[0]["status"], "queued");
        assert_eq!(
            schedule_cursor(&store, "job-due"),
            (
                "active".to_string(),
                Some("2099-07-01T09:32:00+00:00".to_string()),
                Some("scheduled:1:2099-07-01T09:31:00+00:00".to_string()),
            )
        );
    }

    #[test]
    fn renewed_lease_survives_recovery_and_terminal_history_keeps_execution_evidence() {
        let started = FixedAutomationClock::at("2099-08-02T08:00:00Z");
        let store = DesktopSessionStore::in_memory().expect("session store");
        seed_job(&store, "job-renew", 1, 1, true, started.now());
        enqueue_manual_run(
            &store,
            ManualRunCommand {
                user_id: "local-user",
                project_id: "local-project",
                job_id: "job-renew",
                expected_revision: 1,
                idempotency_key: "run-renew-1",
                request_hash: "renew-hash",
                conversation_id: None,
            },
            &started,
        )
        .expect("enqueue run");
        let claim = claim_next_operation(&store, "worker-renew", Duration::from_secs(30), &started)
            .expect("claim operation")
            .expect("queued operation");

        let heartbeat = FixedAutomationClock::at("2099-08-02T08:00:20Z");
        assert!(
            renew_operation_lease(&store, &claim, Duration::from_secs(30), &heartbeat,)
                .expect("renew lease")
        );
        let before_expiry = FixedAutomationClock::at("2099-08-02T08:00:35Z");
        assert_eq!(
            recover_startup_state(&store, &before_expiry).expect("recover before expiry"),
            Default::default()
        );

        settle_operation_with_result(
            &store,
            &claim,
            AutomationRunStatus::Success,
            AutomationExecutionRecord {
                error_code: None,
                result_summary: Some(json!({ "answer": "durable result" })),
                event_count: 3,
                execution_time_ms: 1_250,
                conversation_id: Some("local-automation-conversation".to_string()),
            },
            &before_expiry,
        )
        .expect("settle renewed operation");
        let (runs, total) =
            list_runs(&store, "local-project", "job-renew", 50, 0).expect("run history");
        assert_eq!(total, 1);
        assert_eq!(runs[0]["status"], "success");
        assert_eq!(runs[0]["duration_ms"], 1_250);
        assert_eq!(runs[0]["result_summary"]["answer"], "durable result");
        assert_eq!(runs[0]["conversation_id"], "local-automation-conversation");
    }

    fn schedule_cursor(
        store: &DesktopSessionStore,
        job_id: &str,
    ) -> (String, Option<String>, Option<String>) {
        store
            .connection()
            .expect("connection")
            .query_row(
                "SELECT availability, next_fire_at, last_occurrence_key
                 FROM desktop_automation_schedule_state WHERE job_id = ?1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .expect("schedule cursor")
    }
}
