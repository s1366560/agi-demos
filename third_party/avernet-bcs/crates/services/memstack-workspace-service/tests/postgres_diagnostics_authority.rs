use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicWorkspaceExecutionDiagnosticsInput,
    PublicWorkspaceExecutionDiagnosticsService, WorkspaceCreationService,
};
use serde_json::json;

const TENANT_ID: &str = "tenant-diagnostics-pg-contract";
const PROJECT_ID: &str = "project-diagnostics-pg-contract";
const WORKSPACE_ID: &str = "workspace-diagnostics-pg-contract";
const GROUP_ID: &str = "group-diagnostics-pg-contract";
const USER_ID: &str = "actor-diagnostics-pg-contract";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_diagnostics_projects_scoped_task_plan_and_outbox_authority()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    seed_diagnostics(&db).await?;

    let diagnostics = PublicWorkspaceExecutionDiagnosticsService::new(&db, DbSqlFlavor::Postgres)
        .read(&PublicWorkspaceExecutionDiagnosticsInput {
            tenant_id: TENANT_ID.to_string(),
            project_id: PROJECT_ID.to_string(),
            workspace_id: WORKSPACE_ID.to_string(),
            user_id: USER_ID.to_string(),
            task_limit: 100,
            tool_limit_per_conversation: 100,
        })
        .await?;

    assert_eq!(diagnostics.workspace_id, WORKSPACE_ID);
    assert_eq!(diagnostics.task_status_counts.get("reported"), Some(&1));
    assert_eq!(
        diagnostics
            .attempt_status_counts
            .get("awaiting_leader_adjudication"),
        Some(&1)
    );
    assert_eq!(diagnostics.pending_adjudications.len(), 1);
    assert_eq!(diagnostics.evidence_gaps.len(), 1);
    assert_eq!(diagnostics.active_attempts.len(), 1);
    assert_eq!(diagnostics.retry_queue.len(), 1);
    assert!(diagnostics.blockers.iter().any(|row| {
        row.get("type").and_then(serde_json::Value::as_str) == Some("outbox_dead_letter")
    }));
    assert_eq!(
        diagnostics.controller_state["plan_id"],
        "plan-diagnostics-pg"
    );
    assert_eq!(diagnostics.completion_gate["ready"], false);
    cleanup(&db).await?;
    Ok(())
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn seed_project_membership(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-diagnostics-pg-contract', 'project-diagnostics-pg-contract', 'actor-diagnostics-pg-contract', 'actor-diagnostics-pg-contract', 'membership-diagnostics-pg-contract', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
    ))
    .await?;
    Ok(())
}

async fn create_workspace(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    WorkspaceCreationService::new(db, DbSqlFlavor::Postgres)
        .create(&CreateWorkspaceInput {
            scope: CreateWorkspaceScopeInput {
                tenant_id: TENANT_ID.to_string(),
                project_id: PROJECT_ID.to_string(),
                workspace_id: WORKSPACE_ID.to_string(),
                group_id: GROUP_ID.to_string(),
            },
            owner: CreateWorkspaceOwnerInput {
                member_id: "member-diagnostics-pg-contract".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL Diagnostics Workspace".to_string(),
                description: Some("Diagnostics projection contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "diagnostics-pg-workspace-create".to_string(),
        })
        .await?;
    Ok(())
}

async fn seed_diagnostics(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for statement in [
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, created_by, assignee_agent_id, status, priority, metadata_json) VALUES ('task-diagnostics-pg', 'tenant-diagnostics-pg-contract', 'project-diagnostics-pg-contract', 'workspace-diagnostics-pg-contract', 'Reported task', 'actor-diagnostics-pg-contract', 'agent-diagnostics-pg', 'reported', 1, '{\"current_attempt_id\":\"attempt-diagnostics-pg\"}'::jsonb)",
        "INSERT INTO workspace_task_attempts (attempt_id, tenant_id, project_id, workspace_id, task_id, root_goal_task_id, attempt_number, status, conversation_id, worker_agent_id, leader_agent_id, candidate_summary, candidate_artifacts_json, candidate_verifications_json) VALUES ('attempt-diagnostics-pg', 'tenant-diagnostics-pg-contract', 'project-diagnostics-pg-contract', 'workspace-diagnostics-pg-contract', 'task-diagnostics-pg', 'task-diagnostics-pg', 1, 'awaiting_leader_adjudication', 'conversation-diagnostics-pg', 'agent-diagnostics-pg', 'leader-diagnostics-pg', 'Candidate report', '[]'::jsonb, '[]'::jsonb)",
        "INSERT INTO workspace_plans (plan_id, tenant_id, project_id, workspace_id, collaboration_definition_id, collaboration_definition_version, goal, goal_json, status, revision, created_by_actor_id, metadata_json) VALUES ('plan-diagnostics-pg', 'tenant-diagnostics-pg-contract', 'project-diagnostics-pg-contract', 'workspace-diagnostics-pg-contract', 'definition-diagnostics-pg', 1, 'Finish migration', '{}'::jsonb, 'active', 1, 'actor-diagnostics-pg-contract', '{}'::jsonb)",
        "INSERT INTO workspace_plan_nodes (node_id, tenant_id, project_id, workspace_id, plan_id, workspace_task_id, kind, title, status, sequence_number, dependencies_json, inputs_schema_json, outputs_schema_json, acceptance_criteria_json, recommended_capabilities_json, priority, progress_json, max_attempts, metadata_json) VALUES ('node-diagnostics-pg', 'tenant-diagnostics-pg-contract', 'project-diagnostics-pg-contract', 'workspace-diagnostics-pg-contract', 'plan-diagnostics-pg', 'task-diagnostics-pg', 'task', 'Reported task', 'awaiting_review', 0, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, 1, '{}'::jsonb, 3, '{}'::jsonb)",
        "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, idempotency_key, status, attempt_count, max_attempts, last_error) VALUES ('outbox-diagnostics-pg', 'tenant-diagnostics-pg-contract', 'project-diagnostics-pg-contract', 'workspace-diagnostics-pg-contract', 'workspace_plan', 'plan-diagnostics-pg', 'workspace_plan_updated', 'workspace.events', 90, '{}'::jsonb, '{}'::jsonb, 'diagnostics-pg-dead-letter', 'dead_letter', 10, 10, 'delivery failed')",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for statement in [
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_group_participants WHERE group_id = ")
            .bind(GROUP_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_groups WHERE group_id = ")
            .bind(GROUP_ID)
            .build(),
        DbStatement::new(
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-diagnostics-pg-contract'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}
