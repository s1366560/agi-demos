use super::support::*;
use agistack_adapters_postgres::{CreateSchemaEdgeMap, CreateSchemaType, UpdateSchemaType};

#[tokio::test]
async fn project_schema_lists_are_project_scoped() {
    let Some(pool) = pool_or_skip("project_schema_lists_are_project_scoped").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_schema_rows(&pool).await;
    seed_schema_type(
        &pool,
        "entity_type_person",
        "entity_types",
        "schema_project",
        "Person",
    )
    .await;
    seed_schema_type(
        &pool,
        "entity_type_other",
        "entity_types",
        "schema_other_project",
        "Other",
    )
    .await;
    seed_schema_type(
        &pool,
        "edge_type_works_at",
        "edge_types",
        "schema_project",
        "WORKS_AT",
    )
    .await;
    seed_schema_type(
        &pool,
        "edge_type_other",
        "edge_types",
        "schema_other_project",
        "OTHER_EDGE",
    )
    .await;
    seed_schema_map(
        &pool,
        "edge_map_person_company",
        "schema_project",
        "Person",
        "Company",
        "WORKS_AT",
    )
    .await;
    seed_schema_map(
        &pool,
        "edge_map_other",
        "schema_other_project",
        "Other",
        "Other",
        "OTHER_EDGE",
    )
    .await;

    let repo = PgSchemaRepository::new(pool.clone());
    let entity_types = repo
        .list_entity_types("schema_project")
        .await
        .expect("entity type query succeeds");
    let edge_types = repo
        .list_edge_types("schema_project")
        .await
        .expect("edge type query succeeds");
    let edge_maps = repo
        .list_edge_maps("schema_project")
        .await
        .expect("edge map query succeeds");

    assert_eq!(entity_types.len(), 1);
    assert_eq!(entity_types[0].id, "entity_type_person");
    assert_eq!(entity_types[0].schema_json, json!({"required": ["name"]}));
    assert_eq!(edge_types.len(), 1);
    assert_eq!(edge_types[0].id, "edge_type_works_at");
    assert_eq!(edge_maps.len(), 1);
    assert_eq!(edge_maps[0].source_type, "Person");
    assert_eq!(edge_maps[0].target_type, "Company");
}

#[tokio::test]
async fn project_schema_crud_enforces_python_write_roles() {
    let Some(pool) = pool_or_skip("project_schema_crud_enforces_python_write_roles").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_schema_rows(&pool).await;
    seed_schema_access(&pool, "schema_owner", "schema_project_write", "owner").await;
    seed_schema_access(&pool, "schema_admin", "schema_project_write", "admin").await;
    seed_schema_access(&pool, "schema_member", "schema_project_write", "member").await;
    seed_schema_access(&pool, "schema_editor", "schema_project_write", "editor").await;
    seed_schema_access(&pool, "schema_viewer", "schema_project_write", "viewer").await;

    let repo = PgSchemaRepository::new(pool.clone());
    assert!(repo
        .user_can_write_schema("schema_owner", "schema_project_write")
        .await
        .expect("owner access check"));
    assert!(repo
        .user_can_write_schema("schema_admin", "schema_project_write")
        .await
        .expect("admin access check"));
    assert!(repo
        .user_can_write_schema("schema_member", "schema_project_write")
        .await
        .expect("member access check"));
    assert!(!repo
        .user_can_write_schema("schema_editor", "schema_project_write")
        .await
        .expect("editor access check"));
    assert!(!repo
        .user_can_write_schema("schema_viewer", "schema_project_write")
        .await
        .expect("viewer access check"));

    let entity_schema = json!({"required": ["name"]});
    let created_entity = repo
        .create_entity_type(CreateSchemaType {
            id: "entity_type_created",
            project_id: "schema_project_write",
            name: "Person",
            description: Some("Human"),
            schema_json: &entity_schema,
        })
        .await
        .expect("create entity type");
    assert_eq!(created_entity.name, "Person");
    assert_eq!(created_entity.status, "ENABLED");
    assert_eq!(created_entity.source, "user");
    assert!(created_entity.updated_at.is_none());
    assert!(repo
        .entity_type_name_exists("schema_project_write", "Person")
        .await
        .expect("entity duplicate check"));

    let updated_schema = json!({"required": ["name", "email"]});
    let updated_entity = repo
        .update_entity_type(
            "schema_project_write",
            "entity_type_created",
            UpdateSchemaType {
                description: Some("Updated person"),
                schema_json: Some(&updated_schema),
            },
        )
        .await
        .expect("update entity type")
        .expect("entity type exists");
    assert_eq!(
        updated_entity.description.as_deref(),
        Some("Updated person")
    );
    assert_eq!(updated_entity.schema_json, updated_schema);
    let updated_at = updated_entity.updated_at.expect("update marks updated_at");

    let noop_update = repo
        .update_entity_type(
            "schema_project_write",
            "entity_type_created",
            UpdateSchemaType {
                description: None,
                schema_json: None,
            },
        )
        .await
        .expect("noop update entity type")
        .expect("entity type exists");
    assert_eq!(noop_update.updated_at, Some(updated_at));
    assert!(repo
        .delete_entity_type("schema_project_write", "entity_type_created")
        .await
        .expect("delete entity type"));
    assert!(!repo
        .delete_entity_type("schema_project_write", "entity_type_created")
        .await
        .expect("delete missing entity type"));

    let edge_schema = json!({});
    let created_edge = repo
        .create_edge_type(CreateSchemaType {
            id: "edge_type_created",
            project_id: "schema_project_write",
            name: "WORKS_AT",
            description: None,
            schema_json: &edge_schema,
        })
        .await
        .expect("create edge type");
    assert_eq!(created_edge.name, "WORKS_AT");
    assert!(repo
        .edge_type_name_exists("schema_project_write", "WORKS_AT")
        .await
        .expect("edge duplicate check"));

    let created_map = repo
        .create_edge_map(CreateSchemaEdgeMap {
            id: "edge_map_created",
            project_id: "schema_project_write",
            source_type: "Person",
            target_type: "Company",
            edge_type: "WORKS_AT",
        })
        .await
        .expect("create edge map");
    assert_eq!(created_map.status, "ENABLED");
    assert_eq!(created_map.source, "user");
    assert!(repo
        .edge_map_exists("schema_project_write", "Person", "Company", "WORKS_AT")
        .await
        .expect("edge map duplicate check"));
    assert!(repo
        .delete_edge_map("schema_project_write", "edge_map_created")
        .await
        .expect("delete edge map"));
    assert!(!repo
        .delete_edge_map("schema_project_write", "edge_map_created")
        .await
        .expect("delete missing edge map"));
    assert!(repo
        .delete_edge_type("schema_project_write", "edge_type_created")
        .await
        .expect("delete edge type"));
}

async fn clean_schema_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM edge_type_maps WHERE id LIKE 'edge_map_%'")
        .execute(pool)
        .await
        .expect("clean edge type maps");
    sqlx::query("DELETE FROM edge_types WHERE id LIKE 'edge_type_%'")
        .execute(pool)
        .await
        .expect("clean edge types");
    sqlx::query("DELETE FROM entity_types WHERE id LIKE 'entity_type_%'")
        .execute(pool)
        .await
        .expect("clean entity types");
    sqlx::query("DELETE FROM user_projects WHERE project_id LIKE 'schema_project%'")
        .execute(pool)
        .await
        .expect("clean schema user projects");
}

async fn seed_schema_access(pool: &PgPool, user_id: &str, project_id: &str, role: &str) {
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ($1, $2, $3) \
         ON CONFLICT (user_id, project_id) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(user_id)
    .bind(project_id)
    .bind(role)
    .execute(pool)
    .await
    .expect("seed schema access");
}

async fn seed_schema_type(pool: &PgPool, id: &str, table: &str, project_id: &str, name: &str) {
    let sql = format!(
        "INSERT INTO {table} \
         (id, project_id, name, description, schema, status, source, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) \
         ON CONFLICT (id) DO UPDATE SET project_id = EXCLUDED.project_id"
    );
    sqlx::query(&sql)
        .bind(id)
        .bind(project_id)
        .bind(name)
        .bind(format!("{name} description"))
        .bind(json!({"required": ["name"]}))
        .bind("ENABLED")
        .bind("user")
        .bind(ts(2026, 1, 1, 0, 0, 0))
        .bind(ts(2026, 1, 2, 0, 0, 0))
        .execute(pool)
        .await
        .expect("seed schema type");
}

async fn seed_schema_map(
    pool: &PgPool,
    id: &str,
    project_id: &str,
    source_type: &str,
    target_type: &str,
    edge_type: &str,
) {
    sqlx::query(
        "INSERT INTO edge_type_maps \
         (id, project_id, source_type, target_type, edge_type, status, source, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8) \
         ON CONFLICT (id) DO UPDATE SET project_id = EXCLUDED.project_id",
    )
    .bind(id)
    .bind(project_id)
    .bind(source_type)
    .bind(target_type)
    .bind(edge_type)
    .bind("ENABLED")
    .bind("user")
    .bind(ts(2026, 1, 1, 0, 0, 0))
    .execute(pool)
    .await
    .expect("seed schema map");
}
