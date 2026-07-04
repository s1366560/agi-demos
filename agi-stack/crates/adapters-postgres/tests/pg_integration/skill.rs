use super::support::*;

#[tokio::test]
async fn skill_repository_roundtrips_against_shared_schema() {
    let Some(pool) = pool_or_skip("skill_repository_roundtrips_against_shared_schema").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    for sql in [
        "DELETE FROM skill_versions WHERE skill_id IN ('skill_pg_1', 'skill_pg_project')",
        "DELETE FROM skills WHERE id IN ('skill_pg_1', 'skill_pg_project') OR tenant_id = 't_skill_pg'",
        "DELETE FROM user_projects WHERE project_id = 'p_skill_pg' OR user_id LIKE 'u_skill_%'",
        "DELETE FROM projects WHERE id = 'p_skill_pg'",
        "DELETE FROM user_tenants WHERE tenant_id = 't_skill_pg' OR user_id LIKE 'u_skill_%'",
        "DELETE FROM tenants WHERE id = 't_skill_pg'",
        "DELETE FROM users WHERE id IN ('u_skill_admin', 'u_skill_member', 'u_skill_viewer')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    for (user_id, email) in [
        ("u_skill_admin", "skill-admin@x"),
        ("u_skill_member", "skill-member@x"),
        ("u_skill_viewer", "skill-viewer@x"),
    ] {
        sqlx::query("INSERT INTO users (id, email) VALUES ($1, $2)")
            .bind(user_id)
            .bind(email)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_skill_pg', 'Skill T')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_skill_admin', 'u_skill_admin', 't_skill_pg', 'admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_skill_pg', 't_skill_pg', 'Skill P', 'u_skill_admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    for (user_id, role) in [("u_skill_member", "member"), ("u_skill_viewer", "viewer")] {
        sqlx::query("INSERT INTO user_projects (user_id, project_id, role) VALUES ($1, $2, $3)")
            .bind(user_id)
            .bind("p_skill_pg")
            .bind(role)
            .execute(&pool)
            .await
            .unwrap();
    }

    let repo = PgSkillRepository::new(pool.clone());
    assert_eq!(
        repo.first_tenant_for_user("u_skill_admin").await.unwrap(),
        Some("t_skill_pg".to_string())
    );
    assert!(repo
        .user_has_tenant_access("u_skill_admin", "t_skill_pg")
        .await
        .unwrap());
    assert!(repo
        .user_is_tenant_admin("u_skill_admin", "t_skill_pg")
        .await
        .unwrap());
    assert!(repo
        .user_can_access_project(
            "u_skill_member",
            "t_skill_pg",
            "p_skill_pg",
            SkillProjectAccess::Write,
        )
        .await
        .unwrap());
    assert!(!repo
        .user_can_access_project(
            "u_skill_viewer",
            "t_skill_pg",
            "p_skill_pg",
            SkillProjectAccess::Write,
        )
        .await
        .unwrap());
    assert!(repo
        .user_can_access_project(
            "u_skill_viewer",
            "t_skill_pg",
            "p_skill_pg",
            SkillProjectAccess::Read,
        )
        .await
        .unwrap());

    let created_at = Utc.with_ymd_and_hms(2026, 2, 3, 4, 5, 6).unwrap();
    let skill = SkillRecord {
        id: "skill_pg_1".to_string(),
        tenant_id: "t_skill_pg".to_string(),
        project_id: None,
        name: "code-review".to_string(),
        description: "Review code changes".to_string(),
        tools: vec!["read_file".to_string()],
        status: "active".to_string(),
        metadata_json: Some(json!({ "agentskills": { "license": "MIT" } })),
        created_at,
        updated_at: Some(created_at),
        scope: "tenant".to_string(),
        is_system_skill: false,
        full_content: Some("---\nname: code-review\n---\nReview code changes.".to_string()),
        resource_files: json!({ "README.md": "resource details" }),
        license: Some("MIT".to_string()),
        compatibility: Some("codex>=1".to_string()),
        allowed_tools_raw: Some("Read Grep".to_string()),
        spec_version: "1.0".to_string(),
        current_version: 0,
        version_label: Some("draft".to_string()),
    };

    let created = repo.create_skill(&skill).await.unwrap();
    assert_eq!(created.tools, vec!["read_file"]);
    assert_eq!(created.resource_files["README.md"], "resource details");

    let fetched = repo
        .get_skill("skill_pg_1")
        .await
        .unwrap()
        .expect("skill present");
    assert_eq!(fetched.name, "code-review");
    assert_eq!(fetched.tools, vec!["read_file"]);
    assert_eq!(fetched.license.as_deref(), Some("MIT"));

    let found = repo
        .find_skill("t_skill_pg", "code-review", "tenant", None)
        .await
        .unwrap()
        .expect("skill found by natural key");
    assert_eq!(found.id, "skill_pg_1");

    let project_skill = SkillRecord {
        id: "skill_pg_project".to_string(),
        project_id: Some("p_skill_pg".to_string()),
        name: "project-helper".to_string(),
        description: "Project scoped helper".to_string(),
        scope: "project".to_string(),
        full_content: Some("Project helper".to_string()),
        ..skill.clone()
    };
    repo.create_skill(&project_skill).await.unwrap();

    let tenant_list = repo
        .list_for_tenant("t_skill_pg", Some("active"), Some("tenant"), None, 10, 0)
        .await
        .unwrap();
    assert_eq!(tenant_list.len(), 1);
    assert_eq!(tenant_list[0].id, "skill_pg_1");

    let project_visible = repo
        .list_for_tenant("t_skill_pg", None, None, Some("p_skill_pg"), 10, 0)
        .await
        .unwrap();
    assert!(project_visible
        .iter()
        .any(|record| record.id == "skill_pg_1"));
    assert!(project_visible
        .iter()
        .any(|record| record.id == "skill_pg_project"));

    let updated_at = Utc.with_ymd_and_hms(2026, 2, 3, 5, 5, 6).unwrap();
    let updated = SkillUpdateRecord {
        description: Some("Review code and tests".to_string()),
        tools: Some(vec!["read_file".to_string(), "grep".to_string()]),
        full_content: Some(Some("Updated skill content".to_string())),
        current_version: Some(1),
        version_label: Some(Some("v1".to_string())),
        ..Default::default()
    }
    .apply_to(fetched, updated_at);
    let updated = repo.update_skill(&updated).await.unwrap();
    assert_eq!(updated.description, "Review code and tests");
    assert_eq!(updated.tools, vec!["read_file", "grep"]);
    assert_eq!(updated.current_version, 1);
    assert_eq!(updated.updated_at, Some(updated_at));

    let version = SkillVersionRecord {
        id: "skillver_pg_1".to_string(),
        skill_id: "skill_pg_1".to_string(),
        version_number: 1,
        version_label: Some("v1".to_string()),
        skill_md_content: "Updated skill content".to_string(),
        resource_files: json!({ "README.md": "v1 resource details" }),
        change_summary: Some("Manual content update".to_string()),
        created_by: "agent".to_string(),
        created_at: updated_at,
    };
    repo.create_version(&version).await.unwrap();
    assert_eq!(repo.max_version_number("skill_pg_1").await.unwrap(), 1);
    assert_eq!(repo.count_versions("skill_pg_1").await.unwrap(), 1);
    let versions = repo.list_versions("skill_pg_1", 10, 0).await.unwrap();
    assert_eq!(versions.len(), 1);
    assert_eq!(versions[0].version_label.as_deref(), Some("v1"));
    let fetched_version = repo
        .get_version("skill_pg_1", 1)
        .await
        .unwrap()
        .expect("version present");
    assert_eq!(fetched_version.skill_md_content, "Updated skill content");
    assert_eq!(
        fetched_version.resource_files["README.md"],
        "v1 resource details"
    );
    let latest_version = repo
        .get_latest_version("skill_pg_1")
        .await
        .unwrap()
        .expect("latest version present");
    assert_eq!(latest_version.version_number, 1);
    assert_eq!(latest_version.skill_md_content, "Updated skill content");

    assert!(repo.delete_skill("skill_pg_project").await.unwrap());
    assert!(repo.delete_skill("skill_pg_1").await.unwrap());
    sqlx::query("DELETE FROM skill_versions WHERE skill_id IN ('skill_pg_1', 'skill_pg_project')")
        .execute(&pool)
        .await
        .unwrap();
    assert!(repo.get_skill("skill_pg_1").await.unwrap().is_none());
}

#[tokio::test]
async fn skill_plugin_config_roundtrips_against_shared_schema() {
    let Some(pool) = pool_or_skip("skill_plugin_config_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    for sql in [
        "DELETE FROM plugin_configs WHERE tenant_id = 't_skill_plugin_cfg'",
        "DELETE FROM tenants WHERE id = 't_skill_plugin_cfg'",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_skill_plugin_cfg', 'Skill Plugin')")
        .execute(&pool)
        .await
        .unwrap();

    let repo = PgSkillRepository::new(pool.clone());
    assert!(repo
        .get_plugin_config("t_skill_plugin_cfg", "skill_evolution")
        .await
        .unwrap()
        .is_none());

    let created = repo
        .upsert_plugin_config(
            "plugin_cfg_1",
            "t_skill_plugin_cfg",
            "skill_evolution",
            &json!({
                "enabled": true,
                "min_sessions_per_skill": 5,
                "publish_mode": "review"
            }),
        )
        .await
        .unwrap();
    assert_eq!(created.id, "plugin_cfg_1");
    assert_eq!(created.config["publish_mode"], "review");

    let fetched = repo
        .get_plugin_config("t_skill_plugin_cfg", "skill_evolution")
        .await
        .unwrap()
        .expect("plugin config present");
    assert_eq!(fetched.tenant_id, "t_skill_plugin_cfg");
    assert_eq!(fetched.config["min_sessions_per_skill"], 5);

    let updated = repo
        .upsert_plugin_config(
            "plugin_cfg_new_id",
            "t_skill_plugin_cfg",
            "skill_evolution",
            &json!({
                "enabled": false,
                "min_sessions_per_skill": 7,
                "publish_mode": "direct"
            }),
        )
        .await
        .unwrap();
    assert_eq!(updated.id, "plugin_cfg_1");
    assert_eq!(updated.config["enabled"], false);
    assert_eq!(updated.config["publish_mode"], "direct");

    sqlx::query("DELETE FROM plugin_configs WHERE tenant_id = 't_skill_plugin_cfg'")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM tenants WHERE id = 't_skill_plugin_cfg'")
        .execute(&pool)
        .await
        .unwrap();
}

#[tokio::test]
async fn skill_evolution_overview_queries_shared_schema() {
    let Some(pool) = pool_or_skip("skill_evolution_overview_queries_shared_schema").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    for sql in [
        "DELETE FROM skill_evolution_jobs WHERE tenant_id = 't_skill_evo'",
        "DELETE FROM skill_evolution_sessions WHERE tenant_id = 't_skill_evo'",
        "DELETE FROM skills WHERE tenant_id = 't_skill_evo'",
        "DELETE FROM user_projects WHERE project_id IN ('p_skill_evo', 'p_skill_evo_other')",
        "DELETE FROM projects WHERE id IN ('p_skill_evo', 'p_skill_evo_other')",
        "DELETE FROM user_tenants WHERE tenant_id = 't_skill_evo'",
        "DELETE FROM tenants WHERE id = 't_skill_evo'",
        "DELETE FROM users WHERE id = 'u_skill_evo'",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    sqlx::query("INSERT INTO users (id, email) VALUES ('u_skill_evo', 'evo@example.com')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_skill_evo', 'Skill Evolution')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_skill_evo', 'u_skill_evo', 't_skill_evo', 'admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) VALUES \
         ('p_skill_evo', 't_skill_evo', 'Visible', 'u_skill_evo'), \
         ('p_skill_evo_other', 't_skill_evo', 'Hidden', 'u_skill_evo')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ('u_skill_evo', 'p_skill_evo', 'member')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO skills \
         (id, tenant_id, project_id, name, description, tools, status, created_at, scope, is_system_skill) \
         VALUES \
         ('skill_evo_project', 't_skill_evo', 'p_skill_evo', 'code-review', 'Review code', '[\"read_file\"]'::json, 'active', '2026-01-02T03:00:00Z'::timestamptz, 'project', false), \
         ('skill_evo_tenant', 't_skill_evo', NULL, 'review', 'Review tenant work', '[\"read_file\"]'::json, 'active', '2026-01-02T03:00:00Z'::timestamptz, 'tenant', false)",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO skill_evolution_sessions \
         (id, skill_name, tenant_id, project_id, conversation_id, user_query, summary, judge_scores, overall_score, success, execution_time_ms, tool_call_count, processed, created_at) \
         VALUES \
         ('sess_skill_evo_tenant', 'review', 't_skill_evo', NULL, 'conv-tenant', 'tenant query', 'tenant summary', '{\"quality\":0.9}'::json, 0.9, true, 100, 2, true, '2026-01-02T03:05:00Z'::timestamptz), \
         ('sess_skill_evo_project', 'code-review', 't_skill_evo', 'p_skill_evo', 'conv-project', 'project query', NULL, NULL, NULL, false, 200, 3, false, '2026-01-02T03:06:00Z'::timestamptz), \
         ('sess_skill_evo_no_skill', '__no_skill__', 't_skill_evo', 'p_skill_evo', 'conv-none', 'no skill query', NULL, NULL, NULL, false, 50, 0, false, '2026-01-02T03:07:00Z'::timestamptz), \
         ('sess_skill_evo_hidden', 'code-review', 't_skill_evo', 'p_skill_evo_other', 'conv-hidden', 'hidden query', NULL, NULL, NULL, false, 500, 4, false, '2026-01-02T03:08:00Z'::timestamptz)",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO skill_evolution_jobs \
         (id, skill_name, tenant_id, project_id, action, candidate_content, rationale, session_ids, status, skill_version_id, created_at, applied_at) \
         VALUES \
         ('job_skill_evo_project', 'code-review', 't_skill_evo', 'p_skill_evo', 'update', 'candidate', 'rationale', '[\"sess_skill_evo_project\"]'::json, 'pending_review', NULL, '2026-01-02T03:09:00Z'::timestamptz, NULL), \
         ('job_skill_evo_tenant', 'review', 't_skill_evo', NULL, 'update', 'candidate', 'rationale', '[\"sess_skill_evo_tenant\"]'::json, 'applied', 'version-1', '2026-01-02T03:10:00Z'::timestamptz, '2026-01-02T03:11:00Z'::timestamptz), \
         ('job_skill_evo_hidden', 'code-review', 't_skill_evo', 'p_skill_evo_other', 'update', 'hidden', 'hidden', '[\"sess_skill_evo_hidden\"]'::json, 'pending_review', NULL, '2026-01-02T03:12:00Z'::timestamptz, NULL)",
    )
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgSkillEvolutionRepository::new(pool.clone());
    let project_ids = repo
        .accessible_project_ids("u_skill_evo", "t_skill_evo")
        .await
        .unwrap();
    assert_eq!(project_ids, vec!["p_skill_evo".to_string()]);

    let stats = repo
        .overview_stats("t_skill_evo", &project_ids)
        .await
        .unwrap();
    assert_eq!(stats.total_sessions, 3);
    assert_eq!(stats.skill_sessions, 2);
    assert_eq!(stats.no_skill_sessions, 1);
    assert_eq!(stats.unprocessed_sessions, 1);
    assert_eq!(stats.processed_sessions, 1);
    assert_eq!(stats.scored_sessions, 1);
    assert_eq!(stats.successful_sessions, 1);
    assert!((stats.avg_score.unwrap() - 0.9).abs() < 0.000_001);
    assert_eq!(stats.total_jobs, 2);
    assert_eq!(stats.pending_jobs, 1);
    assert_eq!(stats.applied_jobs, 1);

    let summaries = repo
        .skill_session_summaries("t_skill_evo", &project_ids, 10)
        .await
        .unwrap();
    let project_summary = summaries
        .iter()
        .find(|summary| summary.skill_name == "code-review")
        .expect("project skill summary");
    assert_eq!(
        project_summary.skill_id.as_deref(),
        Some("skill_evo_project")
    );
    assert_eq!(project_summary.project_id.as_deref(), Some("p_skill_evo"));
    assert_eq!(project_summary.session_count, 1);
    assert_eq!(project_summary.job_count, 1);
    assert_eq!(project_summary.pending_job_count, 1);
    let tenant_summary = summaries
        .iter()
        .find(|summary| summary.skill_name == "review")
        .expect("tenant skill summary");
    assert_eq!(tenant_summary.skill_id.as_deref(), Some("skill_evo_tenant"));
    assert_eq!(tenant_summary.job_count, 1);
    assert_eq!(tenant_summary.pending_job_count, 0);

    let sessions = repo
        .list_recent_sessions("t_skill_evo", &project_ids, 10)
        .await
        .unwrap();
    assert_eq!(sessions.len(), 3);
    assert!(sessions
        .iter()
        .all(|session| session.project_id.as_deref() != Some("p_skill_evo_other")));

    let jobs = repo
        .list_jobs("t_skill_evo", &project_ids, 10)
        .await
        .unwrap();
    assert_eq!(jobs.len(), 2);
    assert!(jobs.iter().any(|job| job.id == "job_skill_evo_project"
        && job.status == "pending_review"
        && job.session_ids == vec!["sess_skill_evo_project".to_string()]));
    assert!(jobs
        .iter()
        .all(|job| job.project_id.as_deref() != Some("p_skill_evo_other")));

    let project_jobs = repo
        .list_jobs_for_skill("t_skill_evo", "code-review", Some("p_skill_evo"), 10)
        .await
        .unwrap();
    assert_eq!(project_jobs.len(), 1);
    assert_eq!(project_jobs[0].id, "job_skill_evo_project");
    let tenant_jobs = repo
        .list_jobs_for_skill("t_skill_evo", "review", None, 10)
        .await
        .unwrap();
    assert_eq!(tenant_jobs.len(), 1);
    assert_eq!(tenant_jobs[0].id, "job_skill_evo_tenant");
    let project_session_count = repo
        .count_sessions_by_skill("t_skill_evo", "code-review", Some("p_skill_evo"))
        .await
        .unwrap();
    assert_eq!(project_session_count, 1);
    let tenant_session_count = repo
        .count_sessions_by_skill("t_skill_evo", "review", None)
        .await
        .unwrap();
    assert_eq!(tenant_session_count, 1);

    let pending_job = repo
        .get_job_for_tenant("t_skill_evo", "job_skill_evo_project")
        .await
        .unwrap()
        .expect("pending project job");
    assert_eq!(pending_job.tenant_id, "t_skill_evo");
    assert_eq!(pending_job.status, "pending_review");
    let applied_job = repo
        .update_job_status(
            "t_skill_evo",
            "job_skill_evo_project",
            "applied",
            Some("version-rust"),
        )
        .await
        .unwrap()
        .expect("applied project job");
    assert_eq!(applied_job.status, "applied");
    assert_eq!(
        applied_job.skill_version_id.as_deref(),
        Some("version-rust")
    );
    assert!(applied_job.applied_at.is_some());
    let rejected_job = repo
        .update_job_status("t_skill_evo", "job_skill_evo_hidden", "rejected", None)
        .await
        .unwrap()
        .expect("rejected hidden job");
    assert_eq!(rejected_job.status, "rejected");
    assert!(rejected_job.applied_at.is_none());
    assert!(repo
        .get_job_for_tenant("other-tenant", "job_skill_evo_project")
        .await
        .unwrap()
        .is_none());

    for sql in [
        "DELETE FROM skill_evolution_jobs WHERE tenant_id = 't_skill_evo'",
        "DELETE FROM skill_evolution_sessions WHERE tenant_id = 't_skill_evo'",
        "DELETE FROM skills WHERE tenant_id = 't_skill_evo'",
        "DELETE FROM user_projects WHERE project_id IN ('p_skill_evo', 'p_skill_evo_other')",
        "DELETE FROM projects WHERE id IN ('p_skill_evo', 'p_skill_evo_other')",
        "DELETE FROM user_tenants WHERE tenant_id = 't_skill_evo'",
        "DELETE FROM tenants WHERE id = 't_skill_evo'",
        "DELETE FROM users WHERE id = 'u_skill_evo'",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }
}
