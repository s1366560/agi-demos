use super::support::*;

#[tokio::test]
async fn instances_are_default_tenant_scoped_and_python_ordered() {
    let Some(pool) = pool_or_skip("instances_are_default_tenant_scoped_and_python_ordered").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_instance_rows(&pool).await;

    seed_instance_user(&pool, "instance_user").await;
    seed_instance_member_user(&pool, "instance_member_old", "Old Member").await;
    seed_instance_member_user(&pool, "instance_member_latest", "Latest Member").await;
    seed_instance_member_user(&pool, "instance_member_deleted", "Deleted Member").await;
    seed_instance_tenant(&pool, "instance_tenant_a").await;
    seed_instance_tenant(&pool, "instance_tenant_b").await;
    seed_instance_membership(
        &pool,
        "instance_membership_a",
        "instance_user",
        "instance_tenant_a",
        ts(2026, 3, 1, 0, 0, 0),
    )
    .await;
    seed_instance_membership(
        &pool,
        "instance_membership_b",
        "instance_user",
        "instance_tenant_b",
        ts(2026, 3, 2, 0, 0, 0),
    )
    .await;
    seed_instance_membership(
        &pool,
        "instance_member_membership_old",
        "instance_member_old",
        "instance_tenant_a",
        ts(2026, 3, 2, 1, 0, 0),
    )
    .await;
    seed_instance_membership(
        &pool,
        "instance_member_membership_latest",
        "instance_member_latest",
        "instance_tenant_a",
        ts(2026, 3, 2, 2, 0, 0),
    )
    .await;
    seed_instance_membership(
        &pool,
        "instance_member_membership_deleted",
        "instance_member_deleted",
        "instance_tenant_a",
        ts(2026, 3, 2, 3, 0, 0),
    )
    .await;
    seed_instance_record(
        &pool,
        "instance_old",
        "instance_tenant_a",
        ts(2026, 3, 3, 0, 0, 0),
        false,
    )
    .await;
    seed_instance_record(
        &pool,
        "instance_latest",
        "instance_tenant_a",
        ts(2026, 3, 4, 0, 0, 0),
        false,
    )
    .await;
    seed_instance_record(
        &pool,
        "instance_other_tenant",
        "instance_tenant_b",
        ts(2026, 3, 5, 0, 0, 0),
        false,
    )
    .await;
    seed_instance_record(
        &pool,
        "instance_deleted",
        "instance_tenant_a",
        ts(2026, 3, 6, 0, 0, 0),
        true,
    )
    .await;
    seed_instance_channel(
        &pool,
        "instance_channel_old",
        "instance_latest",
        ts(2026, 3, 4, 1, 0, 0),
        None,
    )
    .await;
    seed_instance_channel(
        &pool,
        "instance_channel_latest",
        "instance_latest",
        ts(2026, 3, 4, 2, 0, 0),
        None,
    )
    .await;
    seed_instance_channel(
        &pool,
        "instance_channel_deleted",
        "instance_latest",
        ts(2026, 3, 4, 3, 0, 0),
        Some(ts(2026, 3, 4, 3, 1, 0)),
    )
    .await;
    seed_instance_channel(
        &pool,
        "instance_channel_other",
        "instance_other_tenant",
        ts(2026, 3, 5, 1, 0, 0),
        None,
    )
    .await;
    seed_instance_member(
        &pool,
        "instance_member_row_old",
        "instance_latest",
        "instance_member_old",
        "viewer",
        ts(2026, 3, 4, 1, 0, 0),
        None,
    )
    .await;
    seed_instance_member(
        &pool,
        "instance_member_row_latest",
        "instance_latest",
        "instance_member_latest",
        "admin",
        ts(2026, 3, 4, 2, 0, 0),
        None,
    )
    .await;
    seed_instance_member(
        &pool,
        "instance_member_row_deleted",
        "instance_latest",
        "instance_member_deleted",
        "viewer",
        ts(2026, 3, 4, 3, 0, 0),
        Some(ts(2026, 3, 4, 3, 1, 0)),
    )
    .await;

    let repo = PgInstanceRepository::new(pool.clone());
    let tenant_id = repo
        .default_tenant_for_user("instance_user")
        .await
        .expect("default tenant query")
        .expect("user has tenant");
    assert_eq!(tenant_id, "instance_tenant_a");
    assert!(repo
        .default_tenant_for_user("instance_missing_user")
        .await
        .expect("missing user tenant query")
        .is_none());

    let (records, total) = repo
        .list_instances(InstanceListQuery {
            tenant_id: &tenant_id,
            limit: 10,
            offset: 0,
        })
        .await
        .expect("instance list succeeds");
    assert_eq!(total, 2);
    assert_eq!(
        records
            .iter()
            .map(|instance| instance.id.as_str())
            .collect::<Vec<_>>(),
        vec!["instance_latest", "instance_old"]
    );
    assert_eq!(records[0].env_vars, json!({"RUST_LOG": "info"}));
    assert_eq!(records[0].pending_config, json!({"image_version": "1.3.0"}));

    let detail = repo
        .get_instance(&tenant_id, "instance_latest")
        .await
        .expect("instance detail query")
        .expect("instance detail exists");
    assert_eq!(detail.name, "Instance instance_latest");
    assert_eq!(detail.tenant_id, "instance_tenant_a");
    assert!(repo
        .get_instance(&tenant_id, "instance_other_tenant")
        .await
        .expect("wrong tenant instance detail query")
        .is_none());

    let updated = repo
        .save_pending_config(
            &tenant_id,
            "instance_latest",
            json!({"image_version": "2.0.0", "replicas": 3}),
        )
        .await
        .expect("save pending config query")
        .expect("updated instance exists");
    assert_eq!(
        updated.pending_config,
        json!({"image_version": "2.0.0", "replicas": 3})
    );
    assert!(repo
        .save_pending_config(&tenant_id, "instance_other_tenant", json!({}))
        .await
        .expect("wrong tenant pending config query")
        .is_none());
    let config_updated = repo
        .update_instance_config(
            &tenant_id,
            "instance_latest",
            json!({"RUST_LOG": "debug"}),
            json!({"autoscale": false}),
            json!({
                "provider_id": "provider-2",
                "model_name": "gpt-4o",
                "api_key_override": "secret"
            }),
        )
        .await
        .expect("update instance config")
        .expect("config updated instance exists");
    assert_eq!(config_updated.env_vars, json!({"RUST_LOG": "debug"}));
    assert_eq!(config_updated.advanced_config, json!({"autoscale": false}));
    assert_eq!(
        config_updated.llm_providers,
        json!({
            "provider_id": "provider-2",
            "model_name": "gpt-4o",
            "api_key_override": "secret"
        })
    );
    assert!(repo
        .update_instance_config(
            &tenant_id,
            "instance_other_tenant",
            json!({}),
            json!({}),
            json!({})
        )
        .await
        .expect("wrong tenant config update")
        .is_none());

    assert_eq!(
        repo.instance_tenant_id("instance_latest")
            .await
            .expect("instance tenant query")
            .as_deref(),
        Some("instance_tenant_a")
    );
    assert!(repo
        .user_can_access_tenant("instance_user", "instance_tenant_a")
        .await
        .expect("tenant access query"));
    assert!(!repo
        .user_can_access_tenant("instance_missing_user", "instance_tenant_a")
        .await
        .expect("missing user tenant access query"));

    let channels = repo
        .list_instance_channels("instance_latest")
        .await
        .expect("instance channels query");
    assert_eq!(
        channels
            .iter()
            .map(|channel| channel.id.as_str())
            .collect::<Vec<_>>(),
        vec!["instance_channel_latest", "instance_channel_old"]
    );
    assert_eq!(
        channels[0].config,
        json!({"webhook_url": "https://example.test/hook"})
    );
    assert_eq!(channels[0].status, "connected");

    let (members, member_total) = repo
        .list_instance_members(InstanceMemberListQuery {
            instance_id: "instance_latest",
            limit: 10,
            offset: 0,
        })
        .await
        .expect("instance members query");
    assert_eq!(member_total, 2);
    assert_eq!(
        members
            .iter()
            .map(|member| member.id.as_str())
            .collect::<Vec<_>>(),
        vec!["instance_member_row_old", "instance_member_row_latest"]
    );
    assert_eq!(members[0].user_name.as_deref(), Some("Old Member"));
    assert_eq!(
        members[1].user_email.as_deref(),
        Some("instance_member_latest@example.test")
    );

    assert!(!repo
        .instance_member_exists_any("instance_latest", "instance_user")
        .await
        .expect("new member existence query"));
    let inserted_member = repo
        .insert_instance_member(
            "instance_member_row_new",
            "instance_latest",
            "instance_user",
            "user",
        )
        .await
        .expect("insert instance member");
    assert_eq!(
        inserted_member.user_email.as_deref(),
        Some("instance_user@example.test")
    );
    assert!(repo
        .instance_member_exists_any("instance_latest", "instance_user")
        .await
        .expect("inserted member existence query"));
    let updated_member = repo
        .update_instance_member_role("instance_latest", "instance_member_row_new", "editor")
        .await
        .expect("update instance member")
        .expect("updated member exists");
    assert_eq!(updated_member.role, "editor");
    assert!(repo
        .update_instance_member_role("instance_other_tenant", "instance_member_row_new", "admin")
        .await
        .expect("wrong instance member update")
        .is_none());
    assert!(repo
        .soft_delete_instance_member("instance_latest", "instance_user")
        .await
        .expect("soft delete instance member"));
    assert!(!repo
        .soft_delete_instance_member("instance_latest", "instance_missing_user")
        .await
        .expect("missing member delete"));

    let users = repo
        .search_tenant_users("instance_tenant_a", "Member", 10)
        .await
        .expect("instance member user search");
    assert_eq!(
        users
            .iter()
            .map(|user| user.id.as_str())
            .collect::<Vec<_>>(),
        vec![
            "instance_member_deleted",
            "instance_member_latest",
            "instance_member_old"
        ]
    );
}

async fn clean_instance_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM instance_members WHERE id LIKE 'instance_%'")
        .execute(pool)
        .await
        .expect("clean instance members");
    sqlx::query("DELETE FROM instance_channel_configs WHERE id LIKE 'instance_%'")
        .execute(pool)
        .await
        .expect("clean instance channels");
    sqlx::query("DELETE FROM instances WHERE id LIKE 'instance_%'")
        .execute(pool)
        .await
        .expect("clean instances");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'instance_%'")
        .execute(pool)
        .await
        .expect("clean instance memberships");
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'instance_%'")
        .execute(pool)
        .await
        .expect("clean instance tenants");
    sqlx::query("DELETE FROM users WHERE id LIKE 'instance_%'")
        .execute(pool)
        .await
        .expect("clean instance users");
}

async fn seed_instance_user(pool: &PgPool, user_id: &str) {
    sqlx::query(
        "INSERT INTO users (id, email, is_active, is_superuser) VALUES ($1, $2, true, false) \
         ON CONFLICT (id) DO UPDATE SET is_active = true",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .execute(pool)
    .await
    .expect("seed instance user");
}

async fn seed_instance_member_user(pool: &PgPool, user_id: &str, full_name: &str) {
    sqlx::query(
        "INSERT INTO users (id, email, full_name, is_active, is_superuser) \
         VALUES ($1, $2, $3, true, false) \
         ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, full_name = EXCLUDED.full_name",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(full_name)
    .execute(pool)
    .await
    .expect("seed instance member user");
}

async fn seed_instance_tenant(pool: &PgPool, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .execute(pool)
    .await
    .expect("seed instance tenant");
}

async fn seed_instance_membership(
    pool: &PgPool,
    id: &str,
    user_id: &str,
    tenant_id: &str,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions, created_at) \
         VALUES ($1, $2, $3, 'member', $4, $5) \
         ON CONFLICT (id) DO UPDATE SET created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(user_id)
    .bind(tenant_id)
    .bind(json!({}))
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed instance membership");
}

async fn seed_instance_record(
    pool: &PgPool,
    id: &str,
    tenant_id: &str,
    created_at: DateTime<Utc>,
    deleted: bool,
) {
    let deleted_at = deleted.then_some(created_at);
    sqlx::query(
        "INSERT INTO instances \
         (id, name, slug, description, tenant_id, cluster_id, namespace, image_version, \
          replicas, cpu_request, cpu_limit, mem_request, mem_limit, service_type, ingress_domain, \
          proxy_token, env_vars, quota_cpu, quota_memory, quota_max_pods, storage_class, \
          storage_size, advanced_config, llm_providers, pending_config, available_replicas, \
          status, health_status, current_revision, compute_provider, runtime, created_by, \
          workspace_id, hex_position_q, hex_position_r, agent_display_name, agent_label, \
          theme_color, created_at, updated_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, \
                 $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, \
                 $27, $28, $29, $30, $31, $32, $33, $34, $35, $36, $37, $38, \
                 $39, $40, $41) \
         ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, \
             created_at = EXCLUDED.created_at, deleted_at = EXCLUDED.deleted_at",
    )
    .bind(id)
    .bind(format!("Instance {id}"))
    .bind(id)
    .bind("Integration instance")
    .bind(tenant_id)
    .bind("cluster-1")
    .bind("production")
    .bind("1.2.0")
    .bind(2_i32)
    .bind("200m")
    .bind("1000m")
    .bind("512Mi")
    .bind("1Gi")
    .bind("ClusterIP")
    .bind("agents.example.test")
    .bind("proxy-token")
    .bind(json!({"RUST_LOG": "info"}))
    .bind("2")
    .bind("4Gi")
    .bind(4_i32)
    .bind("standard")
    .bind("20Gi")
    .bind(json!({"autoscale": true}))
    .bind(json!({"provider_id": "provider-1"}))
    .bind(json!({"image_version": "1.3.0"}))
    .bind(2_i32)
    .bind("running")
    .bind("healthy")
    .bind(3_i32)
    .bind("kubernetes")
    .bind("default")
    .bind("instance_user")
    .bind("workspace-1")
    .bind(1_i32)
    .bind(-1_i32)
    .bind("Prod Agent")
    .bind("prod")
    .bind("#3366ff")
    .bind(created_at)
    .bind(created_at)
    .bind(deleted_at)
    .execute(pool)
    .await
    .expect("seed instance record");
}

async fn seed_instance_channel(
    pool: &PgPool,
    id: &str,
    instance_id: &str,
    created_at: DateTime<Utc>,
    deleted_at: Option<DateTime<Utc>>,
) {
    sqlx::query(
        "INSERT INTO instance_channel_configs \
         (id, instance_id, channel_type, name, config, status, last_connected_at, \
          created_at, updated_at, deleted_at) \
         VALUES ($1, $2, 'feishu', $3, $4, 'connected', $5, $6, $7, $8) \
         ON CONFLICT (id) DO UPDATE SET instance_id = EXCLUDED.instance_id, \
             created_at = EXCLUDED.created_at, deleted_at = EXCLUDED.deleted_at",
    )
    .bind(id)
    .bind(instance_id)
    .bind(format!("Channel {id}"))
    .bind(json!({"webhook_url": "https://example.test/hook"}))
    .bind(created_at)
    .bind(created_at)
    .bind(created_at)
    .bind(deleted_at)
    .execute(pool)
    .await
    .expect("seed instance channel");
}

async fn seed_instance_member(
    pool: &PgPool,
    id: &str,
    instance_id: &str,
    user_id: &str,
    role: &str,
    created_at: DateTime<Utc>,
    deleted_at: Option<DateTime<Utc>>,
) {
    sqlx::query(
        "INSERT INTO instance_members \
         (id, instance_id, user_id, role, created_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, $6) \
         ON CONFLICT (id) DO UPDATE SET instance_id = EXCLUDED.instance_id, \
             user_id = EXCLUDED.user_id, role = EXCLUDED.role, \
             created_at = EXCLUDED.created_at, deleted_at = EXCLUDED.deleted_at",
    )
    .bind(id)
    .bind(instance_id)
    .bind(user_id)
    .bind(role)
    .bind(created_at)
    .bind(deleted_at)
    .execute(pool)
    .await
    .expect("seed instance member");
}
