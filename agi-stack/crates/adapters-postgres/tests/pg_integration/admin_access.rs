use super::support::*;

#[tokio::test]
async fn admin_access_repository_matches_python_admin_gate() {
    let Some(pool) = pool_or_skip("admin access repository").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    clean_admin_dlq_access_rows(&pool).await;

    for (user_id, is_superuser) in [
        ("admin_dlq_super", true),
        ("admin_dlq_role", false),
        ("admin_dlq_member", false),
    ] {
        sqlx::query(
            "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
             ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
        )
        .bind(user_id)
        .bind(format!("{user_id}@example.test"))
        .bind(is_superuser)
        .execute(&pool)
        .await
        .expect("seed admin access user");
    }

    sqlx::query(
        "INSERT INTO roles (id, name, description) VALUES ($1, $2, $3) \
         ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description",
    )
    .bind("admin_dlq_role_admin")
    .bind("admin")
    .bind("Administrator")
    .execute(&pool)
    .await
    .expect("seed admin role");
    let (role_id,) = sqlx::query_as::<_, (String,)>("SELECT id FROM roles WHERE name = $1")
        .bind("admin")
        .fetch_one(&pool)
        .await
        .expect("read admin role id");
    sqlx::query(
        "INSERT INTO user_roles (id, user_id, role_id, tenant_id) VALUES ($1, $2, $3, NULL) \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id, role_id = EXCLUDED.role_id",
    )
    .bind("admin_dlq_role_binding")
    .bind("admin_dlq_role")
    .bind(role_id)
    .execute(&pool)
    .await
    .expect("seed admin role binding");

    let repo = PgAdminAccessRepository::new(pool.clone());
    assert!(repo
        .user_has_admin_access("admin_dlq_super")
        .await
        .expect("superuser access"));
    assert!(repo
        .user_has_admin_access("admin_dlq_role")
        .await
        .expect("role access"));
    assert!(!repo
        .user_has_admin_access("admin_dlq_member")
        .await
        .expect("member access"));
    assert!(!repo
        .user_has_admin_access("admin_dlq_missing")
        .await
        .expect("missing user access"));

    clean_admin_dlq_access_rows(&pool).await;
}

async fn clean_admin_dlq_access_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM user_roles WHERE id LIKE 'admin_dlq_%'")
        .execute(pool)
        .await
        .expect("clean admin dlq role bindings");
    sqlx::query("DELETE FROM users WHERE id LIKE 'admin_dlq_%'")
        .execute(pool)
        .await
        .expect("clean admin dlq users");
}
