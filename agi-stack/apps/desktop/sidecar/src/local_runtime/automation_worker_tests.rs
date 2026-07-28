#[cfg(test)]
mod tests {
    use std::{
        collections::VecDeque,
        future::pending,
        sync::{Arc, Mutex},
        time::Duration,
    };

    use async_trait::async_trait;
    use chrono::{DateTime, Utc};
    use serde_json::{json, Value};
    use tokio::sync::Notify;

    use crate::local_runtime::{
        automation_dispatcher::{
            enqueue_manual_run, list_runs, AutomationClock, AutomationOperationClaim,
            ManualRunCommand, SystemAutomationClock,
        },
        automation_store,
        automation_worker::{
            AutomationExecutor, AutomationExecutorError, AutomationWorker, AutomationWorkerConfig,
            AutomationWorkerExecution, AutomationWorkerHandle,
        },
        session_store::DesktopSessionStore,
    };

    #[derive(Clone)]
    struct FixedClock(DateTime<Utc>);

    impl FixedClock {
        fn at(value: &str) -> Self {
            Self(
                DateTime::parse_from_rfc3339(value)
                    .expect("fixed worker clock")
                    .with_timezone(&Utc),
            )
        }
    }

    struct PendingExecutor {
        entered: Arc<Notify>,
    }

    #[async_trait]
    impl AutomationExecutor for PendingExecutor {
        async fn execute(
            &self,
            _claim: &AutomationOperationClaim,
        ) -> Result<AutomationWorkerExecution, AutomationExecutorError> {
            self.entered.notify_one();
            pending().await
        }
    }

    impl AutomationClock for FixedClock {
        fn now(&self) -> DateTime<Utc> {
            self.0
        }
    }

    struct ScriptedExecutor {
        outcomes: Mutex<VecDeque<Result<AutomationWorkerExecution, AutomationExecutorError>>>,
        run_ids: Mutex<Vec<String>>,
    }

    impl ScriptedExecutor {
        fn new(
            outcomes: impl IntoIterator<
                Item = Result<AutomationWorkerExecution, AutomationExecutorError>,
            >,
        ) -> Self {
            Self {
                outcomes: Mutex::new(outcomes.into_iter().collect()),
                run_ids: Mutex::new(Vec::new()),
            }
        }
    }

    #[async_trait]
    impl AutomationExecutor for ScriptedExecutor {
        async fn execute(
            &self,
            claim: &AutomationOperationClaim,
        ) -> Result<AutomationWorkerExecution, AutomationExecutorError> {
            self.run_ids
                .lock()
                .expect("executed run ids")
                .push(claim.run_id.clone());
            self.outcomes
                .lock()
                .expect("scripted outcomes")
                .pop_front()
                .expect("scripted executor outcome")
        }
    }

    #[tokio::test]
    async fn bounded_worker_consumes_only_the_configured_batch_and_persists_terminals() {
        let clock = Arc::new(FixedClock::at("2099-09-03T10:00:00Z"));
        let store = DesktopSessionStore::in_memory().expect("session store");
        for index in 0..3 {
            let job_id = format!("job-batch-{index}");
            seed_job(&store, &job_id, 0, clock.now());
            enqueue_manual_run(
                &store,
                ManualRunCommand {
                    user_id: "local-user",
                    project_id: "local-project",
                    job_id: &job_id,
                    expected_revision: 1,
                    idempotency_key: &format!("run-batch-{index}"),
                    request_hash: &format!("hash-batch-{index}"),
                    conversation_id: None,
                },
                clock.as_ref(),
            )
            .expect("enqueue batch run");
        }
        let executor = Arc::new(ScriptedExecutor::new((0..3).map(|index| {
            Ok(AutomationWorkerExecution {
                result_summary: json!({ "batch": index }),
                event_count: 2,
                execution_time_ms: 25,
                conversation_id: format!("conversation-batch-{index}"),
            })
        })));
        let worker = AutomationWorker::new(
            store.clone(),
            executor,
            clock,
            AutomationWorkerConfig {
                worker_id: "bounded-worker".to_string(),
                batch_size: 2,
                lease_duration: Duration::from_secs(30),
                heartbeat_interval: Duration::from_secs(10),
                poll_interval: Duration::from_millis(10),
                retry_backoff: Duration::ZERO,
                shutdown_grace: Duration::from_millis(100),
            },
        )
        .expect("worker");

        let first = worker.drain_once().await.expect("first drain");
        assert_eq!(first.claimed, 2);
        assert_eq!(first.succeeded, 2);
        let second = worker.drain_once().await.expect("second drain");
        assert_eq!(second.claimed, 1);
        assert_eq!(second.succeeded, 1);

        let mut batch_results = Vec::new();
        let terminal_count = (0..3)
            .map(|index| {
                let (runs, total) = list_runs(
                    &store,
                    "local-project",
                    &format!("job-batch-{index}"),
                    10,
                    0,
                )
                .expect("run history");
                assert_eq!(total, 1);
                batch_results.push(
                    runs[0]["result_summary"]["batch"]
                        .as_u64()
                        .expect("batch result"),
                );
                runs[0]["status"] == "success"
            })
            .filter(|terminal| *terminal)
            .count();
        assert_eq!(terminal_count, 3);
        batch_results.sort_unstable();
        assert_eq!(batch_results, vec![0, 1, 2]);
    }

    #[tokio::test]
    async fn retryable_execution_is_requeued_once_then_succeeds_with_the_same_run() {
        let clock = Arc::new(FixedClock::at("2099-10-04T11:00:00Z"));
        let store = DesktopSessionStore::in_memory().expect("session store");
        seed_job(&store, "job-retry", 1, clock.now());
        let receipt = enqueue_manual_run(
            &store,
            ManualRunCommand {
                user_id: "local-user",
                project_id: "local-project",
                job_id: "job-retry",
                expected_revision: 1,
                idempotency_key: "run-retry-1",
                request_hash: "hash-retry-1",
                conversation_id: None,
            },
            clock.as_ref(),
        )
        .expect("enqueue retry run");
        let executor = Arc::new(ScriptedExecutor::new([
            Err(AutomationExecutorError::retryable(
                "local_agent_temporarily_unavailable",
            )),
            Ok(AutomationWorkerExecution {
                result_summary: json!({ "answer": "recovered" }),
                event_count: 1,
                execution_time_ms: 40,
                conversation_id: "conversation-retry".to_string(),
            }),
        ]));
        let worker = AutomationWorker::new(
            store.clone(),
            executor,
            clock,
            AutomationWorkerConfig {
                worker_id: "retry-worker".to_string(),
                batch_size: 1,
                lease_duration: Duration::from_secs(30),
                heartbeat_interval: Duration::from_secs(10),
                poll_interval: Duration::from_millis(10),
                retry_backoff: Duration::ZERO,
                shutdown_grace: Duration::from_millis(100),
            },
        )
        .expect("worker");

        let first = worker.drain_once().await.expect("first attempt");
        assert_eq!(first.requeued, 1);
        let second = worker.drain_once().await.expect("second attempt");
        assert_eq!(second.succeeded, 1);
        let (runs, total) =
            list_runs(&store, "local-project", "job-retry", 10, 0).expect("retry history");
        assert_eq!(total, 1);
        assert_eq!(runs[0]["id"], receipt.run_id);
        assert_eq!(runs[0]["status"], "success");
        assert_eq!(runs[0]["result_summary"]["answer"], "recovered");
    }

    #[tokio::test]
    async fn shutdown_aborts_a_stuck_execution_after_the_bounded_grace() {
        let clock = Arc::new(SystemAutomationClock);
        let now = clock.now();
        let store = DesktopSessionStore::in_memory().expect("session store");
        seed_job(&store, "job-stuck", 0, now);
        enqueue_manual_run(
            &store,
            ManualRunCommand {
                user_id: "local-user",
                project_id: "local-project",
                job_id: "job-stuck",
                expected_revision: 1,
                idempotency_key: "run-stuck-1",
                request_hash: "hash-stuck-1",
                conversation_id: None,
            },
            clock.as_ref(),
        )
        .expect("enqueue stuck run");
        let entered = Arc::new(Notify::new());
        let worker = AutomationWorker::new(
            store,
            Arc::new(PendingExecutor {
                entered: Arc::clone(&entered),
            }),
            clock,
            AutomationWorkerConfig {
                worker_id: "stuck-worker".to_string(),
                batch_size: 1,
                lease_duration: Duration::from_secs(30),
                heartbeat_interval: Duration::from_secs(10),
                poll_interval: Duration::from_millis(1),
                retry_backoff: Duration::ZERO,
                shutdown_grace: Duration::from_millis(10),
            },
        )
        .expect("worker");
        let handle = AutomationWorkerHandle::spawn(worker);
        tokio::time::timeout(Duration::from_secs(1), entered.notified())
            .await
            .expect("worker entered stuck execution");

        tokio::time::timeout(Duration::from_millis(200), handle.shutdown())
            .await
            .expect("bounded worker shutdown");
        assert!(!handle.is_running());
    }

    fn seed_job(
        store: &DesktopSessionStore,
        job_id: &str,
        max_retries: u64,
        now: DateTime<Utc>,
    ) -> Value {
        let job = json!({
            "id": job_id,
            "project_id": "local-project",
            "tenant_id": "local",
            "name": "Worker automation",
            "description": null,
            "enabled": true,
            "delete_after_run": false,
            "revision": 1,
            "schedule_revision": 1,
            "trigger": { "kind": "schedule", "schedule": {
                "kind": "every", "config": { "interval_seconds": 60 }
            }},
            "schedule": { "kind": "every", "config": { "interval_seconds": 60 } },
            "payload": {
                "kind": "agent_turn",
                "config": { "message": "Execute the worker automation" }
            },
            "delivery": { "kind": "none", "config": {} },
            "conversation_mode": "fresh",
            "workspace_id": "local-workspace",
            "conversation_id": null,
            "timezone": "UTC",
            "stagger_seconds": 0,
            "timeout_seconds": 300,
            "max_retries": max_retries,
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
}
