use super::support::*;
use agistack_adapters_postgres::ProviderHealthRecord;

const PROVIDER_ID: &str = "11111111-2222-4333-8444-555555555555";
const OTHER_PROVIDER_ID: &str = "21111111-2222-4333-8444-555555555555";
const MAPPING_HIGH_PRIORITY_ID: &str = "31111111-2222-4333-8444-555555555555";
const MAPPING_LOW_PRIORITY_ID: &str = "41111111-2222-4333-8444-555555555555";
const MAPPING_MID_PRIORITY_ID: &str = "51111111-2222-4333-8444-555555555555";
const USAGE_FIRST_ID: &str = "61111111-2222-4333-8444-555555555555";
const USAGE_SECOND_ID: &str = "71111111-2222-4333-8444-555555555555";
const USAGE_OTHER_ID: &str = "81111111-2222-4333-8444-555555555555";
const CRUD_OPENAI_NAME: &str = "llm_provider_crud_openai";

#[tokio::test]
async fn llm_provider_latest_health_matches_python_ordering() {
    let Some(pool) = pool_or_skip("llm_provider_latest_health_matches_python_ordering").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_llm_provider_health_rows(&pool).await;
    seed_llm_provider(&pool, PROVIDER_ID, "llm_provider_health_primary").await;
    seed_llm_provider(&pool, OTHER_PROVIDER_ID, "llm_provider_health_other").await;
    seed_provider_health(
        &pool,
        PROVIDER_ID,
        "degraded",
        ts(2026, 1, 1, 0, 0, 0),
        Some("slow"),
        Some(1200),
    )
    .await;
    seed_provider_health(
        &pool,
        PROVIDER_ID,
        "healthy",
        ts(2026, 1, 2, 0, 0, 0),
        None,
        Some(88),
    )
    .await;
    seed_provider_health(
        &pool,
        OTHER_PROVIDER_ID,
        "unhealthy",
        ts(2026, 1, 3, 0, 0, 0),
        Some("other"),
        Some(999),
    )
    .await;

    let repo = PgLlmProviderRepository::new(pool.clone());
    let latest = repo
        .latest_health(PROVIDER_ID)
        .await
        .expect("latest provider health query succeeds")
        .expect("latest provider health exists");

    assert_eq!(latest.provider_id, PROVIDER_ID);
    assert_eq!(latest.status, "healthy");
    assert_eq!(latest.last_check, ts(2026, 1, 2, 0, 0, 0));
    assert_eq!(latest.error_message, None);
    assert_eq!(latest.response_time_ms, Some(88));
    assert!(repo
        .latest_health("31111111-2222-4333-8444-555555555555")
        .await
        .expect("missing provider health query succeeds")
        .is_none());

    let recorded = repo
        .record_health(&ProviderHealthRecord {
            provider_id: PROVIDER_ID.to_string(),
            status: "unhealthy".to_string(),
            last_check: ts(2026, 1, 4, 0, 0, 0),
            error_message: Some("HTTP 401 Unauthorized".to_string()),
            response_time_ms: Some(42),
        })
        .await
        .expect("provider health write succeeds");
    assert_eq!(recorded.status, "unhealthy");
    assert_eq!(
        recorded.error_message.as_deref(),
        Some("HTTP 401 Unauthorized")
    );

    let latest = repo
        .latest_health(PROVIDER_ID)
        .await
        .expect("written provider health query succeeds")
        .expect("written provider health exists");
    assert_eq!(latest, recorded);
}

#[tokio::test]
async fn llm_provider_crud_writes_python_encrypted_metadata_rows() {
    let Some(pool) = pool_or_skip("llm_provider_crud_writes_python_encrypted_metadata_rows").await
    else {
        return;
    };
    let Ok(encryption_key) = std::env::var("LLM_ENCRYPTION_KEY") else {
        eprintln!(
            "[skip] llm_provider_crud_writes_python_encrypted_metadata_rows: LLM_ENCRYPTION_KEY unset"
        );
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_llm_provider_crud_rows(&pool).await;

    let repo = PgLlmProviderRepository::new(pool.clone());
    let created = repo
        .create_provider(&LlmProviderCreateRecord {
            name: CRUD_OPENAI_NAME.to_string(),
            provider_type: "openai".to_string(),
            operation_type: "llm".to_string(),
            api_key_plaintext: "sk-crud-secret-12345".to_string(),
            base_url: None,
            llm_model: Some("gpt-4o".to_string()),
            llm_small_model: Some("gpt-4o-mini".to_string()),
            embedding_model: None,
            reranker_model: None,
            config: json!({"timeout": 30}),
            is_active: true,
            is_default: false,
            is_enabled: true,
            allowed_models: vec!["gpt-4o".to_string()],
            blocked_models: vec!["gpt-3.5".to_string()],
            pool_weight: 2.5,
            pool_enabled: true,
            model_tier: Some("large".to_string()),
            secondary_models: vec!["gpt-4o-mini".to_string()],
        })
        .await
        .expect("provider create succeeds");
    assert_eq!(created.name, CRUD_OPENAI_NAME);
    assert_eq!(created.provider_type, "openai");
    assert_eq!(created.operation_type, "llm");
    assert_eq!(created.llm_model.as_deref(), Some("gpt-4o"));
    assert_eq!(created.allowed_models, vec!["gpt-4o".to_string()]);
    assert_ne!(created.api_key_encrypted, "sk-crud-secret-12345");
    assert_eq!(
        agistack_adapters_secrets::try_decrypt_python_aes256_gcm(
            &created.api_key_encrypted,
            &encryption_key,
        )
        .expect("rust-created provider api key decrypts with python envelope"),
        "sk-crud-secret-12345"
    );

    let listed = repo
        .list_providers(false)
        .await
        .expect("provider list succeeds");
    assert!(listed.iter().any(|record| record.id == created.id));

    let updated = repo
        .update_provider(
            &created.id,
            &LlmProviderUpdateRecord {
                expected_updated_at: created.updated_at,
                name: Some("llm_provider_crud_embedding".to_string()),
                provider_type: Some("dashscope_embedding".to_string()),
                operation_type: Some("embedding".to_string()),
                api_key_plaintext: Some("dashscope-crud-secret".to_string()),
                embedding_model: Some("text-embedding-v3".to_string()),
                config: Some(
                    json!({"embedding": {"model": "text-embedding-v3", "dimensions": 1024}}),
                ),
                is_default: Some(true),
                pool_enabled: Some(false),
                secondary_models: Some(Vec::new()),
                ..Default::default()
            },
        )
        .await
        .expect("provider update succeeds")
        .expect("updated provider is returned");
    assert_eq!(updated.name, "llm_provider_crud_embedding");
    assert_eq!(updated.operation_type, "embedding");
    assert_eq!(updated.llm_model, None);
    assert_eq!(
        updated.embedding_model.as_deref(),
        Some("text-embedding-v3")
    );
    assert!(!updated.pool_enabled);
    assert!(updated.is_default);
    assert_eq!(
        agistack_adapters_secrets::try_decrypt_python_aes256_gcm(
            &updated.api_key_encrypted,
            &encryption_key,
        )
        .expect("updated provider api key decrypts"),
        "dashscope-crud-secret"
    );

    let stale_update = repo
        .update_provider(
            &created.id,
            &LlmProviderUpdateRecord {
                expected_updated_at: created.updated_at,
                name: Some("stale-provider-name".to_string()),
                ..Default::default()
            },
        )
        .await
        .expect("stale provider update query succeeds");
    assert!(stale_update.is_none());

    assert!(repo
        .soft_delete_provider(&created.id)
        .await
        .expect("provider soft-delete succeeds"));
    assert!(!repo
        .list_providers(false)
        .await
        .expect("active list succeeds")
        .iter()
        .any(|record| record.id == created.id));
    assert!(repo
        .list_providers(true)
        .await
        .expect("include-inactive list succeeds")
        .iter()
        .any(|record| record.id == created.id && !record.is_active));

    clean_llm_provider_crud_rows(&pool).await;
}

#[tokio::test]
async fn llm_provider_tenant_assignments_match_python_access_filter_order() {
    let Some(pool) =
        pool_or_skip("llm_provider_tenant_assignments_match_python_access_filter_order").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_llm_provider_assignment_rows(&pool).await;
    seed_llm_provider(&pool, PROVIDER_ID, "llm_provider_mapping_primary").await;
    seed_llm_provider(&pool, OTHER_PROVIDER_ID, "llm_provider_mapping_other").await;
    seed_llm_provider_user(&pool, "llm_provider_member").await;
    seed_llm_provider_user(&pool, "llm_provider_admin").await;
    seed_llm_provider_user(&pool, "llm_provider_stranger").await;
    seed_llm_provider_membership(&pool, "llm_provider_member", "llm_provider_tenant").await;
    seed_llm_provider_admin_role(&pool, "llm_provider_admin").await;
    seed_tenant_provider_mapping(
        &pool,
        MAPPING_HIGH_PRIORITY_ID,
        "llm_provider_tenant",
        PROVIDER_ID,
        "llm",
        5,
        ts(2026, 1, 1, 0, 0, 0),
    )
    .await;
    seed_tenant_provider_mapping(
        &pool,
        MAPPING_LOW_PRIORITY_ID,
        "llm_provider_tenant",
        OTHER_PROVIDER_ID,
        "embedding",
        1,
        ts(2026, 1, 2, 0, 0, 0),
    )
    .await;
    seed_tenant_provider_mapping(
        &pool,
        MAPPING_MID_PRIORITY_ID,
        "llm_provider_tenant",
        OTHER_PROVIDER_ID,
        "llm",
        3,
        ts(2026, 1, 3, 0, 0, 0),
    )
    .await;

    let repo = PgLlmProviderRepository::new(pool.clone());
    assert!(repo
        .user_can_read_tenant_assignments("llm_provider_member", "llm_provider_tenant")
        .await
        .expect("member access query succeeds"));
    assert!(repo
        .user_can_read_tenant_assignments("llm_provider_admin", "llm_provider_tenant")
        .await
        .expect("admin access query succeeds"));
    assert!(!repo
        .user_can_read_tenant_assignments("llm_provider_stranger", "llm_provider_tenant")
        .await
        .expect("stranger access query succeeds"));

    let all = repo
        .list_tenant_assignments("llm_provider_tenant", None)
        .await
        .expect("assignment list succeeds");
    assert_eq!(
        all.iter()
            .map(|mapping| mapping.id.as_str())
            .collect::<Vec<_>>(),
        vec![
            MAPPING_LOW_PRIORITY_ID,
            MAPPING_MID_PRIORITY_ID,
            MAPPING_HIGH_PRIORITY_ID
        ]
    );
    assert_eq!(all[0].operation_type, "embedding");
    assert_eq!(all[0].tenant_id, "llm_provider_tenant");
    assert_eq!(all[0].provider_id, OTHER_PROVIDER_ID);
    assert_eq!(all[0].created_at, ts(2026, 1, 2, 0, 0, 0));

    let llm = repo
        .list_tenant_assignments("llm_provider_tenant", Some("llm"))
        .await
        .expect("filtered assignment list succeeds");
    assert_eq!(
        llm.iter()
            .map(|mapping| mapping.id.as_str())
            .collect::<Vec<_>>(),
        vec![MAPPING_MID_PRIORITY_ID, MAPPING_HIGH_PRIORITY_ID]
    );
}

#[tokio::test]
async fn llm_provider_usage_statistics_match_python_scope_and_aggregation() {
    let Some(pool) =
        pool_or_skip("llm_provider_usage_statistics_match_python_scope_and_aggregation").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_llm_provider_assignment_rows(&pool).await;
    seed_llm_provider(&pool, PROVIDER_ID, "llm_provider_usage_primary").await;
    seed_llm_provider_user(&pool, "llm_provider_member").await;
    seed_llm_provider_user(&pool, "llm_provider_admin").await;
    seed_llm_provider_membership(&pool, "llm_provider_member", "llm_provider_tenant").await;
    seed_llm_provider_admin_role(&pool, "llm_provider_admin").await;
    seed_usage_log(
        &pool,
        USAGE_FIRST_ID,
        PROVIDER_ID,
        Some("llm_provider_tenant"),
        "llm",
        "gpt-test",
        10,
        20,
        Some(0.01),
        ts(2026, 1, 1, 0, 0, 0),
    )
    .await;
    seed_usage_log(
        &pool,
        USAGE_SECOND_ID,
        PROVIDER_ID,
        Some("llm_provider_tenant"),
        "llm",
        "gpt-test",
        3,
        7,
        Some(0.02),
        ts(2026, 1, 2, 0, 0, 0),
    )
    .await;
    seed_usage_log(
        &pool,
        USAGE_OTHER_ID,
        PROVIDER_ID,
        Some("llm_provider_other_tenant"),
        "llm",
        "gpt-test",
        100,
        200,
        Some(0.99),
        ts(2026, 1, 3, 0, 0, 0),
    )
    .await;

    let repo = PgLlmProviderRepository::new(pool.clone());
    assert!(!repo
        .user_has_provider_admin_role("llm_provider_member")
        .await
        .expect("member admin query succeeds"));
    assert!(repo
        .user_has_provider_admin_role("llm_provider_admin")
        .await
        .expect("admin query succeeds"));
    assert_eq!(
        repo.default_tenant_for_user("llm_provider_member")
            .await
            .expect("default tenant query succeeds")
            .as_deref(),
        Some("llm_provider_tenant")
    );

    let stats = repo
        .usage_statistics(UsageStatisticsQuery {
            provider_id: Some(PROVIDER_ID),
            tenant_id: Some("llm_provider_tenant"),
            operation_type: Some("llm"),
            start_date: Some(ts(2026, 1, 1, 0, 0, 0)),
            end_date: Some(ts(2026, 1, 2, 23, 59, 59)),
        })
        .await
        .expect("usage statistics query succeeds");

    assert_eq!(stats.len(), 1);
    let stat = &stats[0];
    assert_eq!(stat.provider_id, PROVIDER_ID);
    assert_eq!(stat.tenant_id.as_deref(), Some("llm_provider_tenant"));
    assert_eq!(stat.operation_type, "llm");
    assert_eq!(stat.total_requests, 2);
    assert_eq!(stat.total_prompt_tokens, 13);
    assert_eq!(stat.total_completion_tokens, 27);
    assert_eq!(stat.total_tokens, 40);
    assert!((stat.total_cost_usd.unwrap_or_default() - 0.03).abs() < f64::EPSILON);
    assert_eq!(stat.avg_response_time_ms, None);
    assert_eq!(stat.first_request_at, Some(ts(2026, 1, 1, 0, 0, 0)));
    assert_eq!(stat.last_request_at, Some(ts(2026, 1, 2, 0, 0, 0)));
}

async fn clean_llm_provider_health_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM provider_health WHERE provider_id::text = ANY($1::text[])")
        .bind(vec![PROVIDER_ID, OTHER_PROVIDER_ID])
        .execute(pool)
        .await
        .expect("clean provider health rows");
    sqlx::query("DELETE FROM llm_providers WHERE id::text = ANY($1::text[])")
        .bind(vec![PROVIDER_ID, OTHER_PROVIDER_ID])
        .execute(pool)
        .await
        .expect("clean provider rows");
}

async fn clean_llm_provider_crud_rows(pool: &PgPool) {
    sqlx::query(
        "DELETE FROM llm_providers WHERE name IN \
         ('llm_provider_crud_openai', 'llm_provider_crud_embedding')",
    )
    .execute(pool)
    .await
    .expect("clean llm provider crud rows");
}

async fn clean_llm_provider_assignment_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM tenant_provider_mappings WHERE tenant_id LIKE 'llm_provider_%'")
        .execute(pool)
        .await
        .expect("clean tenant provider mappings by tenant");
    sqlx::query("DELETE FROM llm_usage_logs WHERE id::text = ANY($1::text[])")
        .bind(vec![USAGE_FIRST_ID, USAGE_SECOND_ID, USAGE_OTHER_ID])
        .execute(pool)
        .await
        .expect("clean usage logs by id");
    sqlx::query("DELETE FROM llm_usage_logs WHERE tenant_id LIKE 'llm_provider_%'")
        .execute(pool)
        .await
        .expect("clean usage logs by tenant");
    sqlx::query("DELETE FROM tenant_provider_mappings WHERE id::text = ANY($1::text[])")
        .bind(vec![
            MAPPING_HIGH_PRIORITY_ID,
            MAPPING_LOW_PRIORITY_ID,
            MAPPING_MID_PRIORITY_ID,
        ])
        .execute(pool)
        .await
        .expect("clean tenant provider mappings by id");
    sqlx::query("DELETE FROM user_roles WHERE id LIKE 'llm_provider_%'")
        .execute(pool)
        .await
        .expect("clean provider user roles");
    sqlx::query("DELETE FROM user_tenants WHERE id LIKE 'llm_provider_%'")
        .execute(pool)
        .await
        .expect("clean provider user tenants");
    sqlx::query("DELETE FROM users WHERE id LIKE 'llm_provider_%'")
        .execute(pool)
        .await
        .expect("clean provider users");
    sqlx::query("DELETE FROM provider_health WHERE provider_id::text = ANY($1::text[])")
        .bind(vec![PROVIDER_ID, OTHER_PROVIDER_ID])
        .execute(pool)
        .await
        .expect("clean provider health rows");
    sqlx::query("DELETE FROM llm_providers WHERE id::text = ANY($1::text[])")
        .bind(vec![PROVIDER_ID, OTHER_PROVIDER_ID])
        .execute(pool)
        .await
        .expect("clean provider rows");
}

async fn seed_llm_provider(pool: &PgPool, id: &str, name: &str) {
    sqlx::query(
        "INSERT INTO llm_providers (\
             id, name, provider_type, operation_type, api_key_encrypted, config, \
             is_active, is_default, is_enabled, pool_weight, pool_enabled, created_at, updated_at\
         ) VALUES (\
             $1::uuid, $2, 'openai', 'llm', 'encrypted-test-key', '{}'::json, \
             true, false, true, 1.0, true, now(), now()\
         ) \
         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    .bind(id)
    .bind(name)
    .execute(pool)
    .await
    .expect("seed provider");
}

async fn seed_llm_provider_user(pool: &PgPool, user_id: &str) {
    sqlx::query(
        "INSERT INTO users (id, email) VALUES ($1, $2) \
         ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .execute(pool)
    .await
    .expect("seed provider user");
}

async fn seed_llm_provider_membership(pool: &PgPool, user_id: &str, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ($1, $2, $3, 'member') \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id, tenant_id = EXCLUDED.tenant_id",
    )
    .bind(format!("llm_provider_membership_{user_id}_{tenant_id}"))
    .bind(user_id)
    .bind(tenant_id)
    .execute(pool)
    .await
    .expect("seed provider membership");
}

async fn seed_llm_provider_admin_role(pool: &PgPool, user_id: &str) {
    sqlx::query(
        "INSERT INTO roles (id, name, description) VALUES ($1, 'admin', 'Admin') \
         ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description",
    )
    .bind("llm_provider_admin_role")
    .execute(pool)
    .await
    .expect("seed admin role");
    let (role_id,) = sqlx::query_as::<_, (String,)>("SELECT id FROM roles WHERE name = 'admin'")
        .fetch_one(pool)
        .await
        .expect("read admin role id");
    sqlx::query(
        "INSERT INTO user_roles (id, user_id, role_id, tenant_id) VALUES ($1, $2, $3, NULL) \
         ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id, role_id = EXCLUDED.role_id",
    )
    .bind(format!("llm_provider_user_role_{user_id}"))
    .bind(user_id)
    .bind(role_id)
    .execute(pool)
    .await
    .expect("seed provider admin user role");
}

async fn seed_tenant_provider_mapping(
    pool: &PgPool,
    id: &str,
    tenant_id: &str,
    provider_id: &str,
    operation_type: &str,
    priority: i32,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO tenant_provider_mappings \
            (id, tenant_id, provider_id, operation_type, priority, created_at) \
         VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6) \
         ON CONFLICT (id) DO UPDATE SET \
            tenant_id = EXCLUDED.tenant_id, \
            provider_id = EXCLUDED.provider_id, \
            operation_type = EXCLUDED.operation_type, \
            priority = EXCLUDED.priority, \
            created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(tenant_id)
    .bind(provider_id)
    .bind(operation_type)
    .bind(priority)
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed tenant provider mapping");
}

#[allow(clippy::too_many_arguments)]
async fn seed_usage_log(
    pool: &PgPool,
    id: &str,
    provider_id: &str,
    tenant_id: Option<&str>,
    operation_type: &str,
    model_name: &str,
    prompt_tokens: i32,
    completion_tokens: i32,
    cost_usd: Option<f64>,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO llm_usage_logs \
            (id, provider_id, tenant_id, operation_type, model_name, prompt_tokens, \
             completion_tokens, cost_usd, created_at) \
         VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9) \
         ON CONFLICT (id) DO UPDATE SET \
            provider_id = EXCLUDED.provider_id, \
            tenant_id = EXCLUDED.tenant_id, \
            operation_type = EXCLUDED.operation_type, \
            model_name = EXCLUDED.model_name, \
            prompt_tokens = EXCLUDED.prompt_tokens, \
            completion_tokens = EXCLUDED.completion_tokens, \
            cost_usd = EXCLUDED.cost_usd, \
            created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(provider_id)
    .bind(tenant_id)
    .bind(operation_type)
    .bind(model_name)
    .bind(prompt_tokens)
    .bind(completion_tokens)
    .bind(cost_usd)
    .bind(created_at)
    .execute(pool)
    .await
    .expect("seed usage log");
}

async fn seed_provider_health(
    pool: &PgPool,
    provider_id: &str,
    status: &str,
    last_check: DateTime<Utc>,
    error_message: Option<&str>,
    response_time_ms: Option<i32>,
) {
    sqlx::query(
        "INSERT INTO provider_health \
            (provider_id, last_check, status, error_message, response_time_ms) \
         VALUES ($1::uuid, $2, $3, $4, $5) \
         ON CONFLICT (provider_id, last_check) DO UPDATE SET \
            status = EXCLUDED.status, \
            error_message = EXCLUDED.error_message, \
            response_time_ms = EXCLUDED.response_time_ms",
    )
    .bind(provider_id)
    .bind(last_check)
    .bind(status)
    .bind(error_message)
    .bind(response_time_ms)
    .execute(pool)
    .await
    .expect("seed provider health");
}
