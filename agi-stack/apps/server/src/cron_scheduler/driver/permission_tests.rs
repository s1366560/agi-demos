use std::sync::atomic::{AtomicUsize, Ordering};

use agistack_core::{automation_permission::PermissionInvocationProposal, CoreResult};
use agistack_plugin_host::{Tool, ToolAccessClass, Trust};
use serde_json::json;

use super::*;
use crate::cron_tool_authority::PgAutomationPermissionProducerFactory;

struct InheritedPermissionPort;

#[async_trait]
impl agistack_core::automation_permission::PermissionSuspensionPort for InheritedPermissionPort {
    async fn suspend(&self, _: &SessionState) -> CoreResult<()> {
        panic!("restricted driver must clear inherited permission authority")
    }
}

struct ProposedTool {
    access: ToolAccessClass,
    applicable: bool,
    calls: Arc<AtomicUsize>,
}
#[async_trait]
impl Tool for ProposedTool {
    fn name(&self) -> &str {
        "write"
    }
    fn version(&self) -> &str {
        "host-version-7"
    }
    fn trust(&self) -> Trust {
        Trust::Builtin
    }
    fn access_class(&self) -> ToolAccessClass {
        self.access
    }
    fn should_run(&self, context: &str) -> bool {
        let value: Value = serde_json::from_str(context).unwrap();
        assert_eq!(value["actor_user_id"], "actor");
        assert_eq!(value["project_id"], "project");
        self.applicable
    }
    async fn invoke(&self, _: &str) -> CoreResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        panic!("producer must not dispatch")
    }
}

async fn permission_schema(pool: &PgPool) {
    sqlx::raw_sql(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../crates/adapters-postgres/tests/automation_permission/schema.sql"
    )))
    .execute(pool)
    .await
    .unwrap();
    for sql in [
        "CREATE TABLE users (id text PRIMARY KEY,is_active boolean)",
        "CREATE TABLE projects (id text PRIMARY KEY,tenant_id text,owner_id text)",
        "CREATE TABLE user_tenants (user_id text,tenant_id text)",
        "CREATE TABLE user_projects (user_id text,project_id text,role text)",
        "CREATE TABLE api_keys (id text PRIMARY KEY,user_id text,is_active boolean,expires_at timestamptz)",
        "INSERT INTO users VALUES ('actor',true)","INSERT INTO projects VALUES ('project','tenant','actor')",
        "INSERT INTO user_tenants VALUES ('actor','tenant')","INSERT INTO user_projects VALUES ('actor','project','member')",
        "INSERT INTO api_keys VALUES ('host-key','actor',true,NULL)",
        "UPDATE agistack_cron_operations SET actor_api_key_id='host-key'",
    ] {sqlx::query(sql).execute(pool).await.unwrap();}
}

#[tokio::test]
async fn postgres_driver_permission_producer_resolves_host_identity_and_never_dispatches() {
    for case in 0..5 {
        let Some(f) = Fixture::open().await else {
            return;
        };
        f.seed("bound").await;
        permission_schema(&f.pool).await;
        let calls = Arc::new(AtomicUsize::new(0));
        let registry = HotPlugRegistry::new();
        if case != 3 {
            registry.register_tool(Arc::new(ProposedTool {
                access: if case == 1 {
                    ToolAccessClass::Pure
                } else {
                    ToolAccessClass::Mutating
                },
                applicable: case != 2,
                calls: calls.clone(),
            }));
        }
        let mut request:HitlRequest=serde_json::from_value(json!({
            "id":"bound-request","kind":"permission","prompt":"Write file?",
            "decision":{"action":{"name":"write","label":"Write"},"target":{"kind":"file","id":"agent-target","version_id":"agent-version"},
                "data":{"summary":"Proposed file change"},"reason":"Requested task","risk":{"level":"low","rationale":"One file"},
                "reversibility":{"mode":"reversible"},"scope":{"kind":"files","ids":["file"]},
                "evidence":[{"kind":"diff","id":"diff","label":"Proposed diff"}]}
        })).unwrap();
        request.permission_invocation = Some(Box::new(PermissionInvocationProposal {
            tool: "write".into(),
            input: json!({"path":"file","text":"exact"}),
        }));
        let expected_request = request.clone();
        let engine = Arc::new(ReActEngine::new(
            Arc::new(ScriptedLlm::new(vec![AgentAction::RequestHuman {
                request,
            }])),
            Arc::new(registry.clone()),
            Arc::new(InMemoryCheckpointStore::new()),
            Arc::new(SystemClock),
        ));
        let engine = if case == 4 {
            Arc::new(
                engine
                    .as_ref()
                    .clone()
                    .with_permission_suspension(Arc::new(InheritedPermissionPort)),
            )
        } else {
            engine
        };
        if case == 0 {
            sqlx::raw_sql("CREATE FUNCTION slow_permission_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.1); RETURN NEW; END $$; CREATE TRIGGER slow_permission_intent AFTER INSERT ON agistack_automation_permission_intents FOR EACH ROW EXECUTE FUNCTION slow_permission_intent();")
                .execute(&f.pool).await.unwrap();
        }
        let config = CronSchedulerConfig {
            runtime_heartbeat: std::time::Duration::from_millis(1),
            ..CronSchedulerConfig::default()
        };
        let mut driver = PgCronSchedulerDriver::new(
            f.pool.clone(),
            engine.clone(),
            registry.clone(),
            config.clone(),
            Arc::new(PgCronSchedulerOwnerRepository::new(f.pool.clone())),
            Arc::new(UtcCronWorkerClock),
        );
        if case != 4 {
            // The bound producer remains testable through an explicit internal
            // composition; it is never installed by the released driver.
            let executor = ReActAutomationRunExecutor::new(engine)
                .with_run_persistence_factory(Arc::new(PgAutomationRunPersistenceFactory::new(
                    f.pool.clone(),
                )))
                .with_tool_host_factory(Arc::new(RegistryAutomationToolHostFactory::new(
                    registry.clone(),
                )))
                .with_permission_producer_factory(PgAutomationPermissionProducerFactory::new(
                    f.pool.clone(),
                    registry,
                ));
            driver.runtime = Arc::new(CronAutomationRuntimeWorker::new(
                Arc::new(PgCronAutomationRuntimeRepository::new(f.pool.clone())),
                Arc::new(executor),
                config.runtime_worker_config(),
            ));
        }
        tokio::time::timeout(
            std::time::Duration::from_secs(2),
            driver.drive_runtime_scope(&scope()),
        )
        .await
        .expect("renewal must not block the transaction it is waiting for")
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        let count: i64 =
            sqlx::query_scalar("SELECT count(*) FROM agistack_automation_permission_intents")
                .fetch_one(&f.pool)
                .await
                .unwrap();
        if case == 0 {
            assert_eq!(count, 1);
            assert_eq!(run_state(&f.pool, "bound").await.0, "waiting_human");
            let identity:(String,String,String)=sqlx::query_as("SELECT tool_version,actor_user_id,actor_api_key_id FROM agistack_automation_permission_intents").fetch_one(&f.pool).await.unwrap();
            assert_eq!(
                identity,
                ("host-version-7".into(), "actor".into(), "host-key".into())
            );
            let state: Value = sqlx::query_scalar("SELECT state FROM agistack_checkpoints")
                .fetch_one(&f.pool)
                .await
                .unwrap();
            let mut expected = SessionState::new("bound", "ask and finish", Some("project"));
            expected.push_unique(agistack_core::TranscriptEntry::new(
                0,
                agistack_core::Role::Action,
                "request_human[Permission] Write file?",
            ));
            expected.pending_hitl = Some(expected_request);
            expected.status = SessionStatus::AwaitingInput;
            assert_eq!(state, serde_json::to_value(expected).unwrap());
            driver.drive_runtime_scope(&scope()).await.unwrap();
            assert_eq!(run_state(&f.pool, "bound").await.0, "waiting_human");
        } else {
            assert_eq!(count, 0);
            let requests: i64 = sqlx::query_scalar("SELECT count(*) FROM hitl_requests")
                .fetch_one(&f.pool)
                .await
                .unwrap();
            assert_eq!(requests, 0);
            if case == 4 {
                assert_eq!(run_state(&f.pool, "bound").await.0, "failed");
            }
        }
        f.close().await;
    }
}
