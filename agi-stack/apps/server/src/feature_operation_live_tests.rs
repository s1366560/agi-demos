//! Opt-in, read-only checks against an already migrated shared database.

use super::*;

#[tokio::test]
#[ignore = "requires AGISTACK_FEATURE_TEST_DATABASE_URL for an existing database"]
async fn live_feature_configuration_and_persisted_ancestry() {
    let dsn =
        std::env::var("AGISTACK_FEATURE_TEST_DATABASE_URL").expect("test database configured");
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(&dsn)
        .await
        .expect("test database connection");
    let repository = PgFeatureOperationRepositoryV2(pool.clone());
    let rows: Vec<(String, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT scope_kind, tenant_id, project_id FROM platform_plugin_v2_apply_states WHERE data_plane_id = 'python-api-v2' AND session_id IS NULL",
    ).fetch_all(&pool).await.expect("existing accepted scopes");
    assert!(
        !rows.is_empty(),
        "live check requires existing accepted publications"
    );
    let mut source_count = 0;
    for (kind, tenant_id, project_id) in &rows {
        let scope = ScopeV2 {
            kind: match kind.as_str() {
                "root" => ScopeKindV2::Root,
                "tenant" => ScopeKindV2::Tenant,
                "project" => ScopeKindV2::Project,
                _ => panic!("unexpected scope"),
            },
            tenant_id: tenant_id.clone(),
            project_id: project_id.clone(),
            session_id: None,
        };
        let accepted = repository
            .accepted(&scope)
            .await
            .expect("accepted immutable binding and digest");
        assert!(!matches!(
            accepted,
            AcceptedFeatureConfigurationV2::Standalone
        ));
        if matches!(accepted, AcceptedFeatureConfigurationV2::Source(_)) {
            source_count += 1;
        }
        let entries = feature_entries(accepted, &scope).expect("accepted feature source");
        assert!(entries.contains_key("builtin-web-feature-tenant-skills"));
    }
    for kind in [
        "project",
        "memory",
        "conversation",
        "skill",
        "instance",
        "deploy",
        "cron",
        "channel",
        "webhook",
        "support_ticket",
        "skill_evolution",
    ] {
        repository
            .resource_scope(kind, "00000000-0000-0000-0000-000000000000")
            .await
            .unwrap_or_else(|_| panic!("persisted {kind} scope SQL must remain valid"));
    }
    let member: Option<(String, String, String)> = sqlx::query_as(
        "SELECT up.user_id, p.tenant_id, p.id FROM user_projects up JOIN projects p ON p.id = up.project_id JOIN user_tenants ut ON ut.user_id = up.user_id AND ut.tenant_id = p.tenant_id LIMIT 1",
    ).fetch_optional(&pool).await.expect("member scope query");
    if let Some((user_id, tenant_id, project_id)) = member {
        let scope = ScopeV2 {
            kind: ScopeKindV2::Project,
            tenant_id: Some(tenant_id.clone()),
            project_id: Some(project_id.clone()),
            session_id: None,
        };
        assert!(repository
            .authorize(&user_id, &scope)
            .await
            .expect("scope membership"));
        assert!(repository
            .accessible_projects(&user_id, Some(&tenant_id))
            .await
            .expect("accessible projects")
            .iter()
            .any(|ids| ids.project_id.as_deref() == Some(project_id.as_str())));
        assert!(repository
            .default_tenant(&user_id)
            .await
            .expect("default tenant")
            .is_some());
        repository
            .support_tenants(&user_id, None)
            .await
            .expect("ticket tenant aggregate SQL");
        repository
            .support_tenants(&user_id, Some("open"))
            .await
            .expect("filtered ticket tenant aggregate SQL");
    }
    println!(
        "validated {} accepted scopes, including {source_count} immutable source bindings",
        rows.len()
    );
    pool.close().await;
}
