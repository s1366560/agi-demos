use super::support::*;

#[tokio::test]
async fn subagent_template_categories_are_published_tenant_scoped_and_sorted() {
    let Some(pool) =
        pool_or_skip("subagent_template_categories_are_published_tenant_scoped_and_sorted").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_subagent_template_rows(&pool).await;

    seed_subagent_template(&pool, "subagent_tpl_1", "subagent_tenant", "research", true).await;
    seed_subagent_template(
        &pool,
        "subagent_tpl_2",
        "subagent_tenant",
        "development",
        true,
    )
    .await;
    seed_subagent_template(&pool, "subagent_tpl_3", "subagent_tenant", "research", true).await;
    seed_subagent_template(
        &pool,
        "subagent_tpl_unpublished",
        "subagent_tenant",
        "hidden",
        false,
    )
    .await;
    seed_subagent_template(
        &pool,
        "subagent_tpl_other",
        "subagent_other_tenant",
        "other",
        true,
    )
    .await;

    let repo = PgSubagentTemplateRepository::new(pool.clone());
    let categories = repo
        .list_categories("subagent_tenant")
        .await
        .expect("subagent template category query succeeds");

    assert_eq!(
        categories,
        vec!["development".to_string(), "research".to_string()]
    );
}

async fn clean_subagent_template_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM subagent_templates WHERE id LIKE 'subagent_tpl_%'")
        .execute(pool)
        .await
        .expect("clean subagent template rows");
}

async fn seed_subagent_template(
    pool: &PgPool,
    id: &str,
    tenant_id: &str,
    category: &str,
    is_published: bool,
) {
    sqlx::query(
        "INSERT INTO subagent_templates \
         (id, tenant_id, name, version, category, system_prompt, is_published) \
         VALUES ($1, $2, $3, '1.0.0', $4, 'system prompt', $5) \
         ON CONFLICT (id) DO UPDATE SET \
            tenant_id = EXCLUDED.tenant_id, \
            category = EXCLUDED.category, \
            is_published = EXCLUDED.is_published",
    )
    .bind(id)
    .bind(tenant_id)
    .bind(id)
    .bind(category)
    .bind(is_published)
    .execute(pool)
    .await
    .expect("seed subagent template");
}
