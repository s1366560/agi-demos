use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::desktop_schema::run_desktop_workspace_schema_migrations;
use memstack_workspace_service::{
    PublicWorkspaceAutonomyScheduleService, PublicWorkspaceRuntimeTerminalContext,
    PublicWorkspaceRuntimeTerminalErrorKind, PublicWorkspaceRuntimeTerminalInput,
    PublicWorkspaceRuntimeTerminalService,
};
use serde_json::json;

#[tokio::test]
async fn final_terminal_atomically_releases_execution_and_root_for_judgment()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db(
        "final-workspace",
        "final-root",
        "final-task",
        "final-attempt",
    )
    .await?;
    let service = PublicWorkspaceRuntimeTerminalService::new(&db, DbSqlFlavor::Sqlite);
    let context = terminal_context("final-workspace");
    let input = terminal_input("complete", "final-event", json!({"content": "done"}));

    let first = service
        .record(&context, "final-correlation", &input)
        .await?;
    assert!(first.created);
    assert_eq!(first.status, "completed");
    assert_eq!(first.task_status.as_deref(), Some("done"));
    assert_eq!(first.attempt_status.as_deref(), Some("completed"));
    assert_eq!(
        first.terminal_id.as_deref(),
        Some("runtime-terminal-final-correlation")
    );

    let replay = service
        .record(&context, "final-correlation", &input)
        .await?;
    assert!(!replay.created);
    assert_eq!(
        scalar(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        1
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_agent_runtime_correlations"
        )
        .await?,
        "completed"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_tasks WHERE task_id = 'final-task'"
        )
        .await?,
        "done"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_task_attempts WHERE attempt_id = 'final-attempt'"
        )
        .await?,
        "completed"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_tasks WHERE task_id = 'final-root'"
        )
        .await?,
        "todo",
        "a structural execution terminal must not make the subjective root verdict"
    );
    assert_eq!(
        scalar(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_execution_terminals"
        )
        .await?,
        1
    );

    let due = PublicWorkspaceAutonomyScheduleService::new(&db, DbSqlFlavor::Sqlite)
        .list_due("1970-01-01T00:00:00Z", 10)
        .await?;
    assert_eq!(due.len(), 1);
    assert_eq!(due[0].workspace_id, "final-workspace");

    let conflicting = terminal_input("complete", "final-event", json!({"content": "different"}));
    let error = match service
        .record(&context, "final-correlation", &conflicting)
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("the same terminal id accepted different content".into()),
    };
    assert_eq!(
        error.kind(),
        PublicWorkspaceRuntimeTerminalErrorKind::Conflict
    );
    Ok(())
}

#[tokio::test]
async fn failed_and_aborted_terminals_block_execution_with_durable_reason()
-> Result<(), Box<dyn Error>> {
    for (suffix, execution_status, stored_status) in [
        ("error", "error", "failed"),
        ("abort", "aborted", "aborted"),
    ] {
        let workspace_id = format!("{suffix}-workspace");
        let root_id = format!("{suffix}-root");
        let task_id = format!("{suffix}-task");
        let attempt_id = format!("{suffix}-attempt");
        let correlation_id = format!("{suffix}-correlation");
        let db = seeded_db(&workspace_id, &root_id, &task_id, &attempt_id).await?;
        let service = PublicWorkspaceRuntimeTerminalService::new(&db, DbSqlFlavor::Sqlite);
        let context = terminal_context(&workspace_id);
        let input = terminal_input(
            execution_status,
            &format!("{suffix}-event"),
            json!({"error_message": "runtime stopped"}),
        );

        let outcome = service.record(&context, &correlation_id, &input).await?;

        assert_eq!(outcome.status, stored_status);
        assert_eq!(outcome.task_status.as_deref(), Some("blocked"));
        assert_eq!(outcome.attempt_status.as_deref(), Some("blocked"));
        assert_eq!(
            scalar_string(
                &db,
                &format!(
                    "SELECT blocker_reason AS value FROM workspace_tasks WHERE task_id = '{task_id}'"
                )
            )
            .await?,
            "runtime stopped"
        );
        assert_eq!(
            scalar_string(
                &db,
                &format!(
                    "SELECT adjudication_reason AS value FROM workspace_task_attempts WHERE attempt_id = '{attempt_id}'"
                )
            )
            .await?,
            "runtime stopped"
        );
    }
    Ok(())
}

#[tokio::test]
async fn missing_attempt_rolls_back_the_entire_terminal_transaction() -> Result<(), Box<dyn Error>>
{
    let db = seeded_db(
        "rollback-workspace",
        "rollback-root",
        "rollback-task",
        "rollback-attempt",
    )
    .await?;
    db.execute(DbStatement::new(
        "UPDATE workspace_agent_runtime_correlations SET attempt_id = 'missing-attempt'",
    ))
    .await?;
    let service = PublicWorkspaceRuntimeTerminalService::new(&db, DbSqlFlavor::Sqlite);
    let result = service
        .record(
            &terminal_context("rollback-workspace"),
            "rollback-correlation",
            &terminal_input("complete", "rollback-event", json!({"content": "done"})),
        )
        .await;

    assert!(result.is_err());
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_agent_runtime_correlations"
        )
        .await?,
        "running"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_tasks WHERE task_id = 'rollback-task'"
        )
        .await?,
        "in_progress"
    );
    assert_eq!(
        scalar(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        0
    );
    assert_eq!(
        scalar(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_execution_terminals"
        )
        .await?,
        0
    );
    Ok(())
}

#[tokio::test]
async fn root_correlated_terminal_is_rejected_without_mutating_root_authority()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db("root-workspace", "root-goal", "root-task", "root-attempt").await?;
    db.execute(DbStatement::new(
        "UPDATE workspace_agent_runtime_correlations SET task_id = 'root-goal', attempt_id = NULL",
    ))
    .await?;
    let service = PublicWorkspaceRuntimeTerminalService::new(&db, DbSqlFlavor::Sqlite);

    let error = match service
        .record(
            &terminal_context("root-workspace"),
            "root-correlation",
            &terminal_input("complete", "root-event", json!({"content": "done"})),
        )
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("a Runtime callback structurally completed a goal root".into()),
    };

    assert_eq!(
        error.kind(),
        PublicWorkspaceRuntimeTerminalErrorKind::Conflict
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_tasks WHERE task_id = 'root-goal'"
        )
        .await?,
        "todo"
    );
    assert_eq!(
        scalar(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        0
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_agent_runtime_correlations"
        )
        .await?,
        "running"
    );
    Ok(())
}

#[tokio::test]
async fn opposite_terminal_replays_cannot_overwrite_the_first_terminal()
-> Result<(), Box<dyn Error>> {
    for (suffix, first, second, task_status, attempt_status) in [
        ("final-error", "complete", "error", "done", "completed"),
        ("error-final", "error", "complete", "blocked", "blocked"),
    ] {
        let workspace_id = format!("{suffix}-workspace");
        let root_id = format!("{suffix}-root");
        let task_id = format!("{suffix}-task");
        let attempt_id = format!("{suffix}-attempt");
        let correlation_id = format!("{suffix}-correlation");
        let db = seeded_db(&workspace_id, &root_id, &task_id, &attempt_id).await?;
        let service = PublicWorkspaceRuntimeTerminalService::new(&db, DbSqlFlavor::Sqlite);
        service
            .record(
                &terminal_context(&workspace_id),
                &correlation_id,
                &terminal_input(first, &format!("{suffix}-first"), json!({"first": true})),
            )
            .await?;

        let error = match service
            .record(
                &terminal_context(&workspace_id),
                &correlation_id,
                &terminal_input(second, &format!("{suffix}-second"), json!({"second": true})),
            )
            .await
        {
            Err(error) => error,
            Ok(_) => return Err("the opposite terminal overwrote durable authority".into()),
        };

        assert_eq!(
            error.kind(),
            PublicWorkspaceRuntimeTerminalErrorKind::Conflict
        );
        assert_eq!(
            scalar_string(
                &db,
                &format!("SELECT status AS value FROM workspace_tasks WHERE task_id = '{task_id}'")
            )
            .await?,
            task_status
        );
        assert_eq!(
            scalar_string(
                &db,
                &format!(
                    "SELECT status AS value FROM workspace_task_attempts WHERE attempt_id = '{attempt_id}'"
                )
            )
            .await?,
            attempt_status
        );
        assert_eq!(
            scalar(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
            1
        );
    }
    Ok(())
}

#[tokio::test]
async fn late_terminal_without_matching_outbox_cannot_overwrite_terminal_rows()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db("late-workspace", "late-root", "late-task", "late-attempt").await?;
    db.execute(DbStatement::new(
        "UPDATE workspace_tasks SET status = 'done' WHERE task_id = 'late-task'",
    ))
    .await?;
    db.execute(DbStatement::new(
        "UPDATE workspace_task_attempts SET status = 'completed' WHERE attempt_id = 'late-attempt'",
    ))
    .await?;
    let service = PublicWorkspaceRuntimeTerminalService::new(&db, DbSqlFlavor::Sqlite);

    let error = match service
        .record(
            &terminal_context("late-workspace"),
            "late-correlation",
            &terminal_input("error", "late-error", json!({"error_message": "late"})),
        )
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("a late terminal without its receipt rewrote terminal rows".into()),
    };

    assert_eq!(
        error.kind(),
        PublicWorkspaceRuntimeTerminalErrorKind::Conflict
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_tasks WHERE task_id = 'late-task'"
        )
        .await?,
        "done"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_task_attempts WHERE attempt_id = 'late-attempt'"
        )
        .await?,
        "completed"
    );
    assert_eq!(
        scalar(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        0
    );
    Ok(())
}

fn terminal_context(workspace_id: &str) -> PublicWorkspaceRuntimeTerminalContext {
    PublicWorkspaceRuntimeTerminalContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: workspace_id.to_string(),
    }
}

fn terminal_input(
    execution_status: &str,
    terminal_event_id: &str,
    report: serde_json::Value,
) -> PublicWorkspaceRuntimeTerminalInput {
    PublicWorkspaceRuntimeTerminalInput {
        execution_status: execution_status.to_string(),
        terminal_message_id: format!("message-{terminal_event_id}"),
        terminal_event_id: terminal_event_id.to_string(),
        report,
    }
}

async fn seeded_db(
    workspace_id: &str,
    root_id: &str,
    task_id: &str,
    attempt_id: &str,
) -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    let plan_id = format!("plan-{task_id}");
    let node_id = format!("node-{task_id}");
    let correlation_id = task_id.replace("task", "correlation");
    let provider_run_id = task_id.replace("task", "provider-run");
    let delivery_request_id = task_id.replace("task", "delivery");
    for statement in [
        format!(
            "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by, metadata_json) VALUES ('{workspace_id}', 'tenant-1', 'project-1', 'group-1', 'Terminal QA', 'user-1', '{{\"collaboration_mode\":\"autonomous\"}}')"
        ),
        format!(
            "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-{workspace_id}', 'tenant-1', 'project-1', '{workspace_id}', 'user-1', 'actor:user-1', 'owner')"
        ),
        format!(
            "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES ('{workspace_id}', 'tenant-1', 'project-1', 0)"
        ),
        format!(
            "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, agent_id, bot_uuid, participant_actor_id, display_name, config_json, is_active, status) VALUES ('binding-{workspace_id}', 'tenant-1', 'project-1', '{workspace_id}', 'agent-1', 'bot-1', 'actor:agent-1', 'Agent', '{{}}', 1, 'idle')"
        ),
        format!(
            "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, created_by, status, metadata_json) VALUES ('{root_id}', 'tenant-1', 'project-1', '{workspace_id}', 'Root', 'user-1', 'todo', '{{\"task_role\":\"goal_root\"}}')"
        ),
        format!(
            "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, created_by, status, metadata_json) VALUES ('{task_id}', 'tenant-1', 'project-1', '{workspace_id}', 'Execution', 'user-1', 'in_progress', '{{\"task_role\":\"execution_task\",\"root_goal_task_id\":\"{root_id}\",\"current_attempt_id\":\"{attempt_id}\"}}')"
        ),
        format!(
            "INSERT INTO workspace_task_attempts (attempt_id, tenant_id, project_id, workspace_id, task_id, root_goal_task_id, attempt_number, status) VALUES ('{attempt_id}', 'tenant-1', 'project-1', '{workspace_id}', '{task_id}', '{root_id}', 1, 'running')"
        ),
        format!(
            "INSERT INTO workspace_plans (plan_id, tenant_id, project_id, workspace_id, source_task_id, collaboration_definition_id, collaboration_definition_version, goal, status) VALUES ('{plan_id}', 'tenant-1', 'project-1', '{workspace_id}', '{task_id}', 'terminal-contract', 1, 'Converge execution', 'running')"
        ),
        format!(
            "INSERT INTO workspace_plan_nodes (node_id, tenant_id, project_id, workspace_id, plan_id, workspace_task_id, kind, title, sequence_number, current_attempt_id) VALUES ('{node_id}', 'tenant-1', 'project-1', '{workspace_id}', '{plan_id}', '{task_id}', 'execution', 'Execution', 0, '{attempt_id}')"
        ),
        format!(
            "INSERT INTO workspace_agent_runtime_correlations (correlation_id, tenant_id, project_id, workspace_id, task_id, attempt_id, plan_id, plan_node_id, conversation_id, delivery_request_id, provider_run_id, user_id, bcs_group_id, provider_id, provider_bot_ref, status) VALUES ('{correlation_id}', 'tenant-1', 'project-1', '{workspace_id}', '{task_id}', '{attempt_id}', '{plan_id}', '{node_id}', 'conversation-1', '{delivery_request_id}', '{provider_run_id}', 'user-1', 'group-1', 'memstack-workspace-agent-runtime', 'agent-1', 'running')"
        ),
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn scalar(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
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
