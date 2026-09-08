use std::time::Duration;

use agistack_plugin_host::{Tool, ToolAccessClass, Trust};
use tokio::sync::{Notify, Semaphore};

use super::*;
use crate::cron_scheduler::runner::{CronScheduler, CronScopeControlReport};

struct BlockingPureTool {
    entered: Notify,
    finish: Semaphore,
}

#[async_trait]
impl Tool for BlockingPureTool {
    fn name(&self) -> &str {
        "blocked-pure"
    }
    fn version(&self) -> &str {
        "1"
    }
    fn trust(&self) -> Trust {
        Trust::Builtin
    }
    fn access_class(&self) -> ToolAccessClass {
        ToolAccessClass::Pure
    }
    async fn invoke(&self, _input: &str) -> CoreResult<String> {
        self.entered.notify_one();
        self.finish.acquire().await.unwrap().forget();
        Ok("completed pure work".into())
    }
}

// Control discovery is a bounded fixture; execution uses the released PostgreSQL
// driver, real independent run leases, ReAct checkpoints and HITL persistence.
struct RuntimeDriver(PgCronSchedulerDriver);

#[async_trait]
impl CronSchedulerDriver for RuntimeDriver {
    async fn list_work_scopes(
        &self,
        _authority: &CronSchedulerLease,
        _after: Option<&CronControlScope>,
        _limit: i64,
        _now: DateTime<Utc>,
    ) -> CoreResult<Vec<CronControlScope>> {
        Ok(vec![scope()])
    }

    async fn drive_control_scope(
        &self,
        _authority: &CronSchedulerLease,
        _scope: &CronControlScope,
    ) -> CoreResult<CronScopeControlReport> {
        Ok(CronScopeControlReport::default())
    }

    async fn drive_runtime_scope(&self, scope: &CronControlScope) -> CoreResult<()> {
        self.0.drive_runtime_scope(scope).await
    }
}

async fn prepare_owner(pool: &PgPool) {
    // Fixture search_path contains only its newly created qa schema, never public.
    sqlx::query("CREATE TABLE agistack_cron_scheduler_owners (
        scope_id text PRIMARY KEY, owner_kind text NOT NULL, owner_id text,
        owner_epoch bigint NOT NULL DEFAULT 0, lease_token text, lease_expires_at timestamptz,
        acquired_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now(),
        cutover_phase text NOT NULL, cutover_revision bigint NOT NULL, cutover_evidence json NOT NULL)")
        .execute(pool).await.unwrap();
    sqlx::query("CREATE TABLE agistack_legacy_cron_admissions (scope_id text, status text)")
        .execute(pool)
        .await
        .unwrap();
    let evidence = serde_json::json!({
        "protocol": "cron-cutover-evidence.v1", "manifest": {"deployment_id": "fixture"},
        "verification": {
            "protocol": "cron-deployment-verification.v1", "deployment_id": "fixture",
            "cutover_revision": 1, "receipt_id": "fixture", "verifier_id": "fixture",
            "inventory_sha256": "a".repeat(64), "evidence_sha256": "b".repeat(64)
        }
    });
    sqlx::query(
        "INSERT INTO agistack_cron_scheduler_owners
        (scope_id,owner_kind,cutover_phase,cutover_revision,cutover_evidence)
        VALUES ('global','rust','verified',1,$1)",
    )
    .bind(evidence)
    .execute(pool)
    .await
    .unwrap();
}

#[tokio::test]
async fn postgres_owner_loss_and_cancelled_drain_preserve_real_agent_and_hitl_work() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    prepare_owner(&fixture.pool).await;
    for human in [false, true] {
        let id = if human {
            "durable-human"
        } else {
            "durable-agent"
        };
        fixture.seed(id).await;
        sqlx::query("UPDATE agistack_cron_scheduler_owners SET cutover_phase='verified'")
            .execute(&fixture.pool)
            .await
            .unwrap();
        let tool = Arc::new(BlockingPureTool {
            entered: Notify::new(),
            finish: Semaphore::new(0),
        });
        let registry = HotPlugRegistry::new();
        registry.register_tool(tool.clone());
        let mut actions = vec![AgentAction::CallTool {
            tool: "blocked-pure".into(),
            input_json: "{}".into(),
        }];
        if human {
            actions.push(AgentAction::RequestHuman {
                request: HitlRequest::new(id, HitlKind::Decision, "Choose a value"),
            });
        }
        actions.push(AgentAction::Finish {
            answer: "durable completion".into(),
        });
        let config = CronSchedulerConfig {
            owner_id: id.into(),
            owner_lease_seconds: 1,
            autostart: true,
            production_ready: true,
            max_scope_pages: 1,
            poll_interval: Duration::from_millis(10),
            runtime_lease_seconds: 2,
            runtime_heartbeat: Duration::from_millis(20),
            ..CronSchedulerConfig::default()
        };
        let engine = Arc::new(ReActEngine::new(
            Arc::new(ScriptedLlm::new(actions)),
            Arc::new(registry.clone()),
            Arc::new(InMemoryCheckpointStore::new()),
            Arc::new(SystemClock),
        ));
        let ownership = Arc::new(PgCronSchedulerOwnerRepository::new(fixture.pool.clone()));
        let runtime_driver = PgCronSchedulerDriver::new(
            fixture.pool.clone(),
            engine,
            registry,
            config.clone(),
            ownership.clone(),
            Arc::new(UtcCronWorkerClock),
        );
        let scheduler = Arc::new(CronScheduler::new(
            ownership,
            Arc::new(RuntimeDriver(runtime_driver)),
            Arc::new(UtcCronWorkerClock),
            config,
        ));
        let runtime = scheduler.spawn_if_enabled().unwrap();
        tokio::time::timeout(Duration::from_secs(3), tool.entered.notified())
            .await
            .unwrap();
        let original: (String, DateTime<Utc>) = sqlx::query_as(
            "SELECT runtime_lease_token,last_heartbeat_at FROM cron_job_runs WHERE id=$1",
        )
        .bind(id)
        .fetch_one(&fixture.pool)
        .await
        .unwrap();
        sqlx::query("UPDATE agistack_cron_scheduler_owners SET cutover_phase='blocked'")
            .execute(&fixture.pool)
            .await
            .unwrap();
        tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                let released: bool = sqlx::query_scalar(
                    "SELECT lease_token IS NULL FROM agistack_cron_scheduler_owners WHERE scope_id='global'")
                    .fetch_one(&fixture.pool).await.unwrap();
                if released { break; }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        }).await.unwrap();
        let held: (String, String, DateTime<Utc>, Option<DateTime<Utc>>) = sqlx::query_as(
            "SELECT status,runtime_lease_token,last_heartbeat_at,finished_at FROM cron_job_runs WHERE id=$1")
            .bind(id).fetch_one(&fixture.pool).await.unwrap();
        assert_eq!(held.0, "running");
        assert_eq!(held.1, original.0);
        assert!(
            held.2 > original.1,
            "run heartbeat remains independent after owner loss"
        );
        assert!(held.3.is_none());
        assert!(
            tokio::time::timeout(Duration::from_millis(20), runtime.shutdown())
                .await
                .is_err()
        );
        tool.finish.add_permits(1);
        tokio::time::timeout(Duration::from_secs(3), runtime.shutdown())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            run_state(&fixture.pool, id).await.0,
            if human { "waiting_human" } else { "success" }
        );
        if human {
            let durable: (String, Option<DateTime<Utc>>, String) = sqlx::query_as(
                "SELECT run.status,run.finished_at,request.status FROM cron_job_runs run
                 JOIN hitl_requests request ON request.id=run.id WHERE run.id=$1",
            )
            .bind(id)
            .fetch_one(&fixture.pool)
            .await
            .unwrap();
            assert_eq!(durable, ("waiting_human".into(), None, "pending".into()));
            answer(&fixture.pool, id).await;
            let restarted = driver(fixture.pool.clone(), HitlKind::Decision, id);
            restarted.drive_runtime_scope(&scope()).await.unwrap();
            assert_eq!(run_state(&fixture.pool, id).await.0, "success");
        }
        let blocked: bool = sqlx::query_scalar(
            "SELECT cutover_phase='blocked' AND owner_kind='rust'
            FROM agistack_cron_scheduler_owners WHERE scope_id='global'",
        )
        .fetch_one(&fixture.pool)
        .await
        .unwrap();
        assert!(
            blocked,
            "runtime settlement cannot delegate backward or manufacture cutover proof"
        );
    }
    fixture.close().await;
}
