//! Query the production adapter against connection-local fixtures only.
use agistack_adapters_postgres::PgUserStore;
use sqlx::postgres::PgPoolOptions;

#[tokio::test]
async fn current_user_global_roles_require_both_scope_columns_to_be_null() {
    let Ok(url) = std::env::var("AGISTACK_TEST_DATABASE_URL") else {
        return;
    };
    // A single physical connection keeps pg_temp fixtures separate from application tables.
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .max_lifetime(None)
        .idle_timeout(None)
        .connect(&url)
        .await
        .expect("test Postgres must be available");
    for statement in [
        "CREATE TEMP TABLE users (id text PRIMARY KEY, email text NOT NULL, full_name text, \
         is_active bool NOT NULL, is_superuser bool NOT NULL, created_at timestamptz NOT NULL, \
         profile jsonb NOT NULL, preferred_language text)",
        "CREATE TEMP TABLE roles (id text PRIMARY KEY, name text NOT NULL)",
        "CREATE TEMP TABLE user_roles (user_id text NOT NULL, role_id text NOT NULL, \
         tenant_id text, project_id text)",
        "INSERT INTO users VALUES \
         ('scoped', 'scoped@example.test', NULL, true, false, NOW(), '{}', NULL), \
         ('superuser', 'superuser@example.test', NULL, true, true, NOW(), '{}', NULL), \
         ('unassigned', 'unassigned@example.test', NULL, true, false, NOW(), '{}', NULL)",
        "INSERT INTO roles VALUES ('admin', 'admin'), ('global', 'auditor'), ('project', 'writer')",
        "INSERT INTO user_roles VALUES \
         ('scoped', 'admin', 'tenant', NULL), \
         ('scoped', 'project', NULL, 'project'), \
         ('scoped', 'global', NULL, NULL), \
         ('superuser', 'admin', 'tenant', 'project')",
    ] {
        sqlx::query(statement).execute(&pool).await.unwrap();
    }
    let users = PgUserStore::new(pool.clone());
    let scoped = users
        .find_current_user_by_id("scoped")
        .await
        .unwrap()
        .unwrap();
    assert_eq!(scoped.roles, vec!["admin", "auditor", "writer"]);
    assert_eq!(scoped.global_roles, vec!["auditor"]);
    assert!(!scoped.is_superuser);

    let superuser = users
        .find_current_user_by_id("superuser")
        .await
        .unwrap()
        .unwrap();
    assert_eq!(superuser.roles, vec!["admin"]);
    assert!(superuser.global_roles.is_empty());
    assert!(superuser.is_superuser);

    let unassigned = users
        .find_current_user_by_id("unassigned")
        .await
        .unwrap()
        .unwrap();
    assert!(unassigned.roles.is_empty());
    assert!(unassigned.global_roles.is_empty());
    assert!(!unassigned.is_superuser);
    assert!(users
        .find_current_user_by_id("missing")
        .await
        .unwrap()
        .is_none());
    pool.close().await;
}
