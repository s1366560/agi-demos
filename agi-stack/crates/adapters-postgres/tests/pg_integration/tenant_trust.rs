use super::support::*;

#[tokio::test]
async fn tenant_skill_config_repository_roundtrips_against_shared_schema() {
    let Some(pool) =
        pool_or_skip("tenant_skill_config_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    for sql in [
        "DELETE FROM tenant_skill_configs WHERE tenant_id IN ('t_tenant_skill_cfg', 't_tenant_skill_other')",
        "DELETE FROM skills WHERE id IN ('skill_cfg_override', 'skill_cfg_other')",
        "DELETE FROM user_tenants WHERE tenant_id IN ('t_tenant_skill_cfg', 't_tenant_skill_other') OR user_id LIKE 'u_tenant_skill_%'",
        "DELETE FROM tenants WHERE id IN ('t_tenant_skill_cfg', 't_tenant_skill_other')",
        "DELETE FROM users WHERE id IN ('u_tenant_skill_admin', 'u_tenant_skill_other')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    sqlx::query(
        "INSERT INTO users (id, email) VALUES \
         ('u_tenant_skill_admin', 'tenant-skill-admin@x'), \
         ('u_tenant_skill_other', 'tenant-skill-other@x')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES \
         ('t_tenant_skill_cfg', 'Tenant Skill Config'), \
         ('t_tenant_skill_other', 'Other Tenant')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) VALUES \
         ('ut_tenant_skill_admin', 'u_tenant_skill_admin', 't_tenant_skill_cfg', 'admin'), \
         ('ut_tenant_skill_other', 'u_tenant_skill_other', 't_tenant_skill_other', 'admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO skills (id, tenant_id, name, description) VALUES \
         ('skill_cfg_override', 't_tenant_skill_cfg', 'Tenant override', 'override skill'), \
         ('skill_cfg_other', 't_tenant_skill_other', 'Other override', 'wrong tenant skill')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgTenantSkillConfigRepository::new(pool.clone());
    assert_eq!(
        repo.first_tenant_for_user("u_tenant_skill_admin")
            .await
            .unwrap(),
        Some("t_tenant_skill_cfg".to_string())
    );
    assert!(repo
        .user_has_tenant_access("u_tenant_skill_admin", "t_tenant_skill_cfg")
        .await
        .unwrap());
    assert!(!repo
        .user_has_tenant_access("u_tenant_skill_admin", "t_tenant_skill_other")
        .await
        .unwrap());
    assert!(repo
        .user_is_tenant_admin("u_tenant_skill_admin", "t_tenant_skill_cfg")
        .await
        .unwrap());
    assert_eq!(
        repo.override_skill_belongs_to_tenant("skill_cfg_override", "t_tenant_skill_cfg")
            .await
            .unwrap(),
        Some(true)
    );
    assert_eq!(
        repo.override_skill_belongs_to_tenant("skill_cfg_other", "t_tenant_skill_cfg")
            .await
            .unwrap(),
        Some(false)
    );
    assert_eq!(
        repo.override_skill_belongs_to_tenant("skill_cfg_missing", "t_tenant_skill_cfg")
            .await
            .unwrap(),
        None
    );

    let created_at = ts(2026, 2, 4, 5, 6, 7);
    let record = TenantSkillConfigRecord {
        id: "tenant_skill_cfg_1".to_string(),
        tenant_id: "t_tenant_skill_cfg".to_string(),
        system_skill_name: "code-review".to_string(),
        action: "disable".to_string(),
        override_skill_id: None,
        created_at,
        updated_at: None,
    };
    let created = repo.create(&record).await.unwrap();
    assert_eq!(created.action, "disable");
    assert_eq!(repo.count_by_tenant("t_tenant_skill_cfg").await.unwrap(), 1);

    let loaded = repo
        .get_by_tenant_and_skill("t_tenant_skill_cfg", "code-review")
        .await
        .unwrap()
        .expect("tenant skill config present");
    assert_eq!(loaded.id, "tenant_skill_cfg_1");
    let listed = repo.list_by_tenant("t_tenant_skill_cfg").await.unwrap();
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].system_skill_name, "code-review");

    let updated_at = ts(2026, 2, 4, 6, 6, 7);
    let updated = TenantSkillConfigRecord {
        action: "override".to_string(),
        override_skill_id: Some("skill_cfg_override".to_string()),
        updated_at: Some(updated_at),
        ..loaded
    };
    let updated = repo.update(&updated).await.unwrap();
    assert_eq!(updated.action, "override");
    assert_eq!(
        updated.override_skill_id.as_deref(),
        Some("skill_cfg_override")
    );

    assert!(repo
        .delete_by_tenant_and_skill("t_tenant_skill_cfg", "code-review")
        .await
        .unwrap());
    assert!(!repo
        .delete_by_tenant_and_skill("t_tenant_skill_cfg", "code-review")
        .await
        .unwrap());
}

#[tokio::test]
async fn trust_repository_matches_python_governance_lifecycle() {
    let Some(pool) = pool_or_skip("trust_repository_matches_python_governance_lifecycle").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_trust_tables(&pool).await;

    for sql in [
        "DELETE FROM trust_policies WHERE tenant_id = 't_trust_pg'",
        "DELETE FROM decision_records WHERE tenant_id = 't_trust_pg'",
        "DELETE FROM workspaces WHERE id = 'w_trust_pg'",
        "DELETE FROM user_tenants WHERE tenant_id = 't_trust_pg'",
        "DELETE FROM projects WHERE id = 'p_trust_pg'",
        "DELETE FROM tenants WHERE id = 't_trust_pg'",
        "DELETE FROM users WHERE id IN ('u_trust_admin', 'u_trust_member', 'u_trust_super')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    for (user_id, email, is_superuser) in [
        ("u_trust_admin", "admin-trust@x", false),
        ("u_trust_member", "member-trust@x", false),
        ("u_trust_super", "super-trust@x", true),
    ] {
        sqlx::query("INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3)")
            .bind(user_id)
            .bind(email)
            .bind(is_superuser)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_trust_pg', 'Trust T')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_trust_pg', 't_trust_pg', 'Trust P', 'u_trust_admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO workspaces (id, tenant_id, project_id, name, created_by) \
         VALUES ('w_trust_pg', 't_trust_pg', 'p_trust_pg', 'Trust W', 'u_trust_admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    for (id, user_id, role) in [
        ("ut_trust_admin", "u_trust_admin", "admin"),
        ("ut_trust_member", "u_trust_member", "member"),
    ] {
        sqlx::query(
            "INSERT INTO user_tenants (id, user_id, tenant_id, role) VALUES ($1, $2, $3, $4)",
        )
        .bind(id)
        .bind(user_id)
        .bind("t_trust_pg")
        .bind(role)
        .execute(&pool)
        .await
        .unwrap();
    }

    let repo = PgTrustRepository::new(pool.clone());
    assert_eq!(
        repo.tenant_access_status("u_trust_admin", "t_trust_pg", true)
            .await
            .unwrap(),
        TenantAccessStatus::Authorized
    );
    assert_eq!(
        repo.tenant_access_status("u_trust_member", "t_trust_pg", false)
            .await
            .unwrap(),
        TenantAccessStatus::Authorized
    );
    assert_eq!(
        repo.tenant_access_status("u_trust_member", "t_trust_pg", true)
            .await
            .unwrap(),
        TenantAccessStatus::NotAdmin
    );
    assert_eq!(
        repo.tenant_access_status("u_trust_super", "t_trust_pg", true)
            .await
            .unwrap(),
        TenantAccessStatus::Authorized
    );
    assert_eq!(
        repo.tenant_access_status("u_trust_admin", "missing_trust_pg", false)
            .await
            .unwrap(),
        TenantAccessStatus::TenantNotFound
    );
    assert!(repo
        .workspace_exists_in_tenant("t_trust_pg", "w_trust_pg")
        .await
        .unwrap());
    assert!(!repo
        .workspace_exists_in_tenant("t_trust_pg", "missing_workspace")
        .await
        .unwrap());

    let now = Utc::now();
    let policy = repo
        .create_policy(NewTrustPolicyRecord {
            id: "tp_trust_pg".into(),
            tenant_id: "t_trust_pg".into(),
            workspace_id: "w_trust_pg".into(),
            agent_instance_id: "agent_trust_pg".into(),
            action_type: "terminal.execute".into(),
            granted_by: "u_trust_admin".into(),
            grant_type: "always".into(),
            created_at: now,
        })
        .await
        .unwrap();
    assert_eq!(policy.workspace_id, "w_trust_pg");
    assert!(repo
        .check_always_trust("w_trust_pg", "agent_trust_pg", "terminal.execute")
        .await
        .unwrap());
    assert!(!repo
        .check_always_trust("w_trust_pg", "agent_trust_pg", "browser.open")
        .await
        .unwrap());
    let policies = repo.list_policies("w_trust_pg", None).await.unwrap();
    assert!(policies.iter().any(|p| p.id == "tp_trust_pg"));
    let agent_policies = repo
        .list_policies("w_trust_pg", Some("agent_trust_pg"))
        .await
        .unwrap();
    assert!(agent_policies.iter().any(|p| p.id == "tp_trust_pg"));

    let decision = repo
        .create_decision(NewDecisionRecordRecord {
            id: "dr_trust_pg".into(),
            tenant_id: "t_trust_pg".into(),
            workspace_id: "w_trust_pg".into(),
            agent_instance_id: "agent_trust_pg".into(),
            decision_type: "browser.open".into(),
            context_summary: Some("Open a browser".into()),
            proposal: json!({"url": "https://example.test"}),
            outcome: "pending".into(),
            created_at: now,
        })
        .await
        .unwrap();
    assert_eq!(decision.outcome, "pending");
    assert_eq!(decision.proposal, json!({"url": "https://example.test"}));
    assert!(repo.find_decision("dr_trust_pg").await.unwrap().is_some());
    let listed = repo
        .list_decisions("w_trust_pg", Some("agent_trust_pg"), Some("browser.open"))
        .await
        .unwrap();
    assert!(listed.iter().any(|r| r.id == "dr_trust_pg"));

    let resolved_at = Utc::now();
    let resolved = repo
        .resolve_decision(TrustDecisionResolution {
            record_id: "dr_trust_pg",
            reviewer_id: "u_trust_admin",
            review_type: "human",
            review_comment: "Allowed always — trust policy created",
            outcome: "success",
            resolved_at,
            new_policy: Some(NewTrustPolicyRecord {
                id: "tp_trust_pg_auto".into(),
                tenant_id: "t_trust_pg".into(),
                workspace_id: "w_trust_pg".into(),
                agent_instance_id: "agent_trust_pg".into(),
                action_type: "browser.open".into(),
                granted_by: "u_trust_admin".into(),
                grant_type: "always".into(),
                created_at: resolved_at,
            }),
        })
        .await
        .unwrap()
        .expect("resolved decision");
    assert_eq!(resolved.outcome, "success");
    assert_eq!(resolved.reviewer_id.as_deref(), Some("u_trust_admin"));
    assert_eq!(resolved.review_type.as_deref(), Some("human"));
    assert_eq!(
        resolved.review_comment.as_deref(),
        Some("Allowed always — trust policy created")
    );
    assert!(resolved.resolved_at.is_some());
    assert!(repo
        .check_always_trust("w_trust_pg", "agent_trust_pg", "browser.open")
        .await
        .unwrap());
    assert!(repo
        .resolve_decision(TrustDecisionResolution {
            record_id: "missing_decision",
            reviewer_id: "u_trust_admin",
            review_type: "human",
            review_comment: "Allowed once",
            outcome: "success",
            resolved_at: Utc::now(),
            new_policy: None,
        },)
        .await
        .unwrap()
        .is_none());
}
