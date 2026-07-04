use super::support::*;

type SkillEvolutionRunStateRow = (
    String,
    String,
    i32,
    Option<String>,
    Option<serde_json::Value>,
);

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

    let unprocessed_project = repo
        .list_unprocessed_sessions(
            "t_skill_evo",
            Some("code-review"),
            Some("p_skill_evo"),
            true,
            1,
            10,
        )
        .await
        .unwrap();
    assert_eq!(unprocessed_project.len(), 1);
    assert_eq!(unprocessed_project[0].id, "sess_skill_evo_project");
    assert_eq!(unprocessed_project[0].skill_name, "code-review");
    assert!(!unprocessed_project[0].processed);

    let below_min_sessions = repo
        .list_unprocessed_sessions(
            "t_skill_evo",
            Some("code-review"),
            Some("p_skill_evo"),
            true,
            2,
            10,
        )
        .await
        .unwrap();
    assert!(below_min_sessions.is_empty());

    let summary_written = repo
        .update_session_summary(
            "sess_skill_evo_project",
            &serde_json::json!({
                "steps": [
                    {"step": 1, "action": "read diff", "tool": "read_file", "outcome": "success"}
                ],
                "final_response": "Reviewed the patch."
            }),
            "The agent reviewed the requested patch and produced actionable feedback.",
        )
        .await
        .unwrap();
    assert!(summary_written);

    let unscored_project = repo
        .list_unscored_sessions(
            "t_skill_evo",
            Some("code-review"),
            Some("p_skill_evo"),
            true,
            1,
            10,
        )
        .await
        .unwrap();
    assert_eq!(unscored_project.len(), 1);
    assert_eq!(unscored_project[0].id, "sess_skill_evo_project");
    assert!(unscored_project[0].processed);
    assert!(unscored_project[0].overall_score.is_none());
    assert_eq!(
        unscored_project[0]
            .trajectory
            .as_ref()
            .and_then(|value| value.get("final_response"))
            .and_then(serde_json::Value::as_str),
        Some("Reviewed the patch.")
    );

    let scores_written = repo
        .update_session_scores(
            "sess_skill_evo_project",
            &serde_json::json!({
                "task_completion": 0.9,
                "response_quality": 0.8,
                "efficiency": 0.7,
                "tool_usage": 0.8,
                "rationale": "Useful review"
            }),
            0.82,
        )
        .await
        .unwrap();
    assert!(scores_written);

    let groups = repo
        .scored_session_groups("t_skill_evo", Some("p_skill_evo"), true, 1, 0.8)
        .await
        .unwrap();
    assert_eq!(groups.len(), 1);
    assert_eq!(groups[0].skill_name, "code-review");
    assert_eq!(groups[0].project_id.as_deref(), Some("p_skill_evo"));
    assert_eq!(groups[0].session_count, 1);
    assert!((groups[0].avg_score - 0.82).abs() < 0.000_001);

    let scored_sessions = repo
        .list_scored_sessions_by_skill(
            "t_skill_evo",
            "code-review",
            Some("p_skill_evo"),
            true,
            Some(0.8),
            10,
        )
        .await
        .unwrap();
    assert_eq!(scored_sessions.len(), 1);
    assert_eq!(scored_sessions[0].id, "sess_skill_evo_project");
    assert!((scored_sessions[0].overall_score.unwrap() - 0.82).abs() < 0.000_001);

    let duplicate_job = repo
        .get_job_for_sessions(
            "t_skill_evo",
            "code-review",
            Some("p_skill_evo"),
            true,
            &["sess_skill_evo_project".to_string()],
            &["rejected"],
        )
        .await
        .unwrap()
        .expect("duplicate project job by exact session set");
    assert_eq!(duplicate_job.id, "job_skill_evo_project");
    assert!(repo
        .get_job_for_sessions(
            "t_skill_evo",
            "code-review",
            Some("p_skill_evo"),
            true,
            &["sess_skill_evo_project".to_string()],
            &["pending_review"],
        )
        .await
        .unwrap()
        .is_none());

    let inserted_job = repo
        .insert_job(&SkillEvolutionJobInsertRecord {
            id: "job_skill_evo_inserted".to_string(),
            tenant_id: "t_skill_evo".to_string(),
            project_id: Some("p_skill_evo".to_string()),
            skill_name: "code-review".to_string(),
            action: "skip".to_string(),
            status: "skipped".to_string(),
            rationale: Some("No change needed after Rust pipeline review.".to_string()),
            candidate_content: None,
            session_ids: vec!["sess_skill_evo_project".to_string()],
        })
        .await
        .unwrap();
    assert_eq!(inserted_job.id, "job_skill_evo_inserted");
    assert_eq!(inserted_job.status, "skipped");
    assert_eq!(
        inserted_job.session_ids,
        vec!["sess_skill_evo_project".to_string()]
    );
    assert!(inserted_job.created_at.timestamp() > 0);

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

#[tokio::test]
async fn skill_evolution_run_queue_coalesces_active_runs() {
    let Some(pool) = pool_or_skip("skill_evolution_run_queue_coalesces_active_runs").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    sqlx::query("DELETE FROM agistack_skill_evolution_runs WHERE tenant_id = 't_skill_evo_queue'")
        .execute(&pool)
        .await
        .unwrap();

    let repo = PgSkillEvolutionRepository::new(pool.clone());
    let first = repo
        .schedule_evolution_run(
            "run_skill_evo_queue_1",
            "t_skill_evo_queue",
            Some("p_skill_evo_queue"),
            Some("code-review"),
            "manual",
        )
        .await
        .unwrap();
    let duplicate = repo
        .schedule_evolution_run(
            "run_skill_evo_queue_2",
            "t_skill_evo_queue",
            Some("p_skill_evo_queue"),
            Some("code-review"),
            "manual",
        )
        .await
        .unwrap();
    let tenant_run = repo
        .schedule_evolution_run(
            "run_skill_evo_queue_3",
            "t_skill_evo_queue",
            None,
            None,
            "manual",
        )
        .await
        .unwrap();

    assert!(first);
    assert!(!duplicate);
    assert!(tenant_run);

    let count: (i64,) = sqlx::query_as(
        "SELECT count(*) FROM agistack_skill_evolution_runs \
         WHERE tenant_id = 't_skill_evo_queue'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(count.0, 2);

    sqlx::query(
        "UPDATE agistack_skill_evolution_runs \
         SET status = 'completed', updated_at = now() \
         WHERE id = 'run_skill_evo_queue_1'",
    )
    .execute(&pool)
    .await
    .unwrap();
    let after_completion = repo
        .schedule_evolution_run(
            "run_skill_evo_queue_4",
            "t_skill_evo_queue",
            Some("p_skill_evo_queue"),
            Some("code-review"),
            "manual",
        )
        .await
        .unwrap();
    assert!(after_completion);

    sqlx::query("DELETE FROM agistack_skill_evolution_runs WHERE tenant_id = 't_skill_evo_queue'")
        .execute(&pool)
        .await
        .unwrap();
}

#[tokio::test]
async fn skill_evolution_run_queue_claims_and_finishes_runs() {
    let Some(pool) = pool_or_skip("skill_evolution_run_queue_claims_and_finishes_runs").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    sqlx::query("DELETE FROM agistack_skill_evolution_runs WHERE tenant_id = 't_skill_evo_worker'")
        .execute(&pool)
        .await
        .unwrap();

    let repo = PgSkillEvolutionRepository::new(pool.clone());
    assert!(repo
        .schedule_evolution_run(
            "run_skill_evo_worker_1",
            "t_skill_evo_worker",
            Some("p_skill_evo_worker"),
            Some("code-review"),
            "manual",
        )
        .await
        .unwrap());
    assert!(repo
        .schedule_evolution_run(
            "run_skill_evo_worker_2",
            "t_skill_evo_worker",
            None,
            None,
            "manual",
        )
        .await
        .unwrap());

    let first = repo
        .claim_next_evolution_run("worker-a")
        .await
        .unwrap()
        .expect("first queued run should be claimed");
    assert_eq!(first.id, "run_skill_evo_worker_1");
    assert_eq!(first.status, "running");
    assert_eq!(first.attempts, 1);
    assert_eq!(first.worker_id.as_deref(), Some("worker-a"));
    assert!(first.started_at.is_some());
    assert!(repo
        .complete_evolution_run(
            &first.id,
            Some("worker-a"),
            &serde_json::json!({"jobs": 1, "skipped": false}),
        )
        .await
        .unwrap());

    let second = repo
        .claim_next_evolution_run("worker-b")
        .await
        .unwrap()
        .expect("second queued run should be claimed");
    assert_eq!(second.id, "run_skill_evo_worker_2");
    assert!(repo
        .fail_evolution_run(&second.id, Some("worker-b"), "llm provider unavailable")
        .await
        .unwrap());
    assert!(repo
        .claim_next_evolution_run("worker-c")
        .await
        .unwrap()
        .is_none());

    let rows: Vec<SkillEvolutionRunStateRow> = sqlx::query_as(
        "SELECT id, status, attempts, last_error, result_json \
             FROM agistack_skill_evolution_runs \
             WHERE tenant_id = 't_skill_evo_worker' \
             ORDER BY id ASC",
    )
    .fetch_all(&pool)
    .await
    .unwrap();
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].0, "run_skill_evo_worker_1");
    assert_eq!(rows[0].1, "completed");
    assert_eq!(rows[0].2, 1);
    assert_eq!(rows[0].4.as_ref().unwrap()["jobs"], serde_json::json!(1));
    assert_eq!(rows[1].0, "run_skill_evo_worker_2");
    assert_eq!(rows[1].1, "failed");
    assert_eq!(rows[1].3.as_deref(), Some("llm provider unavailable"));

    sqlx::query("DELETE FROM agistack_skill_evolution_runs WHERE tenant_id = 't_skill_evo_worker'")
        .execute(&pool)
        .await
        .unwrap();
}
