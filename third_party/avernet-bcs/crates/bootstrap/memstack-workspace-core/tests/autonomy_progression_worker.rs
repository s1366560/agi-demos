use std::error::Error;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::autonomy_progression_worker::{
    WorkspaceAutonomyProgressionWorker, WorkspaceAutonomyProgressionWorkerConfig,
};
use memstack_workspace_core::autonomy_scheduler::{
    WorkspaceAutonomyScheduler, WorkspaceAutonomySchedulerConfig,
};
use memstack_workspace_core::desktop_schema::run_desktop_workspace_schema_migrations;
use memstack_workspace_service::{
    PublicWorkspaceAutonomyAttentionService, PublicWorkspaceAutonomyContext,
    PublicWorkspaceAutonomyJudgePort, PublicWorkspaceAutonomyJudgePortError,
    PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgmentRequest,
    PublicWorkspaceAutonomyNextAction, PublicWorkspaceAutonomyScheduleService,
    PublicWorkspaceAutonomyService, PublicWorkspaceAutonomyVerdictKind,
    PublicWorkspaceTaskDispatchService,
};
use serde_json::json;
use tokio::sync::Notify;

struct ContinueJudge;

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for ContinueJudge {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        continue_judgment(request)
    }
}

struct ExpectedRootJudge {
    expected_root_id: &'static str,
}

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for ExpectedRootJudge {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        assert_eq!(
            request
                .candidates()
                .iter()
                .map(|candidate| candidate.root_task_id.as_str())
                .collect::<Vec<_>>(),
            vec![self.expected_root_id],
            "the Judge must never receive a root that already has in-flight work"
        );
        continue_judgment(request)
    }
}

struct BlockingCountingJudge {
    calls: AtomicUsize,
    first_entered: Notify,
    release_first: Notify,
}

struct CountingContinueJudge {
    calls: AtomicUsize,
}

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for CountingContinueJudge {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        continue_judgment(request)
    }
}

struct BlockJudge {
    calls: AtomicUsize,
}

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for BlockJudge {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let root = request
            .candidates()
            .first()
            .ok_or(PublicWorkspaceAutonomyJudgePortError::Unavailable)?;
        PublicWorkspaceAutonomyJudgment::new(
            request,
            PublicWorkspaceAutonomyVerdictKind::Block,
            Some(root.root_task_id.clone()),
            None,
            "The selected root requires editor attention before autonomous work can continue"
                .to_string(),
            "builtin:test-block-judge".to_string(),
            "judge_workspace_autonomy".to_string(),
            json!({"workspace_revision": request.workspace_revision()}),
            json!({
                "verdict": "block",
                "selected_root_task_id": &root.root_task_id,
                "next_action": null,
            }),
            1,
        )
        .map_err(|_| PublicWorkspaceAutonomyJudgePortError::Unavailable)
    }
}

impl BlockingCountingJudge {
    fn new() -> Self {
        Self {
            calls: AtomicUsize::new(0),
            first_entered: Notify::new(),
            release_first: Notify::new(),
        }
    }
}

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for BlockingCountingJudge {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        let call_index = self.calls.fetch_add(1, Ordering::SeqCst);
        if call_index == 0 {
            self.first_entered.notify_waiters();
            self.release_first.notified().await;
        }
        continue_judgment(request)
    }
}

fn continue_judgment(
    request: &PublicWorkspaceAutonomyJudgmentRequest,
) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
    let root = request
        .candidates()
        .first()
        .ok_or(PublicWorkspaceAutonomyJudgePortError::Unavailable)?;
    let binding = request
        .agent_candidates()
        .first()
        .ok_or(PublicWorkspaceAutonomyJudgePortError::Unavailable)?;
    PublicWorkspaceAutonomyJudgment::new(
        request,
        PublicWorkspaceAutonomyVerdictKind::Continue,
        Some(root.root_task_id.clone()),
        Some(PublicWorkspaceAutonomyNextAction {
            title: "Implement the next verified slice".to_string(),
            description: "Advance the autonomous root objective".to_string(),
            workspace_agent_binding_id: binding.workspace_agent_binding_id.clone(),
        }),
        "The open root and active binding support continued execution".to_string(),
        "builtin:test-judge".to_string(),
        "judge_workspace_autonomy".to_string(),
        json!({"workspace_revision": request.workspace_revision()}),
        json!({
            "verdict": "continue",
            "selected_root_task_id": &root.root_task_id,
            "next_action": {
                "title": "Implement the next verified slice",
                "description": "Advance the autonomous root objective",
                "workspace_agent_binding_id": &binding.workspace_agent_binding_id,
            },
        }),
        1,
    )
    .map_err(|_| PublicWorkspaceAutonomyJudgePortError::Unavailable)
}

#[tokio::test]
async fn scheduled_judgment_materializes_dispatch_and_runtime_correlation()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    let db: Arc<dyn DbPlugin> = Arc::new(db);
    let scheduler = WorkspaceAutonomyScheduler::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        Arc::new(ContinueJudge),
        WorkspaceAutonomySchedulerConfig {
            poll_interval: Duration::from_millis(10),
            ..WorkspaceAutonomySchedulerConfig::default()
        },
    )?;

    let schedule = scheduler.tick_once().await?;

    assert_eq!(schedule.due, 1);
    assert_eq!(schedule.triggered, 1);
    assert_eq!(
        scalar_string(
            db.as_ref(),
            "SELECT status AS value FROM workspace_autonomy_progression_outbox"
        )
        .await?,
        "pending"
    );

    let progression_worker = WorkspaceAutonomyProgressionWorker::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        WorkspaceAutonomyProgressionWorkerConfig {
            worker_id: "autonomy-progression-test".to_string(),
            poll_interval: Duration::from_millis(10),
            ..WorkspaceAutonomyProgressionWorkerConfig::default()
        },
    )?;
    let progressed = progression_worker.advance_once().await?;

    assert_eq!(progressed.claimed, 1);
    assert_eq!(progressed.completed, 1);
    assert_eq!(
        scalar_string(
            db.as_ref(),
            "SELECT status AS value FROM workspace_autonomy_progression_outbox"
        )
        .await?,
        "completed"
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_tasks WHERE status = 'in_progress' AND json_extract(metadata_json, '$.task_role') = 'execution_task' AND json_extract(metadata_json, '$.root_goal_task_id') = 'root-1' AND json_extract(metadata_json, '$.autonomy_progression_id') IS NOT NULL"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_task_dispatch_outbox WHERE status = 'pending'"
        )
        .await?,
        1
    );

    let task_worker_boundary =
        PublicWorkspaceTaskDispatchService::new(db.as_ref(), DbSqlFlavor::Sqlite);
    let now_ms = chrono::Utc::now().timestamp_millis();
    let claims = task_worker_boundary
        .claim_dispatches("task-dispatch-test", now_ms, now_ms + 120_000, 10)
        .await?;
    assert_eq!(claims.len(), 1);
    assert_eq!(claims[0].task_status, "in_progress");
    assert!(!claims[0].conversation_id.is_empty());
    assert!(!claims[0].delivery_request_id.is_empty());

    task_worker_boundary.prepare_correlation(&claims[0]).await?;
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_agent_runtime_correlations WHERE status = 'pending' AND conversation_id IS NOT NULL AND delivery_request_id = provider_run_id"
        )
        .await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn scheduled_judgment_excludes_roots_with_in_flight_execution_tasks()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    for statement in [
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, description, created_by, status, metadata_json) VALUES ('root-2', 'tenant-1', 'project-1', 'workspace-1', 'Second root', 'Advance the second goal', 'user-1', 'todo', '{\"task_role\":\"goal_root\"}')",
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, description, created_by, status, metadata_json) VALUES ('execution-root-1', 'tenant-1', 'project-1', 'workspace-1', 'Existing execution', 'Already advancing root one', 'user-1', 'in_progress', '{\"task_role\":\"execution_task\",\"root_goal_task_id\":\"root-1\"}')",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    let db: Arc<dyn DbPlugin> = Arc::new(db);
    let scheduler = WorkspaceAutonomyScheduler::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        Arc::new(ExpectedRootJudge {
            expected_root_id: "root-2",
        }),
        WorkspaceAutonomySchedulerConfig::default(),
    )?;

    let schedule = scheduler.tick_once().await?;

    assert_eq!(schedule.due, 1);
    assert_eq!(schedule.triggered, 1);
    assert_eq!(
        scalar_string(
            db.as_ref(),
            "SELECT root_task_id AS value FROM workspace_autonomy_progression_outbox"
        )
        .await?,
        "root-2"
    );
    Ok(())
}

#[tokio::test]
async fn concurrent_schedulers_call_the_judge_only_after_winning_the_durable_claim()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    let db: Arc<dyn DbPlugin> = Arc::new(db);
    let judge = Arc::new(BlockingCountingJudge::new());
    let first_entered = judge.first_entered.notified();
    let first_scheduler = Arc::new(WorkspaceAutonomyScheduler::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        judge.clone(),
        WorkspaceAutonomySchedulerConfig::default(),
    )?);
    let second_scheduler = WorkspaceAutonomyScheduler::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        judge.clone(),
        WorkspaceAutonomySchedulerConfig::default(),
    )?;

    let first_tick = tokio::spawn(async move { first_scheduler.tick_once().await });
    first_entered.await;
    let second_outcome = second_scheduler.tick_once().await?;
    judge.release_first.notify_waiters();
    let first_outcome = first_tick.await??;

    assert_eq!(
        judge.calls.load(Ordering::SeqCst),
        1,
        "a losing scheduler must not perform a duplicate semantic tool call"
    );
    assert_eq!(first_outcome.triggered + second_outcome.triggered, 1);
    assert_eq!(first_outcome.failed + second_outcome.failed, 1);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_judge_audits"
        )
        .await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn judgment_audit_survives_authority_cas_failure() -> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    let db: Arc<dyn DbPlugin> = Arc::new(db);
    let judge = Arc::new(BlockingCountingJudge::new());
    let first_entered = judge.first_entered.notified();
    let scheduler = Arc::new(WorkspaceAutonomyScheduler::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        judge.clone(),
        WorkspaceAutonomySchedulerConfig::default(),
    )?);

    let tick = tokio::spawn(async move { scheduler.tick_once().await });
    first_entered.await;
    db.execute(DbStatement::new(
        "UPDATE workspace_authorities SET revision = revision + 1 \
         WHERE workspace_id = 'workspace-1'",
    ))
    .await?;
    judge.release_first.notify_waiters();
    let outcome = tick.await??;

    assert_eq!(outcome.failed, 1);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_judge_audits \
             WHERE judgment_type = 'autonomy_tick' AND status = 'superseded'"
        )
        .await?,
        1,
        "the completed tool call must remain audited when the tick loses its CAS"
    );
    Ok(())
}

#[tokio::test]
async fn scheduler_waits_for_an_active_binding_without_calling_the_judge()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    db.execute(DbStatement::new(
        "DELETE FROM workspace_agent_bindings WHERE binding_id = 'binding-1'",
    ))
    .await?;
    let db: Arc<dyn DbPlugin> = Arc::new(db);
    let judge = Arc::new(CountingContinueJudge {
        calls: AtomicUsize::new(0),
    });
    let scheduler = WorkspaceAutonomyScheduler::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        judge.clone(),
        WorkspaceAutonomySchedulerConfig::default(),
    )?;

    let before_binding = scheduler.tick_once().await?;

    assert_eq!(before_binding.due, 0);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_judge_audits"
        )
        .await?,
        0
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_attentions"
        )
        .await?,
        0
    );

    db.execute(DbStatement::new(
        "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, \
         agent_id, bot_uuid, participant_actor_id, display_name, description, config_json, \
         is_active, status) VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', \
         'qa-read-agent', 'qa-read-agent', 'actor:qa-read-agent', 'QA Read Agent', \
         'Reads the workspace', '{}', 1, 'idle')",
    ))
    .await?;

    let after_binding = scheduler.tick_once().await?;

    assert_eq!(after_binding.due, 1);
    assert_eq!(after_binding.triggered, 1);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn manual_tick_without_an_active_binding_is_structurally_not_applicable()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    db.execute(DbStatement::new(
        "DELETE FROM workspace_agent_bindings WHERE binding_id = 'binding-1'",
    ))
    .await?;
    let judge = CountingContinueJudge {
        calls: AtomicUsize::new(0),
    };
    let service = PublicWorkspaceAutonomyService::new(&db, DbSqlFlavor::Sqlite, &judge);

    let outcome = service
        .tick(
            &PublicWorkspaceAutonomyContext {
                expected_revision: Some(0),
                idempotency_key: Some("manual-before-binding".to_string()),
                ..autonomy_context("user-1")
            },
            true,
        )
        .await?;

    assert!(!outcome.response.triggered);
    assert_eq!(outcome.response.reason, "no_active_agent");
    assert_eq!(judge.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_judge_audits").await?,
        0
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_autonomy_attentions"
        )
        .await?,
        0
    );

    db.execute(DbStatement::new(
        "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, \
         agent_id, bot_uuid, participant_actor_id, display_name, description, config_json, \
         is_active, status) VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', \
         'qa-read-agent', 'qa-read-agent', 'actor:qa-read-agent', 'QA Read Agent', \
         'Reads the workspace', '{}', 1, 'idle')",
    ))
    .await?;

    let after_binding = service
        .tick(
            &PublicWorkspaceAutonomyContext {
                idempotency_key: Some("manual-after-binding".to_string()),
                ..autonomy_context("user-1")
            },
            true,
        )
        .await?;

    assert!(after_binding.response.triggered);
    assert_eq!(after_binding.response.reason, "triggered");
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn judge_block_attention_stops_scheduling_until_an_editor_resolves_it()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    let db: Arc<dyn DbPlugin> = Arc::new(db);
    let judge = Arc::new(BlockJudge {
        calls: AtomicUsize::new(0),
    });
    let scheduler = WorkspaceAutonomyScheduler::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        judge.clone(),
        WorkspaceAutonomySchedulerConfig::default(),
    )?;

    let blocked = scheduler.tick_once().await?;

    assert_eq!(blocked.due, 1);
    assert_eq!(blocked.not_triggered, 1);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_attentions \
             WHERE source_kind = 'judge_block' AND status = 'open' AND root_task_id = 'root-1'"
        )
        .await?,
        1
    );
    let future_due = PublicWorkspaceAutonomyScheduleService::new(db.as_ref(), DbSqlFlavor::Sqlite)
        .list_due("9999-12-31T23:59:59.999999Z", 10)
        .await?;
    assert!(
        future_due.is_empty(),
        "open attention must outlive the cooldown"
    );

    let attention_id = scalar_string(
        db.as_ref(),
        "SELECT attention_id AS value FROM workspace_autonomy_attentions \
         WHERE source_kind = 'judge_block'",
    )
    .await?;
    let resolution_context = PublicWorkspaceAutonomyContext {
        expected_revision: Some(1),
        idempotency_key: Some("resolve-blocked-root-1".to_string()),
        ..autonomy_context("user-1")
    };
    let attention_service =
        PublicWorkspaceAutonomyAttentionService::new(db.as_ref(), DbSqlFlavor::Sqlite);
    let resolved = attention_service
        .resolve_judge_attention(
            &resolution_context,
            attention_id.as_str(),
            chrono::Utc::now().timestamp_millis(),
        )
        .await?;
    assert_eq!(resolved.attention_id, attention_id);
    assert_eq!(resolved.status, "resolved");
    assert_eq!(resolved.committed_revision, 2);
    assert!(!resolved.replayed);
    let replay = attention_service
        .resolve_judge_attention(
            &resolution_context,
            attention_id.as_str(),
            chrono::Utc::now().timestamp_millis(),
        )
        .await?;
    assert_eq!(replay.committed_revision, 2);
    assert!(replay.replayed);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_attentions \
             WHERE source_kind = 'judge_block' AND status = 'open' AND root_task_id = 'root-1'"
        )
        .await?,
        0
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts \
             WHERE surface = 'autonomy_attention' AND action = 'resolve'"
        )
        .await?,
        1
    );
    let due_after_resolution =
        PublicWorkspaceAutonomyScheduleService::new(db.as_ref(), DbSqlFlavor::Sqlite)
            .list_due("9999-12-31T23:59:59.999999Z", 10)
            .await?;
    assert_eq!(due_after_resolution.len(), 1);
    Ok(())
}

#[tokio::test]
async fn dead_letter_attention_requires_an_editor_and_retries_the_original_progression()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    for statement in [
        "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, root_task_id, actor_id, verdict, reason) VALUES ('dead-letter-tick', 'tenant-1', 'project-1', 'workspace-1', 'root-1', 'user-1', 'continue', 'triggered')",
        "INSERT INTO workspace_autonomy_progression_outbox (progression_id, tick_id, tenant_id, project_id, workspace_id, root_task_id, actor_id, judge_agent_id, workspace_agent_binding_id, task_title, task_description, status, attempt_count, max_attempts, created_at_ms) VALUES ('dead-letter-progression', 'dead-letter-tick', 'tenant-1', 'project-1', 'workspace-1', 'root-1', 'user-1', 'judge-1', 'binding-1', 'Retry work', 'Retry the original work', 'pending', 1, 1, 1)",
        "UPDATE workspace_autonomy_progression_outbox SET status = 'dead_letter', last_error = 'retry budget exhausted' WHERE progression_id = 'dead-letter-progression'",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    let attention_id = scalar_string(
        &db,
        "SELECT attention_id AS value FROM workspace_autonomy_attentions \
         WHERE source_kind = 'progression_dead_letter'",
    )
    .await?;
    let service = PublicWorkspaceAutonomyAttentionService::new(&db, DbSqlFlavor::Sqlite);

    let unauthorized = match service
        .retry_dead_letter(&autonomy_context("intruder"), attention_id.as_str(), 10)
        .await
    {
        Ok(_) => return Err("intruder unexpectedly retried a dead letter".into()),
        Err(error) => error,
    };
    assert!(unauthorized.to_string().contains("editor access"));

    service
        .retry_dead_letter(&autonomy_context("user-1"), attention_id.as_str(), 10)
        .await?;

    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_autonomy_progression_outbox \
             WHERE progression_id = 'dead-letter-progression' AND status = 'pending' \
             AND attempt_count = 0 AND next_attempt_at_ms = 10"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_autonomy_attentions \
             WHERE attention_id = 'progression:dead-letter-progression' AND status = 'resolved' \
             AND resolved_by_actor_id = 'user-1'"
        )
        .await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn progression_ack_failure_does_not_abandon_later_claims() -> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    seed_autonomous_workspace(&db).await?;
    for statement in [
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, description, created_by, status, metadata_json) VALUES ('root-2', 'tenant-1', 'project-1', 'workspace-1', 'Second root', 'Advance the second goal', 'user-1', 'todo', '{\"task_role\":\"goal_root\"}')",
        "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, root_task_id, actor_id, verdict, reason) VALUES ('tick-1', 'tenant-1', 'project-1', 'workspace-1', 'root-1', 'user-1', 'continue', 'triggered')",
        "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, root_task_id, actor_id, verdict, reason) VALUES ('tick-2', 'tenant-1', 'project-1', 'workspace-1', 'root-2', 'user-1', 'continue', 'triggered')",
        "INSERT INTO workspace_autonomy_progression_outbox (progression_id, tick_id, tenant_id, project_id, workspace_id, root_task_id, actor_id, judge_agent_id, workspace_agent_binding_id, task_title, task_description, created_at_ms) VALUES ('progression-1', 'tick-1', 'tenant-1', 'project-1', 'workspace-1', 'root-1', 'user-1', 'judge-1', 'binding-1', 'First execution', 'Advance root one', 1)",
        "INSERT INTO workspace_autonomy_progression_outbox (progression_id, tick_id, tenant_id, project_id, workspace_id, root_task_id, actor_id, judge_agent_id, workspace_agent_binding_id, task_title, task_description, created_at_ms) VALUES ('progression-2', 'tick-2', 'tenant-1', 'project-1', 'workspace-1', 'root-2', 'user-1', 'judge-1', 'binding-1', 'Second execution', 'Advance root two', 2)",
        "CREATE TRIGGER reject_first_progression_completion BEFORE UPDATE OF status ON workspace_autonomy_progression_outbox WHEN OLD.progression_id = 'progression-1' AND NEW.status = 'completed' BEGIN SELECT RAISE(FAIL, 'injected first ACK failure'); END",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    let db: Arc<dyn DbPlugin> = Arc::new(db);
    let worker = WorkspaceAutonomyProgressionWorker::new(
        Arc::clone(&db),
        DbSqlFlavor::Sqlite,
        WorkspaceAutonomyProgressionWorkerConfig {
            worker_id: "autonomy-progression-partial-failure".to_string(),
            batch_size: 2,
            ..WorkspaceAutonomyProgressionWorkerConfig::default()
        },
    )?;

    let outcome = worker.advance_once().await?;

    assert_eq!(outcome.claimed, 2);
    assert_eq!(outcome.completed, 1);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_progression_outbox WHERE status = 'completed' AND progression_id = 'progression-2'"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_progression_outbox WHERE status = 'processing' AND progression_id = 'progression-1'"
        )
        .await?,
        1
    );
    Ok(())
}

async fn seed_autonomous_workspace(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for statement in [
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, description, created_by, metadata_json) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1', 'Autonomous QA', 'Advance the goal', 'user-1', '{\"collaboration_mode\":\"autonomous\"}')",
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-1', 'tenant-1', 'project-1', 'workspace-1', 'user-1', 'actor:user-1', 'owner')",
        "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES ('workspace-1', 'tenant-1', 'project-1', 0)",
        "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, agent_id, bot_uuid, participant_actor_id, display_name, description, config_json, is_active, status) VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', 'agent-1', 'bot-1', 'actor:agent-1', 'Delivery Agent', 'Executes verified slices', '{}', 1, 'idle')",
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, description, created_by, status, metadata_json) VALUES ('root-1', 'tenant-1', 'project-1', 'workspace-1', 'Autonomous QA', 'Advance the goal', 'user-1', 'todo', '{\"task_role\":\"goal_root\"}')",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(())
}

fn autonomy_context(user_id: &str) -> PublicWorkspaceAutonomyContext {
    PublicWorkspaceAutonomyContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        user_id: user_id.to_string(),
        is_superuser: false,
        expected_revision: None,
        idempotency_key: None,
    }
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("scalar query returned no rows")?
        .get_i64("value")?
        .ok_or("scalar value is NULL")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("scalar query returned no rows")?
        .get_string("value")?
        .ok_or("scalar value is NULL")?)
}
