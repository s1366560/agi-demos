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
        "workspace_agents",
        "workspace_members",
    ] {
        let sql = format!("DELETE FROM {table} WHERE workspace_id = 'ws_p6_repo'");
        let _ = sqlx::query(&sql).execute(pool).await;
    }
    sqlx::query("DELETE FROM workspaces WHERE id = 'ws_p6_repo'")
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM agent_definitions WHERE id IN ('agent_p6_worker', 'agent_p6_leader')")
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM user_projects WHERE project_id = 'p_p6_repo'")
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
        "INSERT INTO users \
             (id, email, hashed_password, is_active, is_superuser, profile) VALUES \
         ('u_p6_owner', 'owner-p6@example.com', 'integration-test-only', true, false, '{}'::json), \
         ('u_p6_viewer', 'viewer-p6@example.com', 'integration-test-only', true, false, '{}'::json) \
         ON CONFLICT DO NOTHING",
    )
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants \
             (id, name, slug, owner_id, plan, max_projects, max_users, max_storage) \
         VALUES \
             ('t_p6_repo', 'P6', 'p6-repo-integration', 'u_p6_owner', 'free', 10, 5, 1073741824) \
         ON CONFLICT DO NOTHING",
    )
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects \
             (id, tenant_id, name, owner_id, memory_rules, graph_config, sandbox_type, \
              sandbox_config, is_public, agent_conversation_mode) \
         VALUES \
             ('p_p6_repo', 't_p6_repo', 'P6 project', 'u_p6_owner', '{}'::json, '{}'::json, \
              'cloud', '{}'::json, false, 'single_agent')",
    )
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO agent_definitions \
             (id, tenant_id, project_id, name, display_name, system_prompt, trigger_examples, \
              trigger_keywords, model, persona_files, allowed_tools, allowed_skills, \
              allowed_mcp_servers, max_tokens, temperature, max_iterations, can_spawn, \
              max_spawn_depth, agent_to_agent_enabled, discoverable, source, enabled, max_retries, \
              fallback_models, total_invocations, avg_execution_time_ms, success_rate) VALUES \
         ('agent_p6_worker', 't_p6_repo', 'p_p6_repo', 'p6-worker', 'P6 Worker', 'Work', \
          '[]'::json, '[]'::json, 'inherit', '[]'::json, '[]'::json, '[]'::json, '[]'::json, \
          4096, 0.7, 10, false, 1, false, true, 'custom', true, 3, '[]'::json, 0, 0, 1), \
         ('agent_p6_leader', 't_p6_repo', 'p_p6_repo', 'p6-leader', 'P6 Leader', 'Lead', \
          '[]'::json, '[]'::json, 'inherit', '[]'::json, '[]'::json, '[]'::json, '[]'::json, \
          4096, 0.7, 10, false, 1, false, true, 'custom', true, 3, '[]'::json, 0, 0, 1)",
    )
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role, permissions) VALUES \
         ('up_p6_owner', 'u_p6_owner', 'p_p6_repo', 'owner', '{}'::json), \
         ('up_p6_viewer', 'u_p6_viewer', 'p_p6_repo', 'viewer', '{}'::json)",
    )
    .execute(pool)
    .await
    .unwrap();
}
