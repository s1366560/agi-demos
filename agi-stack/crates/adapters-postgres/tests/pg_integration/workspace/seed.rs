use super::*;

pub(super) async fn reset_and_seed_workspace_rows(pool: &PgPool) {
    for sql in [
        "DELETE FROM workspace_pipeline_stage_runs WHERE run_id IN (SELECT id FROM workspace_pipeline_runs WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo') OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_pipeline_runs WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_pipeline_contracts WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_plan_outbox WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_plan_events WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_plan_blackboard_entries WHERE plan_id = 'plan_p6_repo'",
        "DELETE FROM workspace_plan_nodes WHERE plan_id = 'plan_p6_repo'",
        "DELETE FROM workspace_plans WHERE id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
    ] {
        let _ = sqlx::query(sql).execute(pool).await;
    }

    for table in [
        "workspace_blackboard_outbox",
        "blackboard_files",
        "blackboard_replies",
        "blackboard_posts",
        "topology_edges",
        "topology_nodes",
        "workspace_task_session_attempts",
        "workspace_tasks",
        "workspace_members",
    ] {
        let sql = format!("DELETE FROM {table} WHERE workspace_id = 'ws_p6_repo'");
        let _ = sqlx::query(&sql).execute(pool).await;
    }
    sqlx::query("DELETE FROM workspaces WHERE id = 'ws_p6_repo'")
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM projects WHERE id = 'p_p6_repo'")
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM tenants WHERE id = 't_p6_repo'")
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM users WHERE id IN ('u_p6_owner', 'u_p6_viewer')")
        .execute(pool)
        .await
        .unwrap();

    sqlx::query(
        "INSERT INTO users (id, email) VALUES \
         ('u_p6_owner', 'owner-p6@example.com'), \
         ('u_p6_viewer', 'viewer-p6@example.com') \
         ON CONFLICT DO NOTHING",
    )
    .execute(pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_p6_repo', 'P6') ON CONFLICT DO NOTHING")
        .execute(pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_p6_repo', 't_p6_repo', 'P6 project', 'u_p6_owner')",
    )
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) VALUES \
         ('u_p6_owner', 'p_p6_repo', 'owner'), \
         ('u_p6_viewer', 'p_p6_repo', 'viewer') \
         ON CONFLICT (user_id, project_id) DO UPDATE SET role = EXCLUDED.role",
    )
    .execute(pool)
    .await
    .unwrap();
}
