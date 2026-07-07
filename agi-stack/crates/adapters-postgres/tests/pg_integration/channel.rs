use super::support::*;

#[tokio::test]
async fn channel_outbox_claims_and_marks_sent_with_owner_lease() {
    let Some(pool) = pool_or_skip("channel_outbox_claims_and_marks_sent_with_owner_lease").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_aux_schema(&pool).await.unwrap();
    clean_channel_rows(&pool, "chan_claim_sent").await;
    seed_channel_outbox(
        &pool,
        ChannelSeed {
            prefix: "chan_claim_sent",
            outbox_id: "chan_claim_sent_outbox",
            attempt_count: 0,
            max_attempts: 3,
            status: "pending",
            next_retry: None,
        },
    )
    .await;

    let repo = PgChannelRepository::new(pool.clone());
    let claimed = repo
        .claim_due_outbox("worker-a", 60, 10)
        .await
        .expect("claim succeeds");

    assert_eq!(claimed.len(), 1);
    assert_eq!(claimed[0].id, "chan_claim_sent_outbox");
    assert_eq!(claimed[0].channel_type.as_deref(), Some("feishu"));
    assert_eq!(
        claimed[0].webhook_url.as_deref(),
        Some("https://example.test/chan_claim_sent/webhook")
    );
    assert_eq!(claimed[0].domain.as_deref(), Some("feishu"));
    assert_eq!(claimed[0].attempt_count, 1);

    let duplicate_claim = repo
        .claim_due_outbox("worker-b", 60, 10)
        .await
        .expect("second claim succeeds");
    assert!(
        duplicate_claim
            .iter()
            .all(|item| item.id != "chan_claim_sent_outbox"),
        "active lease prevents duplicate delivery ownership"
    );

    assert!(repo
        .mark_outbox_sent("chan_claim_sent_outbox", "worker-b", "msg-wrong")
        .await
        .expect("wrong owner update is checked")
        .is_none());
    let sent = repo
        .mark_outbox_sent("chan_claim_sent_outbox", "worker-a", "msg-ok")
        .await
        .expect("owner can mark sent")
        .expect("sent row returned");

    assert_eq!(sent.status, "sent");
    assert_eq!(sent.sent_channel_message_id.as_deref(), Some("msg-ok"));
    assert!(sent.last_error.is_none());
    assert!(sent.next_retry_at.is_none());
    assert_eq!(lease_count(&pool, "chan_claim_sent_outbox").await, 0);
}

#[tokio::test]
async fn channel_outbox_failure_retries_then_dead_letters() {
    let Some(pool) = pool_or_skip("channel_outbox_failure_retries_then_dead_letters").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_aux_schema(&pool).await.unwrap();
    clean_channel_rows(&pool, "chan_retry").await;
    seed_channel_outbox(
        &pool,
        ChannelSeed {
            prefix: "chan_retry",
            outbox_id: "chan_retry_outbox",
            attempt_count: 0,
            max_attempts: 2,
            status: "pending",
            next_retry: None,
        },
    )
    .await;

    let repo = PgChannelRepository::new(pool.clone());
    let first_claim = repo
        .claim_due_outbox("worker-a", 60, 10)
        .await
        .expect("first claim succeeds");
    assert_eq!(first_claim[0].attempt_count, 1);
    let failed = repo
        .mark_outbox_failed("chan_retry_outbox", "worker-a", "rate limited", 300)
        .await
        .expect("failure update succeeds")
        .expect("failed row returned");

    assert_eq!(failed.status, "failed");
    assert_eq!(failed.last_error.as_deref(), Some("rate limited"));
    assert!(failed.next_retry_at.is_some());
    assert_eq!(lease_count(&pool, "chan_retry_outbox").await, 0);

    let blocked_by_retry = repo
        .claim_due_outbox("worker-b", 60, 10)
        .await
        .expect("claim succeeds");
    assert!(
        blocked_by_retry
            .iter()
            .all(|item| item.id != "chan_retry_outbox"),
        "future retry time prevents immediate re-delivery"
    );

    sqlx::query(
        "UPDATE channel_outbox SET next_retry_at = now() - interval '1 second' WHERE id = $1",
    )
    .bind("chan_retry_outbox")
    .execute(&pool)
    .await
    .unwrap();
    let second_claim = repo
        .claim_due_outbox("worker-b", 60, 10)
        .await
        .expect("retry claim succeeds");
    let retry_item = second_claim
        .iter()
        .find(|item| item.id == "chan_retry_outbox")
        .expect("retry row claimed");
    assert_eq!(retry_item.attempt_count, 2);

    let dead_letter = repo
        .mark_outbox_failed("chan_retry_outbox", "worker-b", "provider rejected", 300)
        .await
        .expect("dead-letter update succeeds")
        .expect("dead-letter row returned");

    assert_eq!(dead_letter.status, "dead_letter");
    assert_eq!(dead_letter.last_error.as_deref(), Some("provider rejected"));
    assert!(dead_letter.next_retry_at.is_none());
    assert_eq!(lease_count(&pool, "chan_retry_outbox").await, 0);
}

#[tokio::test]
async fn channel_webhook_ingress_resolves_config_and_deduplicates_events() {
    let Some(pool) =
        pool_or_skip("channel_webhook_ingress_resolves_config_and_deduplicates_events").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_aux_schema(&pool).await.unwrap();
    clean_channel_rows(&pool, "chan_webhook").await;
    seed_channel_outbox(
        &pool,
        ChannelSeed {
            prefix: "chan_webhook",
            outbox_id: "chan_webhook_outbox",
            attempt_count: 0,
            max_attempts: 3,
            status: "pending",
            next_retry: None,
        },
    )
    .await;

    let repo = PgChannelRepository::new(pool.clone());
    let first = repo
        .record_webhook_event(&ChannelWebhookEventInsertRecord {
            id: "chan_webhook_event_1".to_string(),
            channel_config_id: "chan_webhook_config".to_string(),
            idempotency_key: "evt-1".to_string(),
            headers_json: json!({"x-request-id": "req-1"}),
            raw_event_json: json!({"event": {"message_id": "m-1", "text": "hello"}}),
            normalized_event_json: json!({"provider": "feishu", "message_id": "m-1"}),
        })
        .await
        .expect("webhook insert succeeds")
        .expect("config exists");

    assert!(first.inserted);
    assert_eq!(first.event.project_id, "chan_webhook_project");
    assert_eq!(first.event.channel_type, "feishu");
    assert_eq!(first.event.status, "received");
    assert_eq!(first.event.raw_event_json["event"]["message_id"], "m-1");
    assert_eq!(first.event.normalized_event_json["message_id"], "m-1");

    let duplicate = repo
        .record_webhook_event(&ChannelWebhookEventInsertRecord {
            id: "chan_webhook_event_2".to_string(),
            channel_config_id: "chan_webhook_config".to_string(),
            idempotency_key: "evt-1".to_string(),
            headers_json: json!({"x-request-id": "req-2"}),
            raw_event_json: json!({"event": {"message_id": "m-2", "text": "changed"}}),
            normalized_event_json: json!({"provider": "feishu", "message_id": "m-2"}),
        })
        .await
        .expect("duplicate lookup succeeds")
        .expect("existing event returned");

    assert!(!duplicate.inserted);
    assert_eq!(duplicate.event.id, "chan_webhook_event_1");
    assert_eq!(duplicate.event.headers_json["x-request-id"], "req-1");
    assert_eq!(duplicate.event.raw_event_json["event"]["message_id"], "m-1");
    assert_eq!(duplicate.event.normalized_event_json["message_id"], "m-1");
    assert_eq!(
        webhook_event_count(&pool, "chan_webhook_config", "evt-1").await,
        1
    );

    let missing = repo
        .record_webhook_event(&ChannelWebhookEventInsertRecord {
            id: "chan_webhook_missing".to_string(),
            channel_config_id: "missing-config".to_string(),
            idempotency_key: "evt-missing".to_string(),
            headers_json: json!({}),
            raw_event_json: json!({"event": "missing"}),
            normalized_event_json: json!({"provider": "feishu"}),
        })
        .await
        .expect("missing config is not a storage error");
    assert!(missing.is_none());
}

#[tokio::test]
async fn channel_webhook_secret_projection_reads_runtime_credentials_only() {
    let Some(pool) =
        pool_or_skip("channel_webhook_secret_projection_reads_runtime_credentials_only").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_aux_schema(&pool).await.unwrap();
    clean_channel_rows(&pool, "chan_secret").await;
    seed_channel_outbox(
        &pool,
        ChannelSeed {
            prefix: "chan_secret",
            outbox_id: "chan_secret_outbox",
            attempt_count: 0,
            max_attempts: 3,
            status: "pending",
            next_retry: None,
        },
    )
    .await;
    sqlx::query(
        "UPDATE channel_configs \
         SET connection_mode = 'webhook', domain = 'lark', \
             encrypt_key = 'encrypt-secret', verification_token = 'verify-token' \
         WHERE id = $1",
    )
    .bind("chan_secret_config")
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgChannelRepository::new(pool.clone());
    let secrets = repo
        .get_webhook_secrets("chan_secret_config")
        .await
        .expect("secret lookup succeeds")
        .expect("config exists");

    assert_eq!(
        secrets,
        ChannelWebhookSecretRecord {
            config_id: "chan_secret_config".to_string(),
            project_id: "chan_secret_project".to_string(),
            channel_type: "feishu".to_string(),
            enabled: true,
            connection_mode: "webhook".to_string(),
            domain: Some("lark".to_string()),
            encrypt_key: Some("encrypt-secret".to_string()),
            verification_token: Some("verify-token".to_string()),
        }
    );

    let public_config = repo
        .get_config("chan_secret_config")
        .await
        .expect("public config lookup succeeds")
        .expect("config exists");
    assert_eq!(public_config.connection_mode, "webhook");
    assert_eq!(public_config.domain.as_deref(), Some("lark"));

    let missing = repo
        .get_webhook_secrets("missing-secret-config")
        .await
        .expect("missing config lookup succeeds");
    assert!(missing.is_none());
}

#[tokio::test]
async fn channel_webhook_route_projection_matches_existing_session_binding() {
    let Some(pool) =
        pool_or_skip("channel_webhook_route_projection_matches_existing_session_binding").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_aux_schema(&pool).await.unwrap();
    clean_channel_rows(&pool, "chan_route").await;
    seed_channel_outbox(
        &pool,
        ChannelSeed {
            prefix: "chan_route",
            outbox_id: "chan_route_outbox",
            attempt_count: 0,
            max_attempts: 3,
            status: "pending",
            next_retry: None,
        },
    )
    .await;

    let session_key = "project:chan_route_project:channel:feishu:config:chan_route_config:group:chan_route_chat:topic:topic-1:thread:thread-1";
    seed_channel_binding(
        &pool,
        "chan_route_binding",
        "chan_route_project",
        "chan_route_config",
        "chan_route_conversation",
        "chan_route_chat",
        session_key,
    )
    .await;

    let repo = PgChannelRepository::new(pool.clone());
    repo.record_webhook_event(&ChannelWebhookEventInsertRecord {
        id: "chan_route_event".to_string(),
        channel_config_id: "chan_route_config".to_string(),
        idempotency_key: "evt-route".to_string(),
        headers_json: json!({"x-request-id": "req-route"}),
        raw_event_json: json!({"event": {"message_id": "m-route"}}),
        normalized_event_json: json!({
            "provider": "feishu",
            "message_id": "m-route",
            "chat_id": "chan_route_chat",
            "chat_type": "group",
            "topic_id": "topic-1",
            "thread_id": "thread-1"
        }),
    })
    .await
    .expect("webhook insert succeeds")
    .expect("config exists");

    let routed = repo
        .route_webhook_event_to_session_binding("chan_route_event", Some(session_key), None)
        .await
        .expect("route projection succeeds")
        .expect("event exists");

    assert_eq!(routed.event.status, "routed");
    assert_eq!(routed.event.route_session_key.as_deref(), Some(session_key));
    assert_eq!(
        routed.event.route_binding_id.as_deref(),
        Some("chan_route_binding")
    );
    assert_eq!(
        routed.event.route_conversation_id.as_deref(),
        Some("chan_route_conversation")
    );
    assert_eq!(routed.event.route_error, None);
    assert!(routed.event.routed_at.is_some());
    assert_eq!(
        routed
            .session_binding
            .as_ref()
            .map(|binding| binding.id.as_str()),
        Some("chan_route_binding")
    );

    repo.record_webhook_event(&ChannelWebhookEventInsertRecord {
        id: "chan_route_unbound_event".to_string(),
        channel_config_id: "chan_route_config".to_string(),
        idempotency_key: "evt-unbound".to_string(),
        headers_json: json!({"x-request-id": "req-unbound"}),
        raw_event_json: json!({"event": {"message_id": "m-unbound"}}),
        normalized_event_json: json!({"provider": "feishu", "message_id": "m-unbound"}),
    })
    .await
    .expect("unbound webhook insert succeeds")
    .expect("config exists");

    let unbound = repo
        .route_webhook_event_to_session_binding(
            "chan_route_unbound_event",
            None,
            Some("missing chat_id"),
        )
        .await
        .expect("unbound route projection succeeds")
        .expect("event exists");
    assert_eq!(unbound.event.status, "unbound");
    assert_eq!(
        unbound.event.route_error.as_deref(),
        Some("missing chat_id")
    );
    assert_eq!(unbound.event.route_session_key, None);
    assert!(unbound.session_binding.is_none());
}

#[tokio::test]
async fn channel_webhook_route_creates_session_binding_and_conversation_when_unbound() {
    let Some(pool) =
        pool_or_skip("channel_webhook_route_creates_session_binding_and_conversation_when_unbound")
            .await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_aux_schema(&pool).await.unwrap();
    clean_channel_rows(&pool, "chan_auto_route").await;
    seed_channel_outbox(
        &pool,
        ChannelSeed {
            prefix: "chan_auto_route",
            outbox_id: "chan_auto_route_outbox",
            attempt_count: 0,
            max_attempts: 3,
            status: "pending",
            next_retry: None,
        },
    )
    .await;

    let repo = PgChannelRepository::new(pool.clone());
    let session_key =
        "project:chan_auto_route_project:channel:feishu:config:chan_auto_route_config:dm:ou_auto";
    repo.record_webhook_event(&ChannelWebhookEventInsertRecord {
        id: "chan_auto_route_event".to_string(),
        channel_config_id: "chan_auto_route_config".to_string(),
        idempotency_key: "evt-auto-route".to_string(),
        headers_json: json!({"x-request-id": "req-auto-route"}),
        raw_event_json: json!({"event": {"message_id": "m-auto-route"}}),
        normalized_event_json: json!({
            "provider": "feishu",
            "message_id": "m-auto-route",
            "chat_id": "ou_auto",
            "chat_type": "p2p",
            "sender_open_id": "ou_sender_auto"
        }),
    })
    .await
    .expect("webhook insert succeeds")
    .expect("config exists");

    let routed = repo
        .route_webhook_event_to_session_binding_or_create(
            "chan_auto_route_event",
            Some(&ChannelWebhookSessionCreateRecord {
                binding_id: "chan_auto_route_binding".to_string(),
                conversation_id: "chan_auto_route_conversation".to_string(),
                session_key: session_key.to_string(),
                chat_id: "ou_auto".to_string(),
                chat_type: "p2p".to_string(),
                thread_id: None,
                topic_id: None,
                conversation_title: "Feishu: Chat with ou_sender_auto".to_string(),
                metadata_json: json!({
                    "channel_session_key": session_key,
                    "channel_type": "feishu",
                    "channel_config_id": "chan_auto_route_config",
                    "chat_id": "ou_auto",
                    "chat_type": "p2p",
                    "sender_id": "ou_sender_auto",
                    "sender_name": "ou_sender_auto"
                }),
            }),
            None,
        )
        .await
        .expect("route projection succeeds")
        .expect("event exists");

    assert_eq!(routed.event.status, "routed");
    assert_eq!(routed.event.route_session_key.as_deref(), Some(session_key));
    assert_eq!(
        routed.event.route_binding_id.as_deref(),
        Some("chan_auto_route_binding")
    );
    assert_eq!(
        routed.event.route_conversation_id.as_deref(),
        Some("chan_auto_route_conversation")
    );
    let binding = routed
        .session_binding
        .as_ref()
        .expect("new session binding returned");
    assert_eq!(binding.conversation_id, "chan_auto_route_conversation");
    assert_eq!(binding.chat_type, "p2p");

    let conversation = sqlx::query_as::<_, (String, String, String, serde_json::Value)>(
        "SELECT user_id, title, status, meta \
         FROM conversations \
         WHERE id = $1",
    )
    .bind("chan_auto_route_conversation")
    .fetch_one(&pool)
    .await
    .expect("conversation exists");
    assert_eq!(conversation.0, "chan_auto_route_user");
    assert_eq!(conversation.1, "Feishu: Chat with ou_sender_auto");
    assert_eq!(conversation.2, "active");
    assert_eq!(conversation.3["channel_session_key"], session_key);

    repo.record_webhook_event(&ChannelWebhookEventInsertRecord {
        id: "chan_auto_route_event_2".to_string(),
        channel_config_id: "chan_auto_route_config".to_string(),
        idempotency_key: "evt-auto-route-2".to_string(),
        headers_json: json!({"x-request-id": "req-auto-route-2"}),
        raw_event_json: json!({"event": {"message_id": "m-auto-route-2"}}),
        normalized_event_json: json!({
            "provider": "feishu",
            "message_id": "m-auto-route-2",
            "chat_id": "ou_auto",
            "chat_type": "p2p",
            "sender_open_id": "ou_sender_auto"
        }),
    })
    .await
    .expect("second webhook insert succeeds")
    .expect("config exists");
    let reused = repo
        .route_webhook_event_to_session_binding_or_create(
            "chan_auto_route_event_2",
            Some(&ChannelWebhookSessionCreateRecord {
                binding_id: "chan_auto_route_binding_unused".to_string(),
                conversation_id: "chan_auto_route_orphan_conversation".to_string(),
                session_key: session_key.to_string(),
                chat_id: "ou_auto".to_string(),
                chat_type: "p2p".to_string(),
                thread_id: None,
                topic_id: None,
                conversation_title: "Feishu: Chat with ou_sender_auto".to_string(),
                metadata_json: json!({"channel_session_key": session_key}),
            }),
            None,
        )
        .await
        .expect("second route projection succeeds")
        .expect("event exists");

    assert_eq!(
        reused.event.route_conversation_id.as_deref(),
        Some("chan_auto_route_conversation")
    );
    assert_eq!(
        conversation_count(&pool, "chan_auto_route_orphan_conversation").await,
        0
    );
}

#[tokio::test]
async fn channel_connection_lifecycle_updates_shared_config_status() {
    let Some(pool) =
        pool_or_skip("channel_connection_lifecycle_updates_shared_config_status").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_aux_schema(&pool).await.unwrap();
    clean_channel_rows(&pool, "chan_lifecycle").await;
    seed_channel_outbox(
        &pool,
        ChannelSeed {
            prefix: "chan_lifecycle",
            outbox_id: "chan_lifecycle_outbox",
            attempt_count: 0,
            max_attempts: 3,
            status: "pending",
            next_retry: None,
        },
    )
    .await;

    let repo = PgChannelRepository::new(pool.clone());
    let disconnected = repo
        .update_connection_status("chan_lifecycle_config", "disconnected", None)
        .await
        .expect("disconnect transition succeeds")
        .expect("config exists");
    assert_eq!(disconnected.status, "disconnected");
    assert!(!disconnected.connected);
    assert_eq!(disconnected.last_error, None);

    let connected = repo
        .update_connection_status("chan_lifecycle_config", "connected", None)
        .await
        .expect("connect transition succeeds")
        .expect("config exists");
    assert_eq!(connected.status, "connected");
    assert!(connected.connected);

    sqlx::query("UPDATE channel_configs SET enabled = false WHERE id = $1")
        .bind("chan_lifecycle_config")
        .execute(&pool)
        .await
        .unwrap();
    let disabled = repo
        .update_connection_status(
            "chan_lifecycle_config",
            "disconnected",
            Some("channel config disabled"),
        )
        .await
        .expect("disabled health transition succeeds")
        .expect("config exists");
    assert_eq!(disabled.status, "disconnected");
    assert!(!disabled.connected);
    assert_eq!(
        disabled.last_error.as_deref(),
        Some("channel config disabled")
    );

    let missing = repo
        .update_connection_status("missing-lifecycle-config", "connected", None)
        .await
        .expect("missing config is not a storage error");
    assert!(missing.is_none());
}

struct ChannelSeed<'a> {
    prefix: &'a str,
    outbox_id: &'a str,
    attempt_count: i32,
    max_attempts: i32,
    status: &'a str,
    next_retry: Option<DateTime<Utc>>,
}

async fn clean_channel_rows(pool: &PgPool, prefix: &str) {
    let like = format!("{prefix}%");
    for sql in [
        "DELETE FROM agistack_channel_webhook_events WHERE channel_config_id LIKE $1 OR id LIKE $1",
        "DELETE FROM agistack_channel_outbox_leases WHERE outbox_id LIKE $1",
        "DELETE FROM channel_outbox WHERE id LIKE $1",
        "DELETE FROM channel_session_bindings WHERE id LIKE $1",
        "DELETE FROM conversations WHERE id LIKE $1 OR project_id LIKE $1",
        "DELETE FROM channel_configs WHERE id LIKE $1",
        "DELETE FROM user_projects WHERE project_id LIKE $1 OR user_id LIKE $1",
        "DELETE FROM projects WHERE id LIKE $1",
        "DELETE FROM tenants WHERE id LIKE $1",
        "DELETE FROM users WHERE id LIKE $1",
    ] {
        sqlx::query(sql).bind(&like).execute(pool).await.unwrap();
    }
}

async fn seed_channel_outbox(pool: &PgPool, seed: ChannelSeed<'_>) {
    let user_id = format!("{}_user", seed.prefix);
    let tenant_id = format!("{}_tenant", seed.prefix);
    let project_id = format!("{}_project", seed.prefix);
    let config_id = format!("{}_config", seed.prefix);
    let conversation_id = format!("{}_conversation", seed.prefix);
    sqlx::query("INSERT INTO users (id, email) VALUES ($1, $2)")
        .bind(&user_id)
        .bind(format!("{}@example.test", seed.prefix))
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO tenants (id, name) VALUES ($1, $2)")
        .bind(&tenant_id)
        .bind(seed.prefix)
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO projects (id, tenant_id, name, owner_id) VALUES ($1, $2, $3, $4)")
        .bind(&project_id)
        .bind(&tenant_id)
        .bind(seed.prefix)
        .bind(&user_id)
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO user_projects (user_id, project_id, role) VALUES ($1, $2, 'admin')")
        .bind(&user_id)
        .bind(&project_id)
        .execute(pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO channel_configs \
            (id, project_id, channel_type, name, enabled, connection_mode, webhook_url, domain, status, created_at) \
         VALUES ($1, $2, 'feishu', $3, true, 'webhook', $4, 'feishu', 'connected', now())",
    )
    .bind(&config_id)
    .bind(&project_id)
    .bind(seed.prefix)
    .bind(format!("https://example.test/{}/webhook", seed.prefix))
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO channel_outbox \
            (id, project_id, channel_config_id, conversation_id, chat_id, content_text, \
             status, attempt_count, max_attempts, next_retry_at, created_at) \
         VALUES ($1, $2, $3, $4, $5, 'hello', $6, $7, $8, $9, now())",
    )
    .bind(seed.outbox_id)
    .bind(&project_id)
    .bind(&config_id)
    .bind(&conversation_id)
    .bind(format!("{}_chat", seed.prefix))
    .bind(seed.status)
    .bind(seed.attempt_count)
    .bind(seed.max_attempts)
    .bind(seed.next_retry)
    .execute(pool)
    .await
    .unwrap();
}

async fn seed_channel_binding(
    pool: &PgPool,
    binding_id: &str,
    project_id: &str,
    config_id: &str,
    conversation_id: &str,
    chat_id: &str,
    session_key: &str,
) {
    sqlx::query(
        "INSERT INTO channel_session_bindings \
            (id, project_id, channel_config_id, conversation_id, channel_type, chat_id, \
             chat_type, thread_id, topic_id, session_key, created_at) \
         VALUES ($1, $2, $3, $4, 'feishu', $5, 'group', 'thread-1', 'topic-1', $6, now())",
    )
    .bind(binding_id)
    .bind(project_id)
    .bind(config_id)
    .bind(conversation_id)
    .bind(chat_id)
    .bind(session_key)
    .execute(pool)
    .await
    .unwrap();
}

async fn lease_count(pool: &PgPool, outbox_id: &str) -> i64 {
    sqlx::query_as::<_, (i64,)>(
        "SELECT count(*) FROM agistack_channel_outbox_leases WHERE outbox_id = $1",
    )
    .bind(outbox_id)
    .fetch_one(pool)
    .await
    .unwrap()
    .0
}

async fn webhook_event_count(pool: &PgPool, channel_config_id: &str, idempotency_key: &str) -> i64 {
    sqlx::query_as::<_, (i64,)>(
        "SELECT count(*) \
         FROM agistack_channel_webhook_events \
         WHERE channel_config_id = $1 AND idempotency_key = $2",
    )
    .bind(channel_config_id)
    .bind(idempotency_key)
    .fetch_one(pool)
    .await
    .unwrap()
    .0
}

async fn conversation_count(pool: &PgPool, conversation_id: &str) -> i64 {
    sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM conversations WHERE id = $1")
        .bind(conversation_id)
        .fetch_one(pool)
        .await
        .unwrap()
        .0
}
