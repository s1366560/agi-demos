use super::support::*;

#[tokio::test]
async fn deploy_reads_are_tenant_scoped_and_python_ordered() {
    let Some(pool) = pool_or_skip("deploy_reads_are_tenant_scoped_and_python_ordered").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_deploy_rows(&pool).await;

    seed_deploy_user(&pool, "deploy_user", false).await;
    seed_deploy_user(&pool, "deploy_stranger", false).await;
    seed_deploy_user(&pool, "deploy_admin", true).await;
    seed_deploy_tenant(&pool, "deploy_tenant").await;
    seed_deploy_membership(&pool, "deploy_user", "deploy_tenant").await;
    seed_instance(&pool, "deploy_instance", "deploy_tenant").await;
    seed_instance(&pool, "deploy_other_instance", "deploy_other_tenant").await;
    seed_deploy(
        &pool,
        "deploy_old",
        "deploy_instance",
        1,
        ts(2026, 2, 1, 0, 0, 0),
    )
    .await;
    seed_deploy(
        &pool,
        "deploy_latest",
        "deploy_instance",
        2,
        ts(2026, 2, 2, 0, 0, 0),
    )
    .await;
    seed_deploy(
        &pool,
        "deploy_other_instance_record",
        "deploy_other_instance",
        1,
        ts(2026, 2, 3, 0, 0, 0),
    )
    .await;

    let repo = PgDeployRepository::new(pool.clone());
    assert_eq!(
        repo.access_for_instance("deploy_user", "deploy_instance")
            .await
            .expect("instance access query"),
        DeployAccess::Allowed
    );
    assert_eq!(
        repo.access_for_instance("deploy_stranger", "deploy_instance")
            .await
            .expect("instance stranger access query"),
        DeployAccess::Forbidden
    );
    assert_eq!(
        repo.access_for_instance("deploy_user", "deploy_missing_instance")
            .await
            .expect("missing instance access query"),
        DeployAccess::NotFound
    );
    assert_eq!(
        repo.access_for_deploy("deploy_admin", "deploy_other_instance_record")
            .await
            .expect("admin deploy access query"),
        DeployAccess::Allowed
    );

    let (records, total) = repo
        .list_deploys(DeployListQuery {
            instance_id: "deploy_instance",
            limit: 10,
            offset: 0,
        })
        .await
        .expect("deploy list succeeds");
    assert_eq!(total, 2);
    assert_eq!(
        records
            .iter()
            .map(|deploy| deploy.id.as_str())
            .collect::<Vec<_>>(),
        vec!["deploy_latest", "deploy_old"]
    );
    assert_eq!(records[0].revision, 2);
    assert_eq!(records[0].config_snapshot, json!({"cpu_limit": "1000m"}));

    let latest = repo
        .latest_deploy("deploy_instance")
        .await
        .expect("latest deploy query")
        .expect("latest deploy exists");
    assert_eq!(latest.id, "deploy_latest");

    let detail = repo
        .get_deploy("deploy_latest")
        .await
        .expect("deploy detail query")
        .expect("deploy detail exists");
    assert_eq!(detail.instance_id, "deploy_instance");
    assert_eq!(detail.status, "success");
}

async fn clean_deploy_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM deploy_records WHERE id LIKE 'deploy_%'")
        .execute(pool)
        .await
        .expect("clean deploy records");
    sqlx::query("DELETE FROM instances WHERE id LIKE 'deploy_%'")
        .execute(pool)
        .await
        .expect("clean deploy instances");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'deploy_%'")
        .execute(pool)
        .await
        .expect("clean deploy memberships");
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'deploy_%'")
        .execute(pool)
        .await
        .expect("clean deploy tenants");
    sqlx::query("DELETE FROM users WHERE id LIKE 'deploy_%'")
        .execute(pool)
        .await
        .expect("clean deploy users");
}

async fn seed_deploy_user(pool: &PgPool, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
         ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed deploy user");
}

async fn seed_deploy_tenant(pool: &PgPool, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .execute(pool)
    .await
    .expect("seed deploy tenant");
}

async fn seed_deploy_membership(pool: &PgPool, user_id: &str, tenant_id: &str) {
    let id = format!("deploy_membership_{user_id}_{tenant_id}");
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6) \
         ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(id)
    .bind(user_id)
    .bind(tenant_id)
    .bind("member")
    .bind(json!({}))
    .bind(ts(2026, 2, 1, 0, 0, 0))
    .execute(pool)
    .await
    .expect("seed deploy membership");
}

async fn seed_instance(pool: &PgPool, instance_id: &str, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO instances (id, name, slug, tenant_id, status, created_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, $6, NULL) \
         ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, \
             deleted_at = EXCLUDED.deleted_at",
    )
    .bind(instance_id)
    .bind(format!("Instance {instance_id}"))
    .bind(instance_id)
    .bind(tenant_id)
    .bind("running")
    .bind(ts(2026, 2, 1, 0, 0, 0))
    .execute(pool)
    .await
    .expect("seed deploy instance");
}

async fn seed_deploy(
    pool: &PgPool,
    deploy_id: &str,
    instance_id: &str,
    revision: i32,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO deploy_records \
         (id, instance_id, revision, action, image_version, replicas, config_snapshot, \
          status, message, triggered_by, started_at, finished_at, created_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NULL) \
         ON CONFLICT (id) DO UPDATE SET revision = EXCLUDED.revision, \
             created_at = EXCLUDED.created_at, deleted_at = EXCLUDED.deleted_at",
    )
    .bind(deploy_id)
    .bind(instance_id)
    .bind(revision)
    .bind("update")
    .bind(format!("1.{revision}.0"))
    .bind(3_i32)
    .bind(json!({"cpu_limit": "1000m"}))
    .bind("success")
    .bind("Deploy completed successfully")
    .bind("deploy_user")
    .bind(created_at)
    .bind(created_at)
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed deploy record");
}
