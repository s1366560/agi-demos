use super::support::*;

#[tokio::test]
async fn project_store_splits_read_write_and_admin_access() {
    let Some(pool) = pool_or_skip("project_store_splits_read_write_and_admin_access").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;

    for sql in [
        "DELETE FROM user_tenants WHERE user_id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
        "DELETE FROM user_projects WHERE user_id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
        "DELETE FROM projects WHERE id IN \
         ('p_owned_authz', 'p_viewer_authz', 'p_admin_authz', 'p_public_authz', 'p_tenant_authz')",
        "DELETE FROM tenants WHERE id = 't_authz'",
        "DELETE FROM users WHERE id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_authz', 'T')")
        .execute(&pool)
        .await
        .unwrap();
    for user_id in [
        "u_owner_authz",
        "u_viewer_authz",
        "u_admin_authz",
        "u_public_authz",
        "u_tenant_authz",
    ] {
        sqlx::query("INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, false)")
            .bind(user_id)
            .bind(format!("{user_id}@x"))
            .execute(&pool)
            .await
            .unwrap();
    }
    for (project_id, is_public) in [
        ("p_owned_authz", false),
        ("p_viewer_authz", false),
        ("p_admin_authz", false),
        ("p_public_authz", true),
        ("p_tenant_authz", false),
    ] {
        sqlx::query(
            "INSERT INTO projects (id, tenant_id, name, owner_id, is_public) \
             VALUES ($1, 't_authz', $2, 'u_owner_authz', $3)",
        )
        .bind(project_id)
        .bind(project_id)
        .bind(is_public)
        .execute(&pool)
        .await
        .unwrap();
    }
    for (user_id, project_id, role) in [
        ("u_viewer_authz", "p_viewer_authz", "viewer"),
        ("u_admin_authz", "p_admin_authz", "admin"),
    ] {
        sqlx::query("INSERT INTO user_projects (user_id, project_id, role) VALUES ($1, $2, $3)")
            .bind(user_id)
            .bind(project_id)
            .bind(role)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_authz', 'u_tenant_authz', 't_authz', 'owner')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let projects = PgProjectStore::new(pool.clone());

    let owned = projects
        .find_by_id("p_owned_authz")
        .await
        .unwrap()
        .expect("owned project");
    assert!(projects
        .user_can_access("u_owner_authz", &owned)
        .await
        .unwrap());
    assert!(projects
        .user_can_write("u_owner_authz", &owned)
        .await
        .unwrap());
    assert!(projects
        .user_can_admin("u_owner_authz", &owned)
        .await
        .unwrap());

    let viewer = projects
        .find_by_id("p_viewer_authz")
        .await
        .unwrap()
        .expect("viewer project");
    assert!(projects
        .user_can_access("u_viewer_authz", &viewer)
        .await
        .unwrap());
    assert!(!projects
        .user_can_write("u_viewer_authz", &viewer)
        .await
        .unwrap());
    assert!(!projects
        .user_can_admin("u_viewer_authz", &viewer)
        .await
        .unwrap());

    let admin = projects
        .find_by_id("p_admin_authz")
        .await
        .unwrap()
        .expect("admin project");
    assert!(projects
        .user_can_access("u_admin_authz", &admin)
        .await
        .unwrap());
    assert!(projects
        .user_can_write("u_admin_authz", &admin)
        .await
        .unwrap());
    assert!(projects
        .user_can_admin("u_admin_authz", &admin)
        .await
        .unwrap());

    let public = projects
        .find_by_id("p_public_authz")
        .await
        .unwrap()
        .expect("public project");
    assert!(projects
        .user_can_access("u_public_authz", &public)
        .await
        .unwrap());
    assert!(!projects
        .user_can_write("u_public_authz", &public)
        .await
        .unwrap());
    assert!(!projects
        .user_can_admin("u_public_authz", &public)
        .await
        .unwrap());

    let tenant = projects
        .find_by_id("p_tenant_authz")
        .await
        .unwrap()
        .expect("tenant project");
    assert!(projects
        .user_can_admin("u_tenant_authz", &tenant)
        .await
        .unwrap());
}
