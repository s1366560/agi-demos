use super::support::*;
use agistack_adapters_postgres::{LlmProviderMutationError, ProviderHealthRecord};
use sqlx::Row;

const PROVIDER_ID: &str = "11111111-2222-4333-8444-555555555555";
const OTHER_PROVIDER_ID: &str = "21111111-2222-4333-8444-555555555555";
const MAPPING_HIGH_PRIORITY_ID: &str = "31111111-2222-4333-8444-555555555555";
const MAPPING_LOW_PRIORITY_ID: &str = "41111111-2222-4333-8444-555555555555";
const MAPPING_MID_PRIORITY_ID: &str = "51111111-2222-4333-8444-555555555555";
const USAGE_FIRST_ID: &str = "61111111-2222-4333-8444-555555555555";
const USAGE_SECOND_ID: &str = "71111111-2222-4333-8444-555555555555";
const USAGE_OTHER_ID: &str = "81111111-2222-4333-8444-555555555555";
const CRUD_OPENAI_NAME: &str = "llm_provider_crud_openai";
const DEFAULT_TRANSITION_PREFIX: &str = "llm_provider_default_transition_";

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
                base_url: Some(Some("https://dashscope.example.test/v1".to_string())),
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
        updated.base_url.as_deref(),
        Some("https://dashscope.example.test/v1")
    );
    assert_eq!(
        agistack_adapters_secrets::try_decrypt_python_aes256_gcm(
            &updated.api_key_encrypted,
            &encryption_key,
        )
        .expect("updated provider api key decrypts"),
        "dashscope-crud-secret"
    );

    let preserved_base_url = repo
        .update_provider(
            &created.id,
            &LlmProviderUpdateRecord {
                expected_updated_at: updated.updated_at,
                is_enabled: Some(false),
                ..Default::default()
            },
        )
        .await
        .expect("provider update preserving base URL succeeds")
        .expect("provider with preserved base URL is returned");
    assert_eq!(
        preserved_base_url.base_url.as_deref(),
        Some("https://dashscope.example.test/v1")
    );

    let cleared_base_url = repo
        .update_provider(
            &created.id,
            &LlmProviderUpdateRecord {
                expected_updated_at: preserved_base_url.updated_at,
                base_url: Some(None),
                ..Default::default()
            },
        )
        .await
        .expect("provider base URL clear succeeds")
        .expect("provider with cleared base URL is returned");
    assert_eq!(cleared_base_url.base_url, None);
    assert_eq!(
        repo.get_provider(&created.id)
            .await
            .expect("provider read after base URL clear succeeds")
            .expect("provider remains available")
            .base_url,
        None
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
async fn llm_provider_default_transitions_are_atomic_and_name_conflicts_are_explicit() {
    let Some(pool) =
        pool_or_skip("llm_provider_default_transitions_are_atomic_and_name_conflicts_are_explicit")
            .await
    else {
        return;
    };
    if std::env::var("LLM_ENCRYPTION_KEY").is_err() {
        eprintln!(
            "[skip] llm_provider_default_transitions_are_atomic_and_name_conflicts_are_explicit: \
             LLM_ENCRYPTION_KEY unset"
        );
        return;
    }
    ensure_python_shaped_tables(&pool).await;
    clean_llm_provider_default_transition_rows(&pool).await;
    let existing_rerank_defaults = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM llm_providers \
         WHERE operation_type = 'rerank' AND is_default AND name NOT LIKE $1",
    )
    .bind(format!("{DEFAULT_TRANSITION_PREFIX}%"))
    .fetch_one(&pool)
    .await
    .expect("count pre-existing rerank defaults");
    if existing_rerank_defaults > 0 {
        eprintln!(
            "[skip] llm_provider_default_transitions_are_atomic_and_name_conflicts_are_explicit: \
             database has a non-test rerank default"
        );
        return;
    }

    let provider = |suffix: &str, is_default: bool| LlmProviderCreateRecord {
        name: format!("{DEFAULT_TRANSITION_PREFIX}{suffix}"),
        provider_type: "cohere".to_string(),
        operation_type: "rerank".to_string(),
        api_key_plaintext: format!("rerank-{suffix}-secret"),
        base_url: Some("https://api.cohere.com/v1".to_string()),
        llm_model: None,
        llm_small_model: None,
        embedding_model: None,
        reranker_model: Some("rerank-v3.5".to_string()),
        config: json!({}),
        is_active: true,
        is_default,
        is_enabled: true,
        allowed_models: Vec::new(),
        blocked_models: Vec::new(),
        pool_weight: 1.0,
        pool_enabled: false,
        model_tier: None,
        secondary_models: Vec::new(),
    };

    let first_record = provider("first", true);
    let second_record = provider("second", true);
    let first_repo = PgLlmProviderRepository::new(pool.clone());
    let second_repo = PgLlmProviderRepository::new(pool.clone());
    let (first, second) = tokio::join!(
        first_repo.create_provider(&first_record),
        second_repo.create_provider(&second_record)
    );
    let first = first.expect("first concurrent default create succeeds");
    let second = second.expect("second concurrent default create succeeds");

    let rows = sqlx::query(
        "SELECT id::text AS id, is_default, updated_at FROM llm_providers \
         WHERE name LIKE $1 ORDER BY name",
    )
    .bind(format!("{DEFAULT_TRANSITION_PREFIX}%"))
    .fetch_all(&pool)
    .await
    .expect("read concurrent default rows");
    assert_eq!(rows.len(), 2);
    assert_eq!(
        rows.iter()
            .filter(|row| row.get::<bool, _>("is_default"))
            .count(),
        1,
        "concurrent creates must leave exactly one rerank default"
    );
    for created in [&first, &second] {
        let stored = rows
            .iter()
            .find(|row| row.get::<String, _>("id") == created.id)
            .expect("created provider remains stored");
        if !stored.get::<bool, _>("is_default") {
            assert!(
                stored.get::<DateTime<Utc>, _>("updated_at") > created.updated_at,
                "demoting the previous default must advance its public revision"
            );
        }
    }

    let repo = PgLlmProviderRepository::new(pool.clone());
    let duplicate = repo
        .create_provider(&second_record)
        .await
        .expect_err("duplicate provider name must be reported as a conflict");
    assert!(matches!(duplicate, LlmProviderMutationError::NameConflict));

    let third = repo
        .create_provider(&provider("third", false))
        .await
        .expect("non-default provider create succeeds");
    let previous_default = rows
        .iter()
        .find(|row| row.get::<bool, _>("is_default"))
        .map(|row| {
            (
                row.get::<String, _>("id"),
                row.get::<DateTime<Utc>, _>("updated_at"),
            )
        })
        .expect("one default exists before update transition");
    let promoted = repo
        .update_provider(
            &third.id,
            &LlmProviderUpdateRecord {
                expected_updated_at: third.updated_at,
                is_default: Some(true),
                ..Default::default()
            },
        )
        .await
        .expect("default promotion update succeeds")
        .expect("promoted provider is returned");
    assert!(promoted.is_default);

    let final_rows = sqlx::query(
        "SELECT id::text AS id, is_default, updated_at FROM llm_providers \
         WHERE name LIKE $1 ORDER BY name",
    )
    .bind(format!("{DEFAULT_TRANSITION_PREFIX}%"))
    .fetch_all(&pool)
    .await
    .expect("read final default rows");
    assert_eq!(
        final_rows
            .iter()
            .filter(|row| row.get::<bool, _>("is_default"))
            .count(),
        1
    );
    assert!(final_rows.iter().any(|row| {
        row.get::<String, _>("id") == promoted.id && row.get::<bool, _>("is_default")
    }));
    let demoted = final_rows
        .iter()
        .find(|row| row.get::<String, _>("id") == previous_default.0)
        .expect("previous default remains stored");
    assert!(!demoted.get::<bool, _>("is_default"));
    assert!(demoted.get::<DateTime<Utc>, _>("updated_at") > previous_default.1);

    clean_llm_provider_default_transition_rows(&pool).await;
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
    seed_llm_provider_tenant(&pool, "llm_provider_tenant", "llm_provider_member").await;
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
    seed_llm_provider_tenant(&pool, "llm_provider_tenant", "llm_provider_member").await;
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

async fn clean_llm_provider_default_transition_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM llm_providers WHERE name LIKE $1")
        .bind(format!("{DEFAULT_TRANSITION_PREFIX}%"))
        .execute(pool)
        .await
        .expect("clean llm provider default transition rows");
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
    sqlx::query("DELETE FROM tenants WHERE id LIKE 'llm_provider_%'")
        .execute(pool)
        .await
        .expect("clean provider tenants");
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
        "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, profile) \
         VALUES ($1, $2, $3, true, false, '{}'::json) \
         ON CONFLICT (id) DO UPDATE SET \
             email = EXCLUDED.email, hashed_password = EXCLUDED.hashed_password, \
             is_active = true, is_superuser = false, profile = '{}'::json",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind("integration-test-only")
    .execute(pool)
    .await
    .expect("seed provider user");
}

async fn seed_llm_provider_tenant(pool: &PgPool, tenant_id: &str, owner_id: &str) {
    sqlx::query(
        "INSERT INTO tenants \
             (id, name, slug, owner_id, plan, max_projects, max_users, max_storage) \
         VALUES ($1, $2, $3, $4, 'free', 10, 5, 1073741824) \
         ON CONFLICT (id) DO UPDATE SET \
             name = EXCLUDED.name, slug = EXCLUDED.slug, owner_id = EXCLUDED.owner_id",
    )
    .bind(tenant_id)
    .bind("LLM Provider Integration Tenant")
    .bind("llm-provider-integration-tenant")
    .bind(owner_id)
    .execute(pool)
    .await
    .expect("seed provider tenant");
}

async fn seed_llm_provider_membership(pool: &PgPool, user_id: &str, tenant_id: &str) {
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
         VALUES ($1, $2, $3, 'member', '{}'::json) \
         ON CONFLICT (id) DO UPDATE SET \
             user_id = EXCLUDED.user_id, tenant_id = EXCLUDED.tenant_id, \
             permissions = '{}'::json",
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
