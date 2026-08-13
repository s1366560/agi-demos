use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    PublicCreateWorkspaceTaskInput, PublicWorkspaceTaskContext, PublicWorkspaceTaskDispatchService,
    PublicWorkspaceTaskErrorKind, PublicWorkspaceTaskRecoveryInput, PublicWorkspaceTaskService,
};
use serde_json::{Value, json};

#[tokio::test]
async fn task_service_create_list_replay_assign_and_transition_are_atomic()
-> Result<(), Box<dyn Error>> {
    let db = seeded_task_db().await?;
    let service = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Sqlite);
    let create = PublicCreateWorkspaceTaskInput {
        context: task_context("create-1", Some(0)),
        title: "Ship Task authority".to_string(),
        description: Some("Preserve the compatibility contract".to_string()),
        assignee_user_id: None,
        metadata: Some(json!({"source": "contract"})),
        preferred_language: Some("zh-CN".to_string()),
        priority: Some("P2".to_string()),
        estimated_effort: Some("2h".to_string()),
        blocker_reason: None,
    };

    let created = service.create(&create).await?;
    let replayed = service.create(&create).await?;
    assert!(!created.replayed);
    assert!(replayed.replayed);
    assert_eq!(replayed.task, created.task);
    assert_eq!(created.task.priority.as_deref(), Some("P2"));
    assert_eq!(created.task.metadata["preferred_language"], "zh-CN");

    let assigned = service
        .assign_agent(
            &task_context("assign-1", Some(1)),
            created.task.id.as_str(),
            "binding-1",
            Some("en-US"),
        )
        .await?;
    assert_eq!(assigned.task.assignee_agent_id.as_deref(), Some("agent-1"));
    assert_eq!(
        assigned.task.workspace_agent_id.as_deref(),
        Some("binding-1")
    );

    let started = service
        .transition(
            &task_context("start-1", Some(2)),
            created.task.id.as_str(),
            "in_progress",
        )
        .await?;
    assert_eq!(started.task.status, "in_progress");

    let listed = service
        .list(&task_context("read", None), Some("in_progress"), 100, 0)
        .await?;
    assert_eq!(listed, vec![started.task]);
    assert_eq!(table_count(&db, "workspace_task_receipts").await?, 3);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 3);
    assert_eq!(authority_revision(&db).await?, 3);
    Ok(())
}

#[tokio::test]
async fn task_service_projects_execution_experience_and_recovery() -> Result<(), Box<dyn Error>> {
    let db = seeded_task_db().await?;
    let service = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Sqlite);
    let created = service
        .create(&PublicCreateWorkspaceTaskInput {
            context: task_context("create-recovery", Some(0)),
            title: "Recover worker".to_string(),
            description: None,
            assignee_user_id: None,
            metadata: Some(json!({})),
            preferred_language: None,
            priority: None,
            estimated_effort: None,
            blocker_reason: None,
        })
        .await?;

    let recovery = service
        .recovery_action(
            &task_context("new-attempt-1", Some(1)),
            created.task.id.as_str(),
            &PublicWorkspaceTaskRecoveryInput {
                action: "new_attempt".to_string(),
                reason: Some("Retry after explicit operator review".to_string()),
                workspace_agent_id: None,
            },
        )
        .await?;
    assert_eq!(recovery.status, "queued");
    assert!(recovery.attempt_id.is_some());
    assert!(recovery.outbox_id.is_some());

    let experience = service
        .experience(&task_context("read", None), created.task.id.as_str())
        .await?;
    assert_eq!(experience["execution"]["attempts"][0]["attempt_number"], 1);
    assert_eq!(
        experience["readiness"]["transition_gates"]["judgment"],
        "agent_judgment_required"
    );
    let session = service
        .execution_session(&task_context("read", None), created.task.id.as_str())
        .await?;
    assert_eq!(session["session_status"], "not_started");
    assert_eq!(session["attempt_status"], "pending");
    Ok(())
}

#[tokio::test]
async fn recovery_action_commits_ordered_events_and_replays_without_duplicates()
-> Result<(), Box<dyn Error>> {
    let db = seeded_task_db().await?;
    let service = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Sqlite);
    let created = service
        .create(&PublicCreateWorkspaceTaskInput {
            context: task_context("create-recovery-events", Some(0)),
            title: "Recover with durable events".to_string(),
            description: None,
            assignee_user_id: None,
            metadata: Some(json!({})),
            preferred_language: None,
            priority: None,
            estimated_effort: None,
            blocker_reason: None,
        })
        .await?;
    let recovery_context = task_context("recovery-events", Some(1));
    let recovery_input = PublicWorkspaceTaskRecoveryInput {
        action: "new_attempt".to_string(),
        reason: Some("Operator approved a new attempt".to_string()),
        workspace_agent_id: None,
    };

    let committed = service
        .recovery_action_with_authority(
            &recovery_context,
            created.task.id.as_str(),
            &recovery_input,
        )
        .await?;
    assert!(!committed.replayed);
    let events = task_outbox_events(&db, created.task.id.as_str()).await?;
    assert_eq!(
        events
            .iter()
            .map(|event| event.event_type.as_str())
            .collect::<Vec<_>>(),
        vec![
            "workspace_task_created",
            "task_recovery_action_started",
            "task_execution_session_updated",
            "task_execution_incident_opened",
            "task_recovery_action_completed",
        ]
    );
    assert!(
        events
            .windows(2)
            .all(|pair| pair[0].event_sequence < pair[1].event_sequence)
    );
    assert_eq!(
        committed.response.outbox_id.as_deref(),
        Some(events[1].outbox_id.as_str())
    );
    assert_eq!(events[2].payload["workspace_id"], "workspace-1");
    assert_eq!(events[2].payload["task_id"], created.task.id);
    assert_eq!(events[2].payload["session"]["attempt_status"], "pending");
    assert_eq!(
        events[3].payload["incident"]["type"],
        "recovery_action_requested"
    );
    assert_eq!(events[3].payload["incident"]["action"], "new_attempt");
    assert_eq!(events[4].payload["action"], "new_attempt");
    assert_eq!(committed.committed_revision, 5);

    let replayed = service
        .recovery_action_with_authority(
            &recovery_context,
            created.task.id.as_str(),
            &recovery_input,
        )
        .await?;
    assert!(replayed.replayed);
    assert_eq!(replayed.response, committed.response);
    assert_eq!(
        task_outbox_events(&db, created.task.id.as_str()).await?,
        events
    );
    assert_eq!(table_count(&db, "workspace_task_receipts").await?, 2);
    assert_eq!(authority_revision(&db).await?, 5);

    let conflicting_input = PublicWorkspaceTaskRecoveryInput {
        reason: Some("A different recovery intent".to_string()),
        ..recovery_input
    };
    let conflict = service
        .recovery_action_with_authority(
            &recovery_context,
            created.task.id.as_str(),
            &conflicting_input,
        )
        .await
        .expect_err("one idempotency key accepted a different recovery intent");
    assert_eq!(conflict.kind(), PublicWorkspaceTaskErrorKind::Conflict);
    assert_eq!(
        task_outbox_events(&db, created.task.id.as_str()).await?,
        events
    );

    let transitioned = service
        .transition(
            &task_context(
                "post-recovery-transition",
                Some(committed.committed_revision),
            ),
            created.task.id.as_str(),
            "in_progress",
        )
        .await?;
    assert_eq!(transitioned.committed_revision, 6);
    let events_after_transition = task_outbox_events(&db, created.task.id.as_str()).await?;
    assert_eq!(events_after_transition.len(), 6);
    assert_eq!(events_after_transition[5].event_sequence, 6);
    Ok(())
}

#[tokio::test]
async fn recovery_event_failure_rolls_back_task_attempt_receipt_revision_and_all_events()
-> Result<(), Box<dyn Error>> {
    let db = seeded_task_db().await?;
    let service = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Sqlite);
    let created = service
        .create(&PublicCreateWorkspaceTaskInput {
            context: task_context("create-recovery-rollback", Some(0)),
            title: "Rollback recovery events".to_string(),
            description: None,
            assignee_user_id: None,
            metadata: Some(json!({})),
            preferred_language: None,
            priority: None,
            estimated_effort: None,
            blocker_reason: None,
        })
        .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_recovery_incident BEFORE INSERT ON workspace_outbox WHEN NEW.event_type = 'task_execution_incident_opened' BEGIN SELECT RAISE(ABORT, 'injected recovery event failure'); END",
    ))
    .await?;

    let error = service
        .recovery_action(
            &task_context("recovery-rollback", Some(1)),
            created.task.id.as_str(),
            &PublicWorkspaceTaskRecoveryInput {
                action: "new_attempt".to_string(),
                reason: Some("This transaction must roll back".to_string()),
                workspace_agent_id: None,
            },
        )
        .await
        .expect_err("one rejected recovery event did not abort the Task transaction");

    assert_eq!(error.kind(), PublicWorkspaceTaskErrorKind::Unavailable);
    assert_eq!(table_count(&db, "workspace_task_receipts").await?, 1);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 1);
    assert_eq!(table_count(&db, "workspace_task_attempts").await?, 0);
    assert_eq!(authority_revision(&db).await?, 1);
    let persisted = service
        .get(&task_context("read", None), created.task.id.as_str())
        .await?;
    assert!(persisted.metadata.get("recovery_actions").is_none());
    assert!(persisted.metadata.get("current_attempt_id").is_none());
    Ok(())
}

#[tokio::test]
async fn execution_task_assignment_and_recovery_enqueue_fenced_dispatches()
-> Result<(), Box<dyn Error>> {
    let db = seeded_task_db().await?;
    let tasks = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Sqlite);
    let created = tasks
        .create(&PublicCreateWorkspaceTaskInput {
            context: task_context("create-execution", Some(0)),
            title: "Execute assigned work".to_string(),
            description: Some("Persist before Provider delivery".to_string()),
            assignee_user_id: None,
            metadata: Some(json!({
                "task_role": "execution_task",
                "plan_id": "plan-1",
                "plan_node_id": "node-1",
            })),
            preferred_language: None,
            priority: None,
            estimated_effort: None,
            blocker_reason: None,
        })
        .await?;

    let assignment_context = task_context("assign-execution", Some(1));
    let assigned = tasks
        .assign_agent(
            &assignment_context,
            created.task.id.as_str(),
            "binding-1",
            Some("zh-CN"),
        )
        .await?;
    assert!(!assigned.replayed);
    assert_eq!(table_count(&db, "workspace_task_dispatch_outbox").await?, 1);
    let replayed = tasks
        .assign_agent(
            &assignment_context,
            created.task.id.as_str(),
            "binding-1",
            Some("zh-CN"),
        )
        .await?;
    assert!(replayed.replayed);
    assert_eq!(table_count(&db, "workspace_task_dispatch_outbox").await?, 1);
    let conflict = match tasks
        .assign_agent(
            &assignment_context,
            created.task.id.as_str(),
            "binding-1",
            Some("en-US"),
        )
        .await
    {
        Ok(_) => return Err("one idempotency key accepted a different dispatch payload".into()),
        Err(error) => error,
    };
    assert_eq!(conflict.kind(), PublicWorkspaceTaskErrorKind::Conflict);
    assert_eq!(table_count(&db, "workspace_task_dispatch_outbox").await?, 1);

    assert!(
        db.execute(DbStatement::new(
            "UPDATE workspace_task_dispatch_outbox SET bot_uuid = 'bot-overwritten'"
        ))
        .await
        .is_err()
    );
    let dispatches = PublicWorkspaceTaskDispatchService::new(&db, DbSqlFlavor::Sqlite);
    let first = dispatches
        .claim_dispatches("worker-1", 100, 200, 10)
        .await?;
    assert_eq!(first.len(), 1);
    assert_eq!(first[0].task_id, created.task.id);
    assert_eq!(first[0].user_id, "user-1");
    assert_eq!(first[0].agent_id, "agent-1");
    assert_eq!(first[0].bot_uuid, "bot-1");
    assert_eq!(first[0].group_id, "group-1");
    assert_eq!(first[0].plan_id.as_deref(), Some("plan-1"));
    assert_eq!(first[0].plan_node_id.as_deref(), Some("node-1"));
    dispatches.prepare_correlation(&first[0]).await?;
    dispatches.complete_dispatch(&first[0], 150).await?;
    let stale = match dispatches.complete_dispatch(&first[0], 151).await {
        Ok(()) => return Err("a completed lease was reusable".into()),
        Err(error) => error,
    };
    assert_eq!(stale.kind(), PublicWorkspaceTaskErrorKind::Unavailable);
    assert_eq!(
        table_count(&db, "workspace_agent_runtime_correlations").await?,
        1
    );

    let new_attempt = tasks
        .recovery_action_with_authority(
            &task_context("new-attempt-execution", Some(2)),
            created.task.id.as_str(),
            &PublicWorkspaceTaskRecoveryInput {
                action: "new_attempt".to_string(),
                reason: Some("Operator approved a fresh attempt".to_string()),
                workspace_agent_id: None,
            },
        )
        .await?;
    assert!(new_attempt.response.attempt_id.is_some());
    assert_eq!(table_count(&db, "workspace_task_dispatch_outbox").await?, 2);

    let retry_launch = tasks
        .recovery_action_with_authority(
            &task_context(
                "retry-launch-execution",
                Some(new_attempt.committed_revision),
            ),
            created.task.id.as_str(),
            &PublicWorkspaceTaskRecoveryInput {
                action: "retry_launch".to_string(),
                reason: Some("Retry the same durable launch".to_string()),
                workspace_agent_id: None,
            },
        )
        .await?;
    assert_eq!(table_count(&db, "workspace_task_dispatch_outbox").await?, 3);

    let leased = dispatches
        .claim_dispatches("worker-2", 300, 400, 10)
        .await?;
    assert_eq!(leased.len(), 2);
    let failed = dispatches
        .fail_dispatch(&leased[0], 500, "workspace_provider_delivery_failed")
        .await?;
    assert!(!failed.dead_lettered);
    let recovered = dispatches
        .claim_dispatches("worker-3", 400, 500, 10)
        .await?;
    assert_eq!(recovered.len(), 1);
    assert_eq!(recovered[0].dispatch_id, leased[1].dispatch_id);
    let stale = match dispatches.complete_dispatch(&leased[1], 450).await {
        Ok(()) => return Err("an expired lease generation finalized a reclaimed row".into()),
        Err(error) => error,
    };
    assert_eq!(stale.kind(), PublicWorkspaceTaskErrorKind::Unavailable);
    dispatches.complete_dispatch(&recovered[0], 450).await?;

    let retry = dispatches
        .claim_dispatches("worker-4", 500, 600, 10)
        .await?;
    assert_eq!(retry.len(), 1);
    db.execute(DbStatement::new(
        "UPDATE workspace_task_dispatch_outbox SET max_attempts = attempt_count WHERE status = 'delivering'",
    ))
    .await?;
    let dead_lettered = dispatches
        .fail_dispatch(&retry[0], 700, "workspace_provider_delivery_rejected")
        .await?;
    assert!(dead_lettered.dead_lettered);

    tasks
        .recovery_action(
            &task_context(
                "human-block-execution",
                Some(retry_launch.committed_revision),
            ),
            created.task.id.as_str(),
            &PublicWorkspaceTaskRecoveryInput {
                action: "mark_human_blocked".to_string(),
                reason: Some("Human input is required".to_string()),
                workspace_agent_id: None,
            },
        )
        .await?;
    assert_eq!(table_count(&db, "workspace_task_dispatch_outbox").await?, 3);
    Ok(())
}

#[tokio::test]
async fn dispatch_snapshot_failure_rolls_back_task_receipt_revision_and_event()
-> Result<(), Box<dyn Error>> {
    let db = seeded_task_db().await?;
    let tasks = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Sqlite);
    let created = tasks
        .create(&PublicCreateWorkspaceTaskInput {
            context: task_context("create-dispatch-rollback", Some(0)),
            title: "Rollback dispatch".to_string(),
            description: None,
            assignee_user_id: None,
            metadata: Some(json!({"task_role": "execution_task"})),
            preferred_language: None,
            priority: None,
            estimated_effort: None,
            blocker_reason: None,
        })
        .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_task_dispatch BEFORE INSERT ON workspace_task_dispatch_outbox BEGIN SELECT RAISE(ABORT, 'injected task dispatch failure'); END",
    ))
    .await?;

    let error = match tasks
        .assign_agent(
            &task_context("assign-dispatch-rollback", Some(1)),
            created.task.id.as_str(),
            "binding-1",
            None,
        )
        .await
    {
        Ok(_) => return Err("dispatch failure did not abort the complete Task transaction".into()),
        Err(error) => error,
    };

    assert_eq!(error.kind(), PublicWorkspaceTaskErrorKind::Unavailable);
    assert_eq!(table_count(&db, "workspace_task_dispatch_outbox").await?, 0);
    assert_eq!(table_count(&db, "workspace_task_receipts").await?, 1);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 1);
    assert_eq!(authority_revision(&db).await?, 1);
    let persisted = tasks
        .get(&task_context("read", None), created.task.id.as_str())
        .await?;
    assert!(persisted.assignee_agent_id.is_none());
    assert!(persisted.workspace_agent_id.is_none());
    Ok(())
}

#[tokio::test]
async fn goal_root_cannot_be_assigned_through_the_legacy_task_route() -> Result<(), Box<dyn Error>>
{
    let db = seeded_task_db().await?;
    let tasks = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Sqlite);
    let created = tasks
        .create(&PublicCreateWorkspaceTaskInput {
            context: task_context("create-goal-root", Some(0)),
            title: "Goal root".to_string(),
            description: None,
            assignee_user_id: None,
            metadata: Some(json!({"task_role": "goal_root"})),
            preferred_language: None,
            priority: None,
            estimated_effort: None,
            blocker_reason: None,
        })
        .await?;
    let error = match tasks
        .assign_agent(
            &task_context("assign-goal-root", Some(1)),
            created.task.id.as_str(),
            "binding-1",
            None,
        )
        .await
    {
        Ok(_) => return Err("goal_root assignment bypassed structured authority".into()),
        Err(error) => error,
    };
    assert_eq!(error.kind(), PublicWorkspaceTaskErrorKind::Forbidden);
    assert_eq!(table_count(&db, "workspace_task_dispatch_outbox").await?, 0);
    Ok(())
}

async fn seeded_task_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL, deleted_at TEXT, UNIQUE(tenant_id, project_id, workspace_id))",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, is_active INTEGER NOT NULL)",
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, assignee_user_id TEXT, assignee_agent_id TEXT, status TEXT NOT NULL, priority INTEGER NOT NULL, estimated_effort TEXT, blocker_reason TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, archived_at TEXT)",
        "CREATE TABLE workspace_task_attempts (attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT NOT NULL, root_goal_task_id TEXT NOT NULL, attempt_number INTEGER NOT NULL, status TEXT NOT NULL, conversation_id TEXT, worker_agent_id TEXT, leader_agent_id TEXT, candidate_summary TEXT, candidate_artifacts_json TEXT NOT NULL, candidate_verifications_json TEXT NOT NULL, leader_feedback TEXT, adjudication_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, UNIQUE(task_id, attempt_number))",
        "CREATE TABLE workspace_task_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT, actor_id TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, expected_revision INTEGER, committed_revision INTEGER, result_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_task_dispatch_outbox (dispatch_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT, plan_id TEXT, plan_node_id TEXT, user_id TEXT NOT NULL, agent_id TEXT NOT NULL, workspace_agent_binding_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, group_id TEXT NOT NULL, conversation_id TEXT NOT NULL, delivery_request_id TEXT NOT NULL UNIQUE, task_title TEXT NOT NULL, task_description TEXT, status TEXT NOT NULL, attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL, next_attempt_at_ms INTEGER NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, lease_generation INTEGER NOT NULL, last_error TEXT, delivered_at_ms INTEGER, created_at_ms INTEGER NOT NULL)",
        "CREATE TRIGGER prevent_workspace_task_dispatch_snapshot_update BEFORE UPDATE OF tenant_id, project_id, workspace_id, task_id, attempt_id, plan_id, plan_node_id, user_id, agent_id, workspace_agent_binding_id, bot_uuid, group_id, conversation_id, delivery_request_id, task_title, task_description, created_at_ms ON workspace_task_dispatch_outbox BEGIN SELECT RAISE(ABORT, 'Workspace task dispatch snapshot is immutable'); END",
        "CREATE TABLE workspace_agent_runtime_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT, task_id TEXT, attempt_id TEXT, plan_id TEXT, plan_node_id TEXT, conversation_id TEXT NOT NULL, delivery_request_id TEXT, provider_run_id TEXT, bcs_group_id TEXT, provider_id TEXT, provider_bot_ref TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_execution_terminals (terminal_id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL, execution_status TEXT NOT NULL)",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_agent_bindings VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', 'agent-1', 'bot-1', 1)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

fn task_context(
    idempotency_key: &str,
    expected_revision: Option<u64>,
) -> PublicWorkspaceTaskContext {
    PublicWorkspaceTaskContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        user_id: "user-1".to_string(),
        expected_revision,
        idempotency_key: (idempotency_key != "read").then(|| idempotency_key.to_string()),
    }
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_task_receipts" => "SELECT COUNT(*) AS value FROM workspace_task_receipts",
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        "workspace_task_dispatch_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_task_dispatch_outbox"
        }
        "workspace_task_attempts" => "SELECT COUNT(*) AS value FROM workspace_task_attempts",
        "workspace_agent_runtime_correlations" => {
            "SELECT COUNT(*) AS value FROM workspace_agent_runtime_correlations"
        }
        _ => return Err("unsupported table".into()),
    };
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing count")?
        .get_i64("value")?
        .ok_or("missing count value")?)
}

#[derive(Debug, PartialEq)]
struct TaskOutboxEvent {
    outbox_id: String,
    event_type: String,
    event_sequence: i64,
    payload: Value,
}

async fn task_outbox_events(
    db: &dyn DbPlugin,
    task_id: &str,
) -> Result<Vec<TaskOutboxEvent>, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT outbox_id, event_type, event_sequence, payload_json FROM workspace_outbox WHERE aggregate_id = ? ORDER BY event_sequence, outbox_id",
            vec![task_id.into()],
        ))
        .await?;
    rows.iter()
        .map(|row| {
            let outbox_id = row.get_string("outbox_id")?.ok_or("missing outbox_id")?;
            let event_type = row.get_string("event_type")?.ok_or("missing event_type")?;
            let event_sequence = row
                .get_i64("event_sequence")?
                .ok_or("missing event_sequence")?;
            let payload = serde_json::from_str(
                row.get_string("payload_json")?
                    .ok_or("missing payload_json")?
                    .as_str(),
            )?;
            Ok(TaskOutboxEvent {
                outbox_id,
                event_type,
                event_sequence,
                payload,
            })
        })
        .collect()
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
        ))
        .await?
        .first()
        .ok_or("missing authority")?
        .get_i64("value")?
        .ok_or("missing revision")?)
}
