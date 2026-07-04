use super::support::*;

#[tokio::test]
async fn project_reads_roundtrip_against_shared_schema() {
    let Some(pool) = pool_or_skip("project_reads_roundtrip_against_shared_schema").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    ensure_project_read_tables(&pool).await;

    for sql in [
        "DELETE FROM project_delete_audit_children WHERE id IN ('p2_audit_child')",
        "DELETE FROM project_delete_audit_entries WHERE id IN ('p2_audit_entry') \
         OR project_id IN ('p_p2_created')",
        "DELETE FROM messages WHERE id IN ('msg_p2_created_parent', 'msg_p2_created_child') \
         OR conversation_id IN ('c_p2_delete_parent', 'c_p2_delete_child')",
        "DELETE FROM conversations WHERE project_id IN ('p_p2_default', 'p_p2_other', 'p_p2_hidden', 'p_p2_created')",
        "DELETE FROM workspaces WHERE project_id IN ('p_p2_created')",
        "DELETE FROM memories WHERE project_id IN ('p_p2_default', 'p_p2_other', 'p_p2_hidden', 'p_p2_created')",
        "DELETE FROM user_projects WHERE user_id IN ('u_p2_projects', 'u_p2_other') \
         OR project_id IN ('p_p2_default', 'p_p2_other', 'p_p2_hidden', 'p_p2_orphan', 'p_p2_created')",
        "DELETE FROM projects WHERE id IN ('p_p2_default', 'p_p2_other', 'p_p2_hidden', 'p_p2_created')",
        "DELETE FROM user_tenants WHERE user_id IN ('u_p2_projects', 'u_p2_other') \
         OR tenant_id IN ('t_p2_projects', 't_p2_elsewhere')",
        "DELETE FROM tenants WHERE id IN ('t_p2_projects', 't_p2_elsewhere')",
        "DELETE FROM users WHERE id IN ('u_p2_projects', 'u_p2_other')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    sqlx::query(
        "INSERT INTO users (id, email, full_name, is_superuser) VALUES \
         ('u_p2_projects', 'projects@memstack.ai', 'Project Owner', false), \
         ('u_p2_other', 'other-projects@memstack.ai', 'Other Owner', false)",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) VALUES \
         ('t_p2_projects', 'Projects Tenant', 'projects-tenant', 'u_p2_projects'), \
         ('t_p2_elsewhere', 'Other Tenant', 'other-tenant', 'u_p2_other')",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) VALUES \
         ('ut_p2_projects', 'u_p2_projects', 't_p2_projects', 'admin', '{\"create_projects\": true}'::json), \
         ('ut_p2_other', 'u_p2_other', 't_p2_elsewhere', 'member', '{}'::json)",
    )
    .execute(&pool)
    .await
    .unwrap();

    for (id, tenant_id, name, owner, is_public, created_at) in [
        (
            "p_p2_default",
            "t_p2_projects",
            "Default project",
            "u_p2_projects",
            false,
            "2024-01-01T00:00:00Z",
        ),
        (
            "p_p2_other",
            "t_p2_projects",
            "Other Project",
            "u_p2_other",
            true,
            "2025-01-01T00:00:00Z",
        ),
        (
            "p_p2_hidden",
            "t_p2_elsewhere",
            "Hidden Project",
            "u_p2_other",
            false,
            "2025-02-01T00:00:00Z",
        ),
    ] {
        sqlx::query(
            "INSERT INTO projects \
             (id, tenant_id, name, description, owner_id, is_public, created_at, memory_rules, graph_config) \
             VALUES ($1, $2, $3, $3, $4, $5, $6::timestamptz, '{}'::json, '{}'::json)",
        )
        .bind(id)
        .bind(tenant_id)
        .bind(name)
        .bind(owner)
        .bind(is_public)
        .bind(created_at)
        .execute(&pool)
        .await
        .unwrap();
    }

    for (user_id, project_id, role, created_at, permissions) in [
        (
            "u_p2_projects",
            "p_p2_default",
            "owner",
            "2024-01-02T00:00:00Z",
            serde_json::json!({"admin": true, "read": true, "write": true, "delete": true}),
        ),
        (
            "u_p2_projects",
            "p_p2_other",
            "viewer",
            "2024-01-03T00:00:00Z",
            serde_json::json!({"read": true, "write": false}),
        ),
        (
            "u_p2_other",
            "p_p2_hidden",
            "owner",
            "2024-01-04T00:00:00Z",
            serde_json::json!({"admin": true, "read": true, "write": true, "delete": true}),
        ),
        (
            "u_p2_projects",
            "p_p2_orphan",
            "viewer",
            "2024-01-05T00:00:00Z",
            serde_json::json!({"read": true, "write": false}),
        ),
    ] {
        sqlx::query(
            "INSERT INTO user_projects (user_id, project_id, role, created_at, permissions) \
             VALUES ($1, $2, $3, $4::timestamptz, $5)",
        )
        .bind(user_id)
        .bind(project_id)
        .bind(role)
        .bind(created_at)
        .bind(permissions)
        .execute(&pool)
        .await
        .unwrap();
    }

    sqlx::query(
        "INSERT INTO memories (id, project_id, title, content, author_id, created_at) VALUES \
         ('m_p2_project_1', 'p_p2_default', 'M1', 'hello', 'u_p2_projects', '2024-02-01T00:00:00Z'), \
         ('m_p2_project_2', 'p_p2_default', 'M2', 'world!!', 'u_p2_projects', '2024-03-01T00:00:00Z')",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "INSERT INTO conversations (id, project_id, tenant_id, user_id, title, created_at) VALUES \
         ('c_p2_project_1', 'p_p2_default', 't_p2_projects', 'u_p2_projects', 'C1', '2024-04-01T00:00:00Z'), \
         ('c_p2_project_2', 'p_p2_default', 't_p2_projects', 'u_p2_projects', 'C2', '2024-04-02T00:00:00Z'), \
         ('c_p2_project_3', 'p_p2_other', 't_p2_projects', 'u_p2_projects', 'C3', '2024-04-03T00:00:00Z')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let projects = PgProjectReadRepository::new(pool.clone());
    let page = projects
        .list_for_user(ProjectListForUserQuery {
            user_id: "u_p2_projects",
            tenant_id: Some("t_p2_projects"),
            search: None,
            visibility: "all",
            owner_id: None,
            offset: 0,
            limit: 20,
        })
        .await
        .unwrap();
    assert_eq!(page.total, 2);
    assert_eq!(page.projects[0].id, "p_p2_default");
    assert_eq!(page.projects[0].stats.memory_count, 2);
    assert_eq!(page.projects[0].stats.storage_used, 12);
    assert_eq!(page.projects[0].stats.member_count, 1);
    assert_eq!(page.projects[1].id, "p_p2_other");
    assert_eq!(page.owner_ids, vec!["u_p2_other", "u_p2_projects"]);

    let public = projects
        .list_for_user(ProjectListForUserQuery {
            user_id: "u_p2_projects",
            tenant_id: Some("t_p2_projects"),
            search: None,
            visibility: "public",
            owner_id: None,
            offset: 0,
            limit: 20,
        })
        .await
        .unwrap();
    assert_eq!(public.total, 1);
    assert_eq!(public.projects[0].id, "p_p2_other");

    let searched = projects
        .list_for_user(ProjectListForUserQuery {
            user_id: "u_p2_projects",
            tenant_id: Some("t_p2_projects"),
            search: Some("default"),
            visibility: "all",
            owner_id: None,
            offset: 0,
            limit: 20,
        })
        .await
        .unwrap();
    assert_eq!(searched.total, 1);
    assert_eq!(searched.projects[0].id, "p_p2_default");

    assert!(matches!(
        projects
            .get_for_user("u_p2_projects", "p_p2_default", Some("t_p2_projects"))
            .await
            .unwrap(),
        ProjectLookup::Found(p) if p.id == "p_p2_default"
    ));
    assert!(matches!(
        projects
            .get_for_user("u_p2_projects", "p_p2_default", Some("t_p2_elsewhere"))
            .await
            .unwrap(),
        ProjectLookup::TenantMismatch
    ));
    assert!(matches!(
        projects
            .get_for_user("u_p2_projects", "p_p2_hidden", None)
            .await
            .unwrap(),
        ProjectLookup::Forbidden
    ));
    assert!(matches!(
        projects
            .get_for_user("u_p2_projects", "p_p2_orphan", None)
            .await
            .unwrap(),
        ProjectLookup::NotFound
    ));

    let stats = projects
        .stats_for_user("u_p2_projects", "p_p2_default")
        .await
        .unwrap();
    match stats {
        ProjectStatsLookup::Found(stats) => {
            assert_eq!(stats.memory_count, 2);
            assert_eq!(stats.storage_used, 12);
            assert_eq!(stats.member_count, 1);
            assert_eq!(stats.conversation_count, 2);
            assert_eq!(stats.recent_activity.len(), 2);
            assert_eq!(stats.recent_activity[0].id, "m_p2_project_2");
            assert_eq!(stats.recent_activity[0].user, "Project Owner");
            assert_eq!(stats.recent_activity[0].target, "M2");
        }
        other => panic!("expected stats, got {other:?}"),
    }
    assert!(matches!(
        projects
            .stats_for_user("u_p2_projects", "p_p2_hidden")
            .await
            .unwrap(),
        ProjectStatsLookup::Forbidden
    ));
    assert!(matches!(
        projects
            .stats_for_user("u_p2_projects", "p_p2_orphan")
            .await
            .unwrap(),
        ProjectStatsLookup::NotFound
    ));

    let members = projects
        .members_for_user("u_p2_projects", "p_p2_default")
        .await
        .unwrap();
    match members {
        ProjectMembersLookup::Found(members) => {
            assert_eq!(members.total, 1);
            assert_eq!(members.members.len(), 1);
            assert_eq!(members.members[0].user_id, "u_p2_projects");
            assert_eq!(members.members[0].email, "projects@memstack.ai");
            assert_eq!(members.members[0].name.as_deref(), Some("Project Owner"));
            assert_eq!(members.members[0].role, "owner");
            assert_eq!(members.members[0].permissions["admin"], true);
        }
        other => panic!("expected members, got {other:?}"),
    }
    assert!(matches!(
        projects
            .members_for_user("u_p2_projects", "p_p2_hidden")
            .await
            .unwrap(),
        ProjectMembersLookup::Forbidden
    ));
    assert!(matches!(
        projects
            .members_for_user("u_p2_projects", "p_p2_orphan")
            .await
            .unwrap(),
        ProjectMembersLookup::InvalidId
    ));
    assert!(matches!(
        projects
            .members_for_user("u_p2_projects", "not-a-uuid")
            .await
            .unwrap(),
        ProjectMembersLookup::InvalidId
    ));
    assert!(matches!(
        projects
            .members_for_user("u_p2_projects", "00000000-0000-0000-0000-000000000000")
            .await
            .unwrap(),
        ProjectMembersLookup::NotFound
    ));

    assert!(projects
        .user_is_project_admin("u_p2_projects", "p_p2_default")
        .await
        .unwrap());
    assert!(!projects
        .user_is_project_admin("u_p2_projects", "p_p2_other")
        .await
        .unwrap());
    assert!(projects.project_exists("p_p2_default").await.unwrap());
    assert!(!projects.project_exists("p_p2_missing").await.unwrap());
    assert!(projects.user_exists("u_p2_other").await.unwrap());
    assert!(projects
        .project_member_role("p_p2_default", "u_p2_other")
        .await
        .unwrap()
        .is_none());

    projects
        .add_project_member(
            "up_p2_added",
            "p_p2_default",
            "u_p2_other",
            "editor",
            &json!({"read": true, "write": true}),
        )
        .await
        .unwrap();
    let added = projects
        .project_member_role("p_p2_default", "u_p2_other")
        .await
        .unwrap()
        .expect("added membership");
    assert_eq!(added.role, "editor");
    let add_permissions: serde_json::Value = sqlx::query_as::<_, (serde_json::Value,)>(
        "SELECT permissions FROM user_projects WHERE project_id = 'p_p2_default' AND user_id = 'u_p2_other'",
    )
    .fetch_one(&pool)
    .await
    .unwrap()
    .0;
    assert_eq!(add_permissions["write"], true);

    assert!(projects
        .update_project_member(
            "p_p2_default",
            "u_p2_other",
            "editor",
            &json!({"read": true, "write": false}),
        )
        .await
        .unwrap());
    let update_permissions: serde_json::Value = sqlx::query_as::<_, (serde_json::Value,)>(
        "SELECT permissions FROM user_projects WHERE project_id = 'p_p2_default' AND user_id = 'u_p2_other'",
    )
    .fetch_one(&pool)
    .await
    .unwrap()
    .0;
    assert_eq!(update_permissions["write"], false);

    assert!(projects
        .remove_project_member("p_p2_default", "u_p2_other")
        .await
        .unwrap());
    assert!(!projects
        .remove_project_member("p_p2_default", "u_p2_other")
        .await
        .unwrap());
    assert!(projects
        .project_member_role("p_p2_default", "u_p2_other")
        .await
        .unwrap()
        .is_none());

    assert!(projects
        .user_is_tenant_project_admin("u_p2_projects", "t_p2_projects")
        .await
        .unwrap());
    assert!(!projects
        .user_is_tenant_project_admin("u_p2_other", "t_p2_elsewhere")
        .await
        .unwrap());

    let created = projects
        .create_project(&ProjectCreateRecord {
            id: "p_p2_created".to_string(),
            membership_id: "up_p2_created_owner".to_string(),
            tenant_id: "t_p2_projects".to_string(),
            name: "Created Project".to_string(),
            description: Some("created from Rust".to_string()),
            owner_id: "u_p2_projects".to_string(),
            memory_rules: json!({"max_episodes": 3000, "retention_days": 90}),
            graph_config: json!({"max_nodes": 7000}),
            graph_store_id: None,
            retrieval_store_id: None,
            sandbox_type: "cloud".to_string(),
            sandbox_config: json!({}),
            is_public: true,
            agent_conversation_mode: "multi_agent_shared".to_string(),
            owner_permissions: json!({"admin": true, "read": true, "write": true, "delete": true}),
        })
        .await
        .unwrap();
    assert_eq!(created.id, "p_p2_created");
    assert_eq!(created.owner_id, "u_p2_projects");
    assert_eq!(created.member_ids, vec!["u_p2_projects"]);
    assert_eq!(created.stats.member_count, 1);
    assert_eq!(created.agent_conversation_mode, "multi_agent_shared");
    let owner_role = projects
        .project_member_role("p_p2_created", "u_p2_projects")
        .await
        .unwrap()
        .expect("created owner membership");
    assert_eq!(owner_role.role, "owner");

    let updated = projects
        .update_project(
            "p_p2_created",
            &ProjectUpdatePatch {
                name: Some("Updated Project".to_string()),
                description: Some(None),
                memory_rules: Some(json!({"retention_days": 60})),
                graph_config: Some(json!({"max_nodes": 9000})),
                graph_store_id: Some(None),
                retrieval_store_id: Some(None),
                sandbox_config: Some(json!({
                    "sandbox_type": "local",
                    "local_config": {"host": "localhost", "port": 8765}
                })),
                is_public: Some(false),
                agent_conversation_mode: Some("multi_agent_isolated".to_string()),
            },
        )
        .await
        .unwrap()
        .expect("updated project");
    assert_eq!(updated.name, "Updated Project");
    assert!(updated.description.is_none());
    assert_eq!(updated.memory_rules["retention_days"], 60);
    assert_eq!(updated.graph_config["max_nodes"], 9000);
    assert!(!updated.is_public);
    assert_eq!(updated.sandbox_config["sandbox_type"], "local");
    assert_eq!(updated.agent_conversation_mode, "multi_agent_isolated");
    assert!(projects
        .update_project("p_p2_missing", &ProjectUpdatePatch::default())
        .await
        .unwrap()
        .is_none());

    assert!(projects
        .user_is_project_owner("u_p2_projects", "p_p2_created")
        .await
        .unwrap());
    assert!(!projects
        .user_is_project_owner("u_p2_other", "p_p2_created")
        .await
        .unwrap());

    sqlx::query(
        "INSERT INTO conversations \
         (id, project_id, tenant_id, user_id, title, parent_conversation_id, fork_source_id) VALUES \
         ('c_p2_delete_parent', 'p_p2_created', 't_p2_projects', 'u_p2_projects', 'Delete parent', NULL, NULL), \
         ('c_p2_delete_child', 'p_p2_created', 't_p2_projects', 'u_p2_projects', 'Delete child', \
          'c_p2_delete_parent', 'c_p2_delete_parent')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO messages (id, conversation_id, reply_to_id, content) VALUES \
         ('msg_p2_created_parent', 'c_p2_delete_parent', NULL, 'parent'), \
         ('msg_p2_created_child', 'c_p2_delete_child', 'msg_p2_created_parent', 'child')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO workspaces (id, tenant_id, project_id, name, created_by) \
         VALUES ('w_p2_created', 't_p2_projects', 'p_p2_created', 'Delete workspace', 'u_p2_projects')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO project_delete_audit_entries (id, project_id) \
         VALUES ('p2_audit_entry', 'p_p2_created')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO project_delete_audit_children (id, entry_id) \
         VALUES ('p2_audit_child', 'p2_audit_entry')",
    )
    .execute(&pool)
    .await
    .unwrap();

    assert!(projects.delete_project("p_p2_created").await.unwrap());
    for (table, predicate) in [
        ("projects", "id = 'p_p2_created'"),
        ("user_projects", "project_id = 'p_p2_created'"),
        ("conversations", "project_id = 'p_p2_created'"),
        (
            "messages",
            "id IN ('msg_p2_created_parent', 'msg_p2_created_child')",
        ),
        ("workspaces", "project_id = 'p_p2_created'"),
        (
            "project_delete_audit_entries",
            "project_id = 'p_p2_created'",
        ),
        ("project_delete_audit_children", "id = 'p2_audit_child'"),
    ] {
        let sql = format!("SELECT count(*) FROM {table} WHERE {predicate}");
        let count = sqlx::query_as::<_, (i64,)>(&sql)
            .fetch_one(&pool)
            .await
            .unwrap()
            .0;
        assert_eq!(count, 0, "{table} rows should be removed by project delete");
    }
}
