use agistack_adapters_postgres::{
    BackendStoreAccessError, BackendStoreCreate, BackendStoreUpdate, PgGraphStoreRepository,
    PgRetrievalStoreRepository,
};

use super::support::*;

const ENCRYPTION_KEY: &str = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
const ENCRYPTED_CONFIG: &str = concat!(
    "AAECAwQFBgcICQoLPCCjaazH+DnvLvv/i8ZXCeH44kyRFi8QXV3SsyVeIp4jYM+P",
    "3LZ96hCGRc/74ktKiy1CoXi4xqlL8k47IpjXj4BVmRG2qARbPj+IE5IaTk/sVMQFT2DgtWaO9PXs"
);

#[tokio::test]
async fn backend_store_repositories_match_python_schema_access_and_decrypt() {
    let Some(pool) =
        pool_or_skip("backend_store_repositories_match_python_schema_access_and_decrypt").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_backend_store_rows(&pool).await;
    std::env::set_var("LLM_ENCRYPTION_KEY", ENCRYPTION_KEY);

    seed_backend_user(&pool, "backend_store_user", false).await;
    seed_backend_user(&pool, "backend_store_stranger", false).await;
    seed_backend_user(&pool, "backend_store_global_admin", false).await;
    seed_backend_user(&pool, "backend_store_no_tenant", false).await;
    seed_backend_tenant(&pool, "backend_store_tenant_a").await;
    seed_backend_tenant(&pool, "backend_store_tenant_b").await;
    seed_backend_membership(
        &pool,
        "backend_store_membership_a",
        "backend_store_user",
        "backend_store_tenant_a",
        ts(2026, 4, 1, 0, 0, 0),
    )
    .await;
    seed_backend_membership(
        &pool,
        "backend_store_membership_b",
        "backend_store_user",
        "backend_store_tenant_b",
        ts(2026, 4, 2, 0, 0, 0),
    )
    .await;
    seed_system_admin_role(&pool, "backend_store_global_admin").await;

    seed_backend_store(
        &pool,
        "graph_stores",
        BackendStoreSeed {
            id: "backend_store_graph_old",
            tenant_id: "backend_store_tenant_a",
            name: "Old graph",
            engine_type: "neo4j",
            created_at: ts(2026, 4, 3, 0, 0, 0),
            index_config: json!({"label": "old"}),
            deleted: false,
        },
    )
    .await;
    seed_backend_store(
        &pool,
        "graph_stores",
        BackendStoreSeed {
            id: "backend_store_graph_latest",
            tenant_id: "backend_store_tenant_a",
            name: "Latest graph",
            engine_type: "arcadedb",
            created_at: ts(2026, 4, 4, 0, 0, 0),
            index_config: json!({"label": "latest", "dims": 1536}),
            deleted: false,
        },
    )
    .await;
    seed_backend_store(
        &pool,
        "graph_stores",
        BackendStoreSeed {
            id: "backend_store_graph_deleted",
            tenant_id: "backend_store_tenant_a",
            name: "Deleted graph",
            engine_type: "neo4j",
            created_at: ts(2026, 4, 5, 0, 0, 0),
            index_config: json!({}),
            deleted: true,
        },
    )
    .await;
    seed_backend_store(
        &pool,
        "graph_stores",
        BackendStoreSeed {
            id: "backend_store_graph_other_tenant",
            tenant_id: "backend_store_tenant_b",
            name: "Other graph",
            engine_type: "neo4j",
            created_at: ts(2026, 4, 6, 0, 0, 0),
            index_config: json!({}),
            deleted: false,
        },
    )
    .await;

    seed_backend_store(
        &pool,
        "retrieval_stores",
        BackendStoreSeed {
            id: "backend_store_retrieval_latest",
            tenant_id: "backend_store_tenant_a",
            name: "Latest retrieval",
            engine_type: "weknora_remote",
            created_at: ts(2026, 4, 7, 0, 0, 0),
            index_config: json!({"search_path": "/knowledge-search"}),
            deleted: false,
        },
    )
    .await;
    seed_backend_store(
        &pool,
        "retrieval_stores",
        BackendStoreSeed {
            id: "backend_store_retrieval_deleted",
            tenant_id: "backend_store_tenant_a",
            name: "Deleted retrieval",
            engine_type: "qdrant",
            created_at: ts(2026, 4, 8, 0, 0, 0),
            index_config: json!({}),
            deleted: true,
        },
    )
    .await;
    seed_backend_store(
        &pool,
        "retrieval_stores",
        BackendStoreSeed {
            id: "backend_store_retrieval_other_tenant",
            tenant_id: "backend_store_tenant_b",
            name: "Other retrieval",
            engine_type: "milvus",
            created_at: ts(2026, 4, 9, 0, 0, 0),
            index_config: json!({}),
            deleted: false,
        },
    )
    .await;

    let graph_repo = PgGraphStoreRepository::new(pool.clone());
    assert_eq!(
        graph_repo
            .resolve_selected_tenant("backend_store_user", None)
            .await
            .expect("default tenant query"),
        Ok("backend_store_tenant_a".to_string())
    );
    assert_eq!(
        graph_repo
            .resolve_selected_tenant("backend_store_user", Some("backend_store_missing"))
            .await
            .expect("missing tenant access query"),
        Err(BackendStoreAccessError::TenantNotFound)
    );
    assert_eq!(
        graph_repo
            .resolve_selected_tenant("backend_store_stranger", Some("backend_store_tenant_a"))
            .await
            .expect("forbidden tenant access query"),
        Err(BackendStoreAccessError::TenantAccessRequired)
    );
    assert_eq!(
        graph_repo
            .resolve_selected_tenant("backend_store_global_admin", Some("backend_store_tenant_b"))
            .await
            .expect("global admin tenant access query"),
        Ok("backend_store_tenant_b".to_string())
    );
    assert_eq!(
        graph_repo
            .resolve_selected_tenant("backend_store_no_tenant", None)
            .await
            .expect("no tenant access query"),
        Err(BackendStoreAccessError::UserHasNoTenant)
    );
    assert_eq!(
        graph_repo
            .resolve_selected_tenant_for_admin("backend_store_user", None)
            .await
            .expect("member admin access query"),
        Err(BackendStoreAccessError::AdminAccessRequired)
    );
    assert_eq!(
        graph_repo
            .resolve_selected_tenant_for_admin(
                "backend_store_global_admin",
                Some("backend_store_tenant_b")
            )
            .await
            .expect("global admin write tenant access query"),
        Ok("backend_store_tenant_b".to_string())
    );

    let graph_rows = graph_repo
        .list_stores("backend_store_tenant_a", 10, 0)
        .await
        .expect("graph list succeeds");
    assert_eq!(
        graph_rows
            .iter()
            .map(|store| store.id.as_str())
            .collect::<Vec<_>>(),
        vec!["backend_store_graph_latest", "backend_store_graph_old"]
    );
    assert_eq!(graph_rows[0].engine_type, "arcadedb");
    assert_eq!(
        graph_rows[0].connection_config_json["uri"],
        "bolt://db.example:7687"
    );
    assert_eq!(graph_rows[0].connection_config_json["password"], "secret");
    assert_eq!(graph_rows[0].index_config_json["dims"], 1536);
    assert_eq!(graph_rows[0].health_status.as_deref(), Some("healthy"));
    assert_eq!(graph_rows[0].detected_version.as_deref(), Some("2026.04"));

    let graph_page = graph_repo
        .list_stores("backend_store_tenant_a", 1, 1)
        .await
        .expect("graph list page succeeds");
    assert_eq!(graph_page[0].id, "backend_store_graph_old");

    let graph_detail = graph_repo
        .get_store("backend_store_tenant_a", "backend_store_graph_latest")
        .await
        .expect("graph detail succeeds")
        .expect("graph detail exists");
    assert_eq!(graph_detail.name, "Latest graph");
    assert_eq!(graph_detail.index_config_json["label"], "latest");
    assert!(graph_repo
        .get_store("backend_store_tenant_a", "backend_store_graph_other_tenant")
        .await
        .expect("wrong tenant graph detail succeeds")
        .is_none());
    assert!(graph_repo
        .get_store("backend_store_tenant_a", "backend_store_graph_deleted")
        .await
        .expect("deleted graph detail succeeds")
        .is_none());

    let retrieval_repo = PgRetrievalStoreRepository::new(pool.clone());
    let retrieval_rows = retrieval_repo
        .list_stores("backend_store_tenant_a", 10, 0)
        .await
        .expect("retrieval list succeeds");
    assert_eq!(
        retrieval_rows
            .iter()
            .map(|store| store.id.as_str())
            .collect::<Vec<_>>(),
        vec!["backend_store_retrieval_latest"]
    );
    assert_eq!(retrieval_rows[0].engine_type, "weknora_remote");
    assert_eq!(
        retrieval_rows[0].index_config_json["search_path"],
        "/knowledge-search"
    );

    let retrieval_detail = retrieval_repo
        .get_store("backend_store_tenant_a", "backend_store_retrieval_latest")
        .await
        .expect("retrieval detail succeeds")
        .expect("retrieval detail exists");
    assert_eq!(
        retrieval_detail.connection_config_json["nested"]["api_key"],
        "k"
    );
    assert!(retrieval_repo
        .get_store(
            "backend_store_tenant_a",
            "backend_store_retrieval_other_tenant"
        )
        .await
        .expect("wrong tenant retrieval detail succeeds")
        .is_none());
}

#[tokio::test]
async fn backend_store_repositories_create_update_count_and_soft_delete() {
    let Some(pool) =
        pool_or_skip("backend_store_repositories_create_update_count_and_soft_delete").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_project_read_tables(&pool).await;
    clean_backend_store_rows(&pool).await;
    std::env::set_var("LLM_ENCRYPTION_KEY", ENCRYPTION_KEY);

    seed_backend_user(&pool, "backend_store_writer", false).await;
    seed_backend_tenant(&pool, "backend_store_tenant_a").await;
    seed_backend_membership(
        &pool,
        "backend_store_membership_writer",
        "backend_store_writer",
        "backend_store_tenant_a",
        ts(2026, 5, 1, 0, 0, 0),
    )
    .await;
    seed_system_admin_role(&pool, "backend_store_writer").await;

    let graph_repo = PgGraphStoreRepository::new(pool.clone());
    let graph = graph_repo
        .create_store(BackendStoreCreate {
            tenant_id: "backend_store_tenant_a".to_string(),
            name: "Managed graph".to_string(),
            engine_type: "neo4j".to_string(),
            connection_config_json: json!({
                "uri": "bolt://graph.example:7687",
                "password": "secret"
            }),
            index_config_json: json!({ "database": "neo4j" }),
            created_by: "backend_store_writer".to_string(),
        })
        .await
        .expect("graph create succeeds");
    assert_eq!(graph.status, "disconnected");
    assert_eq!(graph.connection_config_json["password"], "secret");
    assert_eq!(graph.index_config_json["database"], "neo4j");

    let (encrypted_graph_config,): (Option<String>,) =
        sqlx::query_as("SELECT connection_config_encrypted FROM graph_stores WHERE id = $1")
            .bind(&graph.id)
            .fetch_one(&pool)
            .await
            .expect("read encrypted graph config");
    let encrypted_graph_config = encrypted_graph_config.expect("graph config encrypted");
    assert!(!encrypted_graph_config.contains("secret"));
    assert_ne!(encrypted_graph_config, ENCRYPTED_CONFIG);

    assert_eq!(
        graph_repo
            .find_by_name("backend_store_tenant_a", "Managed graph")
            .await
            .expect("find graph by name")
            .expect("graph name exists")
            .id,
        graph.id
    );

    let updated_graph = graph_repo
        .update_store(
            "backend_store_tenant_a",
            &graph.id,
            BackendStoreUpdate {
                name: Some("Managed graph updated".to_string()),
                connection_config_json: Some(json!({
                    "uri": "bolt://graph-2.example:7687",
                    "password": "new-secret"
                })),
                index_config_json: Some(json!({ "database": "neo4j2" })),
            },
        )
        .await
        .expect("graph update succeeds")
        .expect("graph update returns row");
    assert_eq!(updated_graph.name, "Managed graph updated");
    assert_eq!(
        updated_graph.connection_config_json["uri"],
        "bolt://graph-2.example:7687"
    );
    assert_eq!(
        updated_graph.connection_config_json["password"],
        "new-secret"
    );
    assert_eq!(updated_graph.index_config_json["database"], "neo4j2");
    assert!(updated_graph.updated_at.is_some());

    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id, graph_store_id) \
         VALUES ($1, $2, $3, $4, $5)",
    )
    .bind("backend_store_project_graph_bound")
    .bind("backend_store_tenant_a")
    .bind("Graph bound project")
    .bind("backend_store_writer")
    .bind(&graph.id)
    .execute(&pool)
    .await
    .expect("seed graph-bound project");
    assert_eq!(
        graph_repo
            .count_projects_bound(&graph.id)
            .await
            .expect("count graph bindings"),
        1
    );
    sqlx::query("DELETE FROM projects WHERE id = $1")
        .bind("backend_store_project_graph_bound")
        .execute(&pool)
        .await
        .expect("remove graph-bound project");
    assert!(graph_repo
        .soft_delete("backend_store_tenant_a", &graph.id)
        .await
        .expect("graph soft delete succeeds"));
    assert!(graph_repo
        .get_store("backend_store_tenant_a", &graph.id)
        .await
        .expect("read deleted graph")
        .is_none());

    let retrieval_repo = PgRetrievalStoreRepository::new(pool.clone());
    let retrieval = retrieval_repo
        .create_store(BackendStoreCreate {
            tenant_id: "backend_store_tenant_a".to_string(),
            name: "Managed retrieval".to_string(),
            engine_type: "weknora_remote".to_string(),
            connection_config_json: json!({
                "base_url": "https://retrieval.example",
                "api_key": "secret",
                "knowledge_base_id": "kb-1"
            }),
            index_config_json: json!({ "search_path": "/knowledge-search" }),
            created_by: "backend_store_writer".to_string(),
        })
        .await
        .expect("retrieval create succeeds");
    assert_eq!(retrieval.status, "disconnected");
    assert_eq!(retrieval.connection_config_json["api_key"], "secret");

    let updated_retrieval = retrieval_repo
        .update_store(
            "backend_store_tenant_a",
            &retrieval.id,
            BackendStoreUpdate {
                name: Some("Managed retrieval updated".to_string()),
                connection_config_json: Some(json!({
                    "base_url": "https://retrieval-2.example",
                    "api_key": "new-secret",
                    "knowledge_base_ids": ["kb-2"]
                })),
                index_config_json: Some(json!({ "index_path": "/index" })),
            },
        )
        .await
        .expect("retrieval update succeeds")
        .expect("retrieval update returns row");
    assert_eq!(updated_retrieval.name, "Managed retrieval updated");
    assert_eq!(
        updated_retrieval.connection_config_json["base_url"],
        "https://retrieval-2.example"
    );
    assert_eq!(
        updated_retrieval.connection_config_json["api_key"],
        "new-secret"
    );
    assert!(updated_retrieval.updated_at.is_some());

    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id, retrieval_store_id) \
         VALUES ($1, $2, $3, $4, $5)",
    )
    .bind("backend_store_project_retrieval_bound")
    .bind("backend_store_tenant_a")
    .bind("Retrieval bound project")
    .bind("backend_store_writer")
    .bind(&retrieval.id)
    .execute(&pool)
    .await
    .expect("seed retrieval-bound project");
    assert_eq!(
        retrieval_repo
            .count_projects_bound(&retrieval.id)
            .await
            .expect("count retrieval bindings"),
        1
    );
    sqlx::query("DELETE FROM projects WHERE id = $1")
        .bind("backend_store_project_retrieval_bound")
        .execute(&pool)
        .await
        .expect("remove retrieval-bound project");
    assert!(retrieval_repo
        .soft_delete("backend_store_tenant_a", &retrieval.id)
        .await
        .expect("retrieval soft delete succeeds"));
    assert!(retrieval_repo
        .get_store("backend_store_tenant_a", &retrieval.id)
        .await
        .expect("read deleted retrieval")
        .is_none());
}

async fn clean_backend_store_rows(pool: &PgPool) {
    for sql in [
        "DELETE FROM projects WHERE id LIKE 'backend_store_%'",
        "DELETE FROM graph_stores WHERE id LIKE 'backend_store_%'",
        "DELETE FROM retrieval_stores WHERE id LIKE 'backend_store_%'",
        "DELETE FROM user_roles WHERE id LIKE 'backend_store_%'",
        "DELETE FROM user_tenants WHERE id LIKE 'backend_store_%'",
        "DELETE FROM users WHERE id LIKE 'backend_store_%'",
        "DELETE FROM tenants WHERE id LIKE 'backend_store_%'",
    ] {
        sqlx::query(sql)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("clean backend store rows failed: {sql}\n{e}"));
    }
}

async fn seed_backend_user(pool: &PgPool, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
         ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.com"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed backend store user");
}

async fn seed_backend_tenant(pool: &PgPool, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(tenant_id)
    .bind(format!("Tenant {tenant_id}"))
    .execute(pool)
    .await
    .expect("seed backend store tenant");
}

async fn seed_backend_membership(
    pool: &PgPool,
    id: &str,
    user_id: &str,
    tenant_id: &str,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, created_at) \
         VALUES ($1, $2, $3, 'member', $4) \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id, \
            tenant_id = EXCLUDED.tenant_id, created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(user_id)
    .bind(tenant_id)
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed backend store tenant membership");
}

async fn seed_system_admin_role(pool: &PgPool, user_id: &str) {
    let (role_id,) = sqlx::query_as::<_, (String,)>(
        "INSERT INTO roles (id, name, description) VALUES ($1, 'system_admin', 'System admin') \
         ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description \
         RETURNING id",
    )
    .bind("backend_store_role_system_admin")
    .fetch_one(pool)
    .await
    .expect("seed backend store system admin role");

    sqlx::query(
        "INSERT INTO user_roles (id, user_id, role_id, tenant_id) VALUES ($1, $2, $3, NULL) \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id, role_id = EXCLUDED.role_id",
    )
    .bind(format!("backend_store_role_binding_{user_id}"))
    .bind(user_id)
    .bind(role_id)
    .execute(pool)
    .await
    .expect("seed backend store system admin binding");
}

struct BackendStoreSeed {
    id: &'static str,
    tenant_id: &'static str,
    name: &'static str,
    engine_type: &'static str,
    created_at: DateTime<Utc>,
    index_config: serde_json::Value,
    deleted: bool,
}

async fn seed_backend_store(pool: &PgPool, table: &str, seed: BackendStoreSeed) {
    let deleted_at = seed.deleted.then_some(ts(2026, 4, 10, 0, 0, 0));
    let sql = format!(
        "INSERT INTO {table} \
         (id, tenant_id, name, engine_type, connection_config_encrypted, index_config, status, \
          health_status, detected_version, created_at, updated_at, deleted_at) \
         VALUES ($1, $2, $3, $4, $5, $6, 'connected', 'healthy', '2026.04', $7, $8, $9) \
         ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, \
            name = EXCLUDED.name, engine_type = EXCLUDED.engine_type, \
            connection_config_encrypted = EXCLUDED.connection_config_encrypted, \
            index_config = EXCLUDED.index_config, status = EXCLUDED.status, \
            health_status = EXCLUDED.health_status, detected_version = EXCLUDED.detected_version, \
            created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at, \
            deleted_at = EXCLUDED.deleted_at"
    );
    sqlx::query(&sql)
        .bind(seed.id)
        .bind(seed.tenant_id)
        .bind(seed.name)
        .bind(seed.engine_type)
        .bind(ENCRYPTED_CONFIG)
        .bind(seed.index_config)
        .bind(seed.created_at)
        .bind(Some(ts(2026, 4, 11, 0, 0, 0)))
        .bind(deleted_at)
        .execute(pool)
        .await
        .unwrap_or_else(|e| panic!("seed backend store row failed: {table}/{}\n{e}", seed.id));
}
