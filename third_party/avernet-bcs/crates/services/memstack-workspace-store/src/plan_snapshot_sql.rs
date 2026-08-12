//! Dialect-aware SQL builders for Workspace Plan snapshots.

use bcs_db_api::{DbSqlFlavor, DbStatement, DbStatementBuilder};

use crate::WorkspacePlanScope;

const PLAN_SELECT: &str = "SELECT plan_id, workspace_id, source_task_id, goal, goal_json, status, revision, metadata_json, created_at, updated_at, completed_at FROM workspace_plans";

pub(crate) fn access_check(
    flavor: DbSqlFlavor,
    scope: &WorkspacePlanScope,
    editor: bool,
) -> DbStatement {
    let mut statement = DbStatementBuilder::new(flavor)
        .push_static("SELECT p.workspace_id FROM workspace_profiles p WHERE p.tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND p.deleted_at IS NULL");
    if !scope.actor_is_superuser {
        statement = statement
            .push_static(
                " AND EXISTS (SELECT 1 FROM workspace_members m WHERE m.tenant_id = p.tenant_id AND m.project_id = p.project_id AND m.workspace_id = p.workspace_id AND m.user_id = ",
            )
            .bind(scope.actor_id.as_str());
        statement = if editor {
            statement.push_static(" AND m.role IN ('owner', 'editor'))")
        } else {
            statement.push_static(" AND m.role IN ('owner', 'editor', 'viewer'))")
        };
    }
    statement.build()
}

pub(crate) fn plan_history(flavor: DbSqlFlavor, scope: &WorkspacePlanScope) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(PLAN_SELECT)
        .push_static(" WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" ORDER BY created_at DESC, plan_id DESC")
        .build()
}

pub(crate) fn selected_plan(
    flavor: DbSqlFlavor,
    scope: &WorkspacePlanScope,
    plan_id: Option<&str>,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(PLAN_SELECT)
        .push_static(" WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND plan_id = ");
    append_selected_plan(builder, plan_id, scope).build()
}

pub(crate) fn nodes(
    flavor: DbSqlFlavor,
    scope: &WorkspacePlanScope,
    plan_id: Option<&str>,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT node_id, plan_id, workspace_task_id, parent_id, kind, title, description, intent, status, sequence_number, dependencies_json, acceptance_criteria_json, feature_checkpoint_json, handoff_package_json, recommended_capabilities_json, priority, progress_json, assignee_agent_id, current_attempt_id, timeout_deadline_at, metadata_json, created_at, updated_at, completed_at FROM workspace_plan_nodes WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND plan_id = ");
    append_selected_plan(builder, plan_id, scope)
        .push_static(" ORDER BY sequence_number, node_id")
        .build()
}

pub(crate) fn blackboard(
    flavor: DbSqlFlavor,
    scope: &WorkspacePlanScope,
    plan_id: Option<&str>,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT plan_id, key, value_json, created_by_actor_id, version, schema_ref, metadata_json FROM workspace_plan_blackboard_entries WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND plan_id = ");
    append_selected_plan(builder, plan_id, scope)
        .push_static(" ORDER BY key, version DESC")
        .build()
}

pub(crate) fn outbox(
    flavor: DbSqlFlavor,
    scope: &WorkspacePlanScope,
    plan_id: Option<&str>,
    limit: u64,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT outbox_id, aggregate_id, workspace_id, event_type, payload_json, status, attempt_count, max_attempts, lease_owner, lease_expires_at, last_error, next_attempt_at, dispatched_at, metadata_json, created_at, updated_at FROM workspace_outbox WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND aggregate_type = 'workspace_plan' AND aggregate_id = ");
    append_selected_plan(builder, plan_id, scope)
        .push_static(" ORDER BY created_at DESC, outbox_id DESC LIMIT ")
        .bind(i64::try_from(limit).unwrap_or(i64::MAX))
        .build()
}

pub(crate) fn events(
    flavor: DbSqlFlavor,
    scope: &WorkspacePlanScope,
    plan_id: Option<&str>,
    limit: u64,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT event_id, plan_id, workspace_id, node_id, attempt_id, event_type, source, actor_id, payload_json, created_at FROM workspace_plan_events WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND plan_id = ");
    append_selected_plan(builder, plan_id, scope)
        .push_static(" ORDER BY created_at DESC, event_id DESC LIMIT ")
        .bind(i64::try_from(limit).unwrap_or(i64::MAX))
        .build()
}

pub(crate) fn pipeline_runs(
    flavor: DbSqlFlavor,
    scope: &WorkspacePlanScope,
    plan_id: Option<&str>,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT run_id, provider, status, reason, node_id, attempt_id, commit_ref, metadata_json, started_at, completed_at, created_at FROM workspace_pipeline_runs WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND plan_id = ");
    append_selected_plan(builder, plan_id, scope)
        .push_static(" ORDER BY created_at DESC, run_id DESC LIMIT 20")
        .build()
}

fn append_selected_plan(
    builder: DbStatementBuilder,
    plan_id: Option<&str>,
    scope: &WorkspacePlanScope,
) -> DbStatementBuilder {
    if let Some(plan_id) = plan_id {
        return builder.bind(plan_id);
    }
    builder
        .push_static("(SELECT plan_id FROM workspace_plans WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" ORDER BY created_at DESC, plan_id DESC LIMIT 1)")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn postgres_snapshot_uses_numbered_parameters_and_scope() {
        let statement = nodes(DbSqlFlavor::Postgres, &scope(), None);
        assert!(statement.sql().contains("$1"));
        assert!(statement.sql().contains("tenant_id"));
        assert!(statement.sql().contains("project_id"));
        assert!(statement.sql().contains("workspace_id"));
        assert!(!statement.sql().contains('?'));
    }

    fn scope() -> WorkspacePlanScope {
        WorkspacePlanScope {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
            actor_id: "user-1".to_string(),
            actor_is_superuser: false,
        }
    }
}
