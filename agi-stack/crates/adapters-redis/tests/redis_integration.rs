//! Live cross-adapter parity test for the F5 event bus.
//!
//! Asserts the production [`RedisEventStream`] and the in-memory oracle
//! ([`InMemoryEventStream`]) expose **identical observable behaviour** — payload
//! ordering, incremental `read_after` paging, and exact `max_len` trimming —
//! against a real Redis. It is *gated*: set `REDIS_TEST_URI` (or rely on the
//! default `redis://localhost:6379`); if Redis is unreachable the test prints a
//! skip notice and passes, so offline / CI-without-Redis runs stay green.
//!
//! Each run uses a unique topic (nanosecond suffix) and `DEL`s it at start and
//! end, so the test is hermetic and leaves no residue on the shared Redis.

use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};

use agistack_adapters_mem::InMemoryEventStream;
use agistack_adapters_redis::{
    agent_finished_key, agent_running_key, connect, device_code_key, device_user_code_key,
    dlq_error_type_index_key, dlq_event_type_index_key, dlq_message_key, dlq_pending_index_key,
    dlq_stats_key, sandbox_http_services_key, sandbox_mcp_upstream_token_key,
    sandbox_preview_session_key, sandbox_terminal_session_key, worker_launch_cooldown_key,
    workspace_autonomy_cooldown_key, DeviceGrant, DlqListQuery, RedisDeviceGrantStore,
    RedisDlqRepository, RedisEventStream, RedisSandboxHttpRegistry, RedisWorkerLaunchStateStore,
    RedisWorkspaceAutonomyCooldownStore, SandboxHttpServiceRecord, SandboxMcpUpstreamTokenRecord,
    SandboxPreviewSessionRecord, SandboxTerminalSessionRecord,
};
use agistack_core::ports::EventStream;
use redis::streams::StreamRangeReply;
use serde_json::json;
use tokio::sync::Mutex;

static REDIS_DLQ_TEST_LOCK: Mutex<()> = Mutex::const_new(());

fn redis_uri() -> String {
    std::env::var("REDIS_TEST_URI").unwrap_or_else(|_| "redis://localhost:6379".to_string())
}

fn unique_topic(tag: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    format!("agistack-it:{tag}:{nanos}")
}

/// Connect to Redis or return `None` (with a printed skip notice) if unreachable.
async fn redis_or_skip() -> Option<RedisEventStream> {
    let uri = redis_uri();
    match connect(&uri).await {
        Ok(mut_stream) => Some(mut_stream),
        Err(e) => {
            eprintln!("[skip] Redis unreachable at {uri}: {e} — skipping F5 parity test");
            None
        }
    }
}

async fn redis_grants_or_skip() -> Option<RedisDeviceGrantStore> {
    let uri = redis_uri();
    match RedisDeviceGrantStore::connect(&uri).await {
        Ok(store) => Some(store),
        Err(e) => {
            eprintln!("[skip] Redis unreachable at {uri}: {e} — skipping device grant test");
            None
        }
    }
}

async fn redis_sandbox_http_registry_or_skip() -> Option<RedisSandboxHttpRegistry> {
    let uri = redis_uri();
    match RedisSandboxHttpRegistry::connect(&uri).await {
        Ok(store) => Some(store),
        Err(e) => {
            eprintln!(
                "[skip] Redis unreachable at {uri}: {e} — skipping sandbox HTTP registry test"
            );
            None
        }
    }
}

async fn redis_worker_launch_state_or_skip() -> Option<RedisWorkerLaunchStateStore> {
    let uri = redis_uri();
    match RedisWorkerLaunchStateStore::connect(&uri).await {
        Ok(store) => Some(store),
        Err(e) => {
            eprintln!("[skip] Redis unreachable at {uri}: {e} — skipping worker launch state test");
            None
        }
    }
}

async fn redis_workspace_autonomy_cooldown_or_skip() -> Option<RedisWorkspaceAutonomyCooldownStore>
{
    let uri = redis_uri();
    match RedisWorkspaceAutonomyCooldownStore::connect(&uri).await {
        Ok(store) => Some(store),
        Err(e) => {
            eprintln!(
                "[skip] Redis unreachable at {uri}: {e} — skipping workspace autonomy cooldown test"
            );
            None
        }
    }
}

async fn redis_dlq_or_skip() -> Option<RedisDlqRepository> {
    let uri = redis_uri();
    match RedisDlqRepository::connect(&uri).await {
        Ok(store) => Some(store),
        Err(e) => {
            eprintln!("[skip] Redis unreachable at {uri}: {e} — skipping admin DLQ test");
            None
        }
    }
}

async fn del(stream: &RedisEventStream, topic: &str) {
    // Best-effort cleanup via a throwaway append+trim is awkward; instead issue a
    // raw DEL through a fresh connection helper. RedisEventStream doesn't expose
    // DEL, so we reconnect with the low-level client here.
    let uri = redis_uri();
    if let Ok(client) = redis::Client::open(uri) {
        if let Ok(mut conn) = client.get_multiplexed_async_connection().await {
            let _: Result<i64, _> = redis::cmd("DEL").arg(topic).query_async(&mut conn).await;
        }
    }
    // Keep the reference used so the signature stays honest about needing a live stream.
    let _ = stream;
}

async fn del_keys(keys: &[String]) {
    let uri = redis_uri();
    if let Ok(client) = redis::Client::open(uri) {
        if let Ok(mut conn) = client.get_multiplexed_async_connection().await {
            let _: Result<i64, _> = redis::cmd("DEL").arg(keys).query_async(&mut conn).await;
        }
    }
}

async fn set_raw_with_ttl(key: &str, value: &str, ttl_millis: u64) {
    let client = redis::Client::open(redis_uri()).unwrap();
    let mut conn = client.get_multiplexed_async_connection().await.unwrap();
    let _: () = redis::cmd("PSETEX")
        .arg(key)
        .arg(ttl_millis)
        .arg(value)
        .query_async(&mut conn)
        .await
        .unwrap();
}

async fn pttl(key: &str) -> i64 {
    let client = redis::Client::open(redis_uri()).unwrap();
    let mut conn = client.get_multiplexed_async_connection().await.unwrap();
    redis::cmd("PTTL")
        .arg(key)
        .query_async(&mut conn)
        .await
        .unwrap()
}

async fn ttl(key: &str) -> Option<i64> {
    let uri = redis_uri();
    let client = redis::Client::open(uri).ok()?;
    let mut conn = client.get_multiplexed_async_connection().await.ok()?;
    redis::cmd("TTL").arg(key).query_async(&mut conn).await.ok()
}

async fn set_key(key: &str, value: &str, ttl_seconds: u64) {
    let uri = redis_uri();
    let client = redis::Client::open(uri).unwrap();
    let mut conn = client.get_multiplexed_async_connection().await.unwrap();
    let _: () = redis::cmd("SETEX")
        .arg(key)
        .arg(ttl_seconds.max(1))
        .arg(value)
        .query_async(&mut conn)
        .await
        .unwrap();
}

async fn redis_hash_snapshot(key: &str) -> BTreeMap<String, String> {
    let uri = redis_uri();
    let client = redis::Client::open(uri).unwrap();
    let mut conn = client.get_multiplexed_async_connection().await.unwrap();
    redis::cmd("HGETALL")
        .arg(key)
        .query_async(&mut conn)
        .await
        .unwrap()
}

async fn restore_redis_hash(key: &str, snapshot: BTreeMap<String, String>) {
    let uri = redis_uri();
    let client = redis::Client::open(uri).unwrap();
    let mut conn = client.get_multiplexed_async_connection().await.unwrap();
    let _: i64 = redis::cmd("DEL")
        .arg(key)
        .query_async(&mut conn)
        .await
        .unwrap();
    if snapshot.is_empty() {
        return;
    }
    let mut cmd = redis::cmd("HSET");
    cmd.arg(key);
    for (field, value) in snapshot {
        cmd.arg(field).arg(value);
    }
    let _: i64 = cmd.query_async(&mut conn).await.unwrap();
}

async fn payloads_after(
    s: &dyn EventStream,
    topic: &str,
    after: &str,
    limit: usize,
) -> Vec<String> {
    s.read_after(topic, after, limit)
        .await
        .unwrap()
        .into_iter()
        .map(|e| e.payload)
        .collect()
}

#[tokio::test]
async fn redis_matches_in_memory_ordering_and_paging() {
    let Some(redis) = redis_or_skip().await else {
        return;
    };
    let mem = InMemoryEventStream::new();
    let topic = unique_topic("order");
    del(&redis, &topic).await;

    let seed = ["evt-a", "evt-b", "evt-c", "evt-d", "evt-e"];
    let mut redis_ids = Vec::new();
    for p in seed {
        redis_ids.push(redis.append(&topic, p, 0).await.unwrap());
        mem.append(&topic, p, 0).await.unwrap();
    }

    // Full read from the start: payload sequence + count must match exactly.
    let r_all = payloads_after(&redis, &topic, "", 100).await;
    let m_all = payloads_after(&mem, &topic, "", 100).await;
    assert_eq!(r_all, seed.to_vec(), "redis full-read order");
    assert_eq!(r_all, m_all, "redis vs in-memory full-read parity");

    // Incremental paging: first 2, then the remainder after the last-seen id.
    let r_first = redis.read_after(&topic, "", 2).await.unwrap();
    let m_first = mem.read_after(&topic, "", 2).await.unwrap();
    assert_eq!(
        r_first.iter().map(|e| &e.payload).collect::<Vec<_>>(),
        m_first.iter().map(|e| &e.payload).collect::<Vec<_>>(),
        "first page payload parity"
    );

    let r_rest = payloads_after(&redis, &topic, &r_first.last().unwrap().id, 100).await;
    let m_rest = payloads_after(&mem, &topic, &m_first.last().unwrap().id, 100).await;
    assert_eq!(r_rest, vec!["evt-c", "evt-d", "evt-e"], "redis remainder");
    assert_eq!(
        r_rest, m_rest,
        "remainder parity (ids differ, payloads match)"
    );

    del(&redis, &topic).await;
}

#[tokio::test]
async fn redis_matches_in_memory_maxlen_trim() {
    let Some(redis) = redis_or_skip().await else {
        return;
    };
    let mem = InMemoryEventStream::new();
    let topic = unique_topic("trim");
    del(&redis, &topic).await;

    // Append 5 with max_len 3 → both tiers retain exactly the last 3, in order.
    for p in ["1", "2", "3", "4", "5"] {
        redis.append(&topic, p, 3).await.unwrap();
        mem.append(&topic, p, 3).await.unwrap();
    }

    let r = payloads_after(&redis, &topic, "", 100).await;
    let m = payloads_after(&mem, &topic, "", 100).await;
    assert_eq!(r, vec!["3", "4", "5"], "redis exact MAXLEN trim");
    assert_eq!(r, m, "redis vs in-memory trim parity");

    del(&redis, &topic).await;
}

#[tokio::test]
async fn redis_device_grants_match_python_keys_and_lifecycle() {
    let Some(store) = redis_grants_or_skip().await else {
        return;
    };
    let suffix = unique_topic("device-grant").replace(':', "-");
    let device_code = format!("device-{suffix}");
    let user_code = "ABCDEFGH";
    let keys = vec![
        device_code_key(&device_code),
        device_user_code_key(user_code),
    ];
    del_keys(&keys).await;

    let pending = DeviceGrant::pending(user_code);
    store
        .create_pending(&device_code, &pending, 600)
        .await
        .unwrap();
    assert!(store.user_code_exists(user_code).await.unwrap());
    assert_eq!(
        store.device_code_for_user_code(user_code).await.unwrap(),
        Some(device_code.clone())
    );
    assert_eq!(
        store.get(&device_code).await.unwrap(),
        Some(pending.clone())
    );

    // Python json.dumps emits different whitespace and may use a different
    // object-key order. Rust compares decoded fields rather than raw bytes.
    set_raw_with_ttl(
        &device_code_key(&device_code),
        r#"{ "access_token": null, "status": "pending", "user_code": "ABCDEFGH", "approved_user_id": null }"#,
        900,
    )
    .await;

    let approved = DeviceGrant::approved(user_code, "user-1", "ms_sk_test");
    assert!(store
        .compare_and_set(&device_code, &pending, &approved)
        .await
        .unwrap());
    let remaining_ttl = pttl(&device_code_key(&device_code)).await;
    assert!(
        (1..=900).contains(&remaining_ttl),
        "CAS must keep a sub-second TTL, got {remaining_ttl}ms"
    );
    assert!(!store
        .compare_and_set(&device_code, &pending, &approved)
        .await
        .unwrap());
    assert_eq!(
        store.get(&device_code).await.unwrap(),
        Some(approved.clone())
    );

    let consumed = DeviceGrant {
        status: "consumed".to_string(),
        ..approved.clone()
    };
    assert!(store
        .compare_and_set_and_delete_index(&device_code, &approved, &consumed)
        .await
        .unwrap());
    assert!(!store.user_code_exists(user_code).await.unwrap());
    assert!(!store
        .compare_and_delete_pair(&device_code, &approved)
        .await
        .unwrap());
    assert!(store
        .compare_and_delete_pair(&device_code, &consumed)
        .await
        .unwrap());
    assert_eq!(store.get(&device_code).await.unwrap(), None);

    // Missing grants are never recreated by either transition.
    assert!(!store
        .compare_and_set(&device_code, &pending, &approved)
        .await
        .unwrap());
}

#[tokio::test]
async fn redis_device_grant_approval_and_cancel_have_one_atomic_winner() {
    let Some(store) = redis_grants_or_skip().await else {
        return;
    };
    let suffix = unique_topic("device-grant-race").replace(':', "-");
    let device_code = format!("device-{suffix}");
    let user_code = "BCDEFGHJ";
    let keys = vec![
        device_code_key(&device_code),
        device_user_code_key(user_code),
    ];
    del_keys(&keys).await;

    let pending = DeviceGrant::pending(user_code);
    let approved = DeviceGrant::approved(user_code, "user-race", "ms_sk_race");
    store
        .create_pending(&device_code, &pending, 600)
        .await
        .unwrap();

    let approving_store = store.clone();
    let cancelling_store = store.clone();
    let (approved_won, cancel_won) = tokio::join!(
        approving_store.compare_and_set(&device_code, &pending, &approved),
        cancelling_store.compare_and_delete_pair(&device_code, &pending),
    );
    let approved_won = approved_won.unwrap();
    let cancel_won = cancel_won.unwrap();
    assert_ne!(approved_won, cancel_won, "exactly one transition must win");
    assert_eq!(
        store.get(&device_code).await.unwrap(),
        approved_won.then_some(approved)
    );

    store.delete_pair(&device_code, user_code).await.unwrap();
}

#[tokio::test]
async fn redis_sandbox_http_registry_persists_services_and_preview_sessions() {
    let Some(store) = redis_sandbox_http_registry_or_skip().await else {
        return;
    };
    let suffix = unique_topic("sandbox-http").replace(':', "-");
    let project_id = format!("project-{suffix}");
    let service_id = "web";
    let token = format!("preview-{suffix}");
    let keys = vec![
        sandbox_http_services_key(&project_id),
        sandbox_preview_session_key(&token),
    ];
    del_keys(&keys).await;

    let service = SandboxHttpServiceRecord {
        service_id: service_id.to_string(),
        name: "Docs".to_string(),
        source_type: "sandbox_internal".to_string(),
        status: "running".to_string(),
        service_url: "http://127.0.0.1:3000/docs".to_string(),
        preview_url: "http://web.project.preview.localhost:8000/".to_string(),
        ws_preview_url: Some("ws://web.project.preview.localhost:8000/".to_string()),
        sandbox_id: Some("sandbox-1".to_string()),
        auto_open: true,
        restart_token: Some("1700000000000".to_string()),
        updated_at: "1970-01-01T00:00:00.000+00:00".to_string(),
    };

    store
        .upsert_http_service(&project_id, &service)
        .await
        .unwrap();
    assert_eq!(
        store
            .get_http_service(&project_id, service_id)
            .await
            .unwrap(),
        Some(service.clone())
    );
    assert_eq!(
        store.list_http_services(&project_id).await.unwrap(),
        vec![service.clone()]
    );

    let session = SandboxPreviewSessionRecord {
        project_id: project_id.clone(),
        service_id: service_id.to_string(),
        expires_at_ms: 1_700_000_060_000,
    };
    store
        .create_preview_session(&token, &session, 60)
        .await
        .unwrap();
    assert_eq!(
        store.get_preview_session(&token).await.unwrap(),
        Some(session)
    );
    let session_ttl = ttl(&sandbox_preview_session_key(&token)).await.unwrap();
    assert!(
        (1..=60).contains(&session_ttl),
        "preview session should be Redis TTL-backed, got {session_ttl}"
    );

    assert!(store
        .remove_http_service(&project_id, service_id)
        .await
        .unwrap());
    assert!(store
        .get_http_service(&project_id, service_id)
        .await
        .unwrap()
        .is_none());

    del_keys(&keys).await;
}

#[tokio::test]
async fn redis_sandbox_terminal_sessions_are_ttl_persisted() {
    let Some(store) = redis_sandbox_http_registry_or_skip().await else {
        return;
    };
    let suffix = unique_topic("terminal-session").replace(':', "-");
    let project_id = format!("project-{suffix}");
    let session_id = "term-session";
    let key = sandbox_terminal_session_key(&project_id, session_id);
    del_keys(std::slice::from_ref(&key)).await;

    let session = SandboxTerminalSessionRecord {
        project_id: project_id.clone(),
        session_id: session_id.to_string(),
        cols: 120,
        rows: 40,
        connected: true,
        last_seen_at_ms: 1_700_000_000_000,
        expires_at_ms: 1_700_086_400_000,
    };
    store.upsert_terminal_session(&session, 60).await.unwrap();
    assert_eq!(
        store
            .get_terminal_session(&project_id, session_id)
            .await
            .unwrap(),
        Some(session)
    );
    let session_ttl = ttl(&key).await.unwrap();
    assert!(
        (1..=60).contains(&session_ttl),
        "terminal session should be Redis TTL-backed, got {session_ttl}"
    );

    assert!(store
        .remove_terminal_session(&project_id, session_id)
        .await
        .unwrap());
    assert!(store
        .get_terminal_session(&project_id, session_id)
        .await
        .unwrap()
        .is_none());

    del_keys(&[key]).await;
}

#[tokio::test]
async fn redis_sandbox_mcp_upstream_tokens_are_ttl_persisted() {
    let Some(store) = redis_sandbox_http_registry_or_skip().await else {
        return;
    };
    let suffix = unique_topic("mcp-token").replace(':', "-");
    let token = format!("mcp-token-{suffix}");
    let key = sandbox_mcp_upstream_token_key(&token);
    del_keys(std::slice::from_ref(&key)).await;

    let grant = SandboxMcpUpstreamTokenRecord {
        token: token.clone(),
        project_id: format!("project-{suffix}"),
        sandbox_id: "sandbox-1".to_string(),
        issued_at_ms: 1_700_000_000_000,
        expires_at_ms: 1_700_000_600_000,
    };
    store.create_mcp_upstream_token(&grant, 60).await.unwrap();
    assert_eq!(
        store.get_mcp_upstream_token(&token).await.unwrap(),
        Some(grant)
    );
    let token_ttl = ttl(&key).await.unwrap();
    assert!(
        (1..=60).contains(&token_ttl),
        "mcp upstream token should be Redis TTL-backed, got {token_ttl}"
    );

    del_keys(&[key]).await;
}

#[tokio::test]
async fn redis_worker_launch_state_matches_python_marker_keys() {
    let Some(store) = redis_worker_launch_state_or_skip().await else {
        return;
    };
    let suffix = unique_topic("worker-launch").replace(':', "-");
    let conversation_id = format!("conv-{suffix}");
    let cooldown_key = worker_launch_cooldown_key(&conversation_id);
    let running_key = agent_running_key(&conversation_id);
    let finished_key = agent_finished_key(&conversation_id);
    del_keys(&[
        cooldown_key.clone(),
        running_key.clone(),
        finished_key.clone(),
    ])
    .await;

    assert!(store
        .claim_worker_launch_cooldown(&conversation_id, 60)
        .await
        .unwrap());
    assert!(!store
        .claim_worker_launch_cooldown(&conversation_id, 60)
        .await
        .unwrap());
    let cooldown_ttl = ttl(&cooldown_key).await.unwrap();
    assert!(
        (1..=60).contains(&cooldown_ttl),
        "worker launch cooldown should be Redis TTL-backed, got {cooldown_ttl}"
    );

    assert!(!store.agent_running_exists(&conversation_id).await.unwrap());
    set_key(&running_key, "1", 60).await;
    assert!(store.agent_running_exists(&conversation_id).await.unwrap());
    set_key(&finished_key, "msg-1", 60).await;

    store
        .clear_reused_worker_session_markers(&conversation_id)
        .await
        .unwrap();
    assert_eq!(ttl(&cooldown_key).await.unwrap(), -2);
    assert_eq!(ttl(&finished_key).await.unwrap(), -2);
    assert!(store.agent_running_exists(&conversation_id).await.unwrap());

    del_keys(&[cooldown_key, running_key, finished_key]).await;
}

#[tokio::test]
async fn redis_worker_launch_refreshes_runtime_markers_like_python_heartbeat() {
    let Some(store) = redis_worker_launch_state_or_skip().await else {
        return;
    };
    let suffix = unique_topic("worker-launch-refresh").replace(':', "-");
    let conversation_id = format!("conv-{suffix}");
    let cooldown_key = worker_launch_cooldown_key(&conversation_id);
    let running_key = agent_running_key(&conversation_id);
    let finished_key = agent_finished_key(&conversation_id);
    del_keys(&[
        cooldown_key.clone(),
        running_key.clone(),
        finished_key.clone(),
    ])
    .await;

    assert_eq!(
        store
            .agent_finished_message_id(&conversation_id)
            .await
            .unwrap(),
        None
    );
    assert!(!store
        .refresh_worker_launch_cooldown(&conversation_id, 60)
        .await
        .unwrap());
    assert!(!store
        .refresh_existing_agent_running_marker(&conversation_id, 60)
        .await
        .unwrap());

    set_key(&cooldown_key, "1", 5).await;
    set_key(&running_key, "1", 5).await;
    assert!(store
        .refresh_worker_launch_cooldown(&conversation_id, 60)
        .await
        .unwrap());
    assert!(store
        .refresh_existing_agent_running_marker(&conversation_id, 60)
        .await
        .unwrap());
    let cooldown_ttl = ttl(&cooldown_key).await.unwrap();
    let running_ttl = ttl(&running_key).await.unwrap();
    assert!(
        (30..=60).contains(&cooldown_ttl),
        "worker launch cooldown should be refreshed, got {cooldown_ttl}"
    );
    assert!(
        (30..=60).contains(&running_ttl),
        "agent:running marker should be refreshed, got {running_ttl}"
    );

    set_key(&finished_key, "msg-1", 60).await;
    assert_eq!(
        store
            .agent_finished_message_id(&conversation_id)
            .await
            .unwrap(),
        Some("msg-1".to_string())
    );
    assert!(!store
        .refresh_existing_agent_running_marker(&conversation_id, 60)
        .await
        .unwrap());

    del_keys(&[cooldown_key, running_key, finished_key]).await;
}

#[tokio::test]
async fn redis_workspace_autonomy_cooldown_matches_python_key_and_ttl() {
    let Some(store) = redis_workspace_autonomy_cooldown_or_skip().await else {
        return;
    };
    let suffix = unique_topic("workspace-autonomy").replace(':', "-");
    let workspace_id = format!("workspace-{suffix}");
    let root_task_id = format!("root-{suffix}");
    let key = workspace_autonomy_cooldown_key(&workspace_id, &root_task_id);
    del_keys(std::slice::from_ref(&key)).await;

    assert!(!store
        .is_on_cooldown(&workspace_id, &root_task_id)
        .await
        .unwrap());
    store
        .mark_cooldown(&workspace_id, &root_task_id, 60)
        .await
        .unwrap();
    assert!(store
        .is_on_cooldown(&workspace_id, &root_task_id)
        .await
        .unwrap());
    let cooldown_ttl = ttl(&key).await.unwrap();
    assert!(
        (1..=60).contains(&cooldown_ttl),
        "workspace autonomy cooldown should be Redis TTL-backed, got {cooldown_ttl}"
    );

    del_keys(&[key]).await;
}

#[tokio::test]
async fn redis_dlq_reads_python_keys_filters_and_stats() {
    let Some(store) = redis_dlq_or_skip().await else {
        return;
    };
    let _dlq_guard = REDIS_DLQ_TEST_LOCK.lock().await;
    let suffix = unique_topic("dlq").replace(':', "-");
    let id1 = format!("dlq-{suffix}-1");
    let id2 = format!("dlq-{suffix}-2");
    let mut message_keys = vec![dlq_message_key(&id1), dlq_message_key(&id2)];
    let pending_key = dlq_pending_index_key().to_string();
    let error_key = dlq_error_type_index_key("RuntimeError");
    let agent_event_key = dlq_event_type_index_key("agent.failed");
    let channel_event_key = dlq_event_type_index_key("channel.failed");
    let stats_key = dlq_stats_key().to_string();
    let original_stats = redis_hash_snapshot(&stats_key).await;

    let uri = redis_uri();
    let client = redis::Client::open(uri).unwrap();
    let mut conn = client.get_multiplexed_async_connection().await.unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    let score1 = now - 20.0;
    let score2 = now - 10.0;
    for (id, event_type, score) in [
        (&id1, "agent.failed", score1),
        (&id2, "channel.failed", score2),
    ] {
        let payload = json!({
            "id": id,
            "event_id": format!("event-{id}"),
            "event_type": event_type,
            "event_data": "{\"ok\":false}",
            "routing_key": "agent.events.failed",
            "error": "boom",
            "error_type": "RuntimeError",
            "error_traceback": null,
            "retry_count": 1,
            "max_retries": 3,
            "first_failed_at": "2026-01-02T03:04:05+00:00",
            "last_failed_at": "2026-01-02T03:05:05+00:00",
            "next_retry_at": null,
            "status": "pending",
            "metadata": {"source": "integration"}
        })
        .to_string();
        let _: i64 = redis::cmd("HSET")
            .arg(dlq_message_key(id))
            .arg("data")
            .arg(payload)
            .query_async(&mut conn)
            .await
            .unwrap();
        for key in [&pending_key, &error_key] {
            let _: i64 = redis::cmd("ZADD")
                .arg(key)
                .arg(score)
                .arg(id)
                .query_async(&mut conn)
                .await
                .unwrap();
        }
        let event_key = if event_type == "agent.failed" {
            &agent_event_key
        } else {
            &channel_event_key
        };
        let _: i64 = redis::cmd("ZADD")
            .arg(event_key)
            .arg(score)
            .arg(id)
            .query_async(&mut conn)
            .await
            .unwrap();
    }
    let _: i64 = redis::cmd("HSET")
        .arg(&stats_key)
        .arg("total_messages")
        .arg("2")
        .arg("pending_count")
        .arg("2")
        .arg("retrying_count")
        .arg("0")
        .arg("discarded_count")
        .arg("0")
        .arg("expired_count")
        .arg("0")
        .arg("resolved_count")
        .arg("0")
        .arg("error:RuntimeError")
        .arg("2")
        .arg("event:agent.failed")
        .arg("1")
        .arg("event:channel.failed")
        .arg("1")
        .query_async(&mut conn)
        .await
        .unwrap();

    let by_error = store
        .list_messages(DlqListQuery {
            status: Some("pending"),
            event_type: Some("agent.failed"),
            error_type: Some("RuntimeError"),
            routing_key_pattern: Some("agent.events.*"),
            limit: 10,
            offset: 0,
        })
        .await
        .unwrap();
    assert_eq!(
        by_error
            .iter()
            .map(|message| &message.id)
            .collect::<Vec<_>>(),
        vec![&id2, &id1],
        "error_type takes precedence over event_type, matching Python RedisDLQAdapter"
    );
    assert_eq!(
        store
            .count_messages(DlqListQuery {
                status: Some("pending"),
                event_type: Some("agent.failed"),
                error_type: Some("RuntimeError"),
                routing_key_pattern: Some("agent.events.*"),
                limit: 10,
                offset: 0,
            })
            .await
            .unwrap(),
        2
    );

    let by_event = store
        .list_messages(DlqListQuery {
            status: Some("pending"),
            event_type: Some("agent.failed"),
            error_type: None,
            routing_key_pattern: Some("agent.events.*"),
            limit: 10,
            offset: 0,
        })
        .await
        .unwrap();
    assert_eq!(
        by_event
            .iter()
            .map(|message| &message.id)
            .collect::<Vec<_>>(),
        vec![&id1]
    );
    assert_eq!(
        store.get_message(&id1).await.unwrap().unwrap().metadata,
        json!({"source": "integration"})
    );

    let stats = store.stats().await.unwrap();
    assert_eq!(stats.total_messages, 2);
    assert_eq!(stats.pending_count, 2);
    assert_eq!(stats.error_type_counts.get("RuntimeError"), Some(&2));
    assert_eq!(stats.event_type_counts.get("agent.failed"), Some(&1));
    assert!(stats.oldest_message_age_seconds >= 0.0);

    assert_eq!(
        store
            .discard_message(&id1, "operator decision", "2026-01-02T04:00:00Z")
            .await
            .unwrap(),
        Some(true)
    );
    let discarded = store.get_message(&id1).await.unwrap().unwrap();
    assert_eq!(discarded.status, "discarded");
    assert_eq!(
        discarded.metadata["discard_reason"],
        json!("operator decision")
    );

    let expired_id = format!("dlq-{suffix}-expired");
    let resolved_id = format!("dlq-{suffix}-resolved");
    message_keys.push(dlq_message_key(&expired_id));
    message_keys.push(dlq_message_key(&resolved_id));
    let expired_payload = json!({
        "id": expired_id,
        "event_id": format!("event-{expired_id}"),
        "event_type": "agent.failed",
        "event_data": "{\"ok\":false}",
        "routing_key": "agent.events.failed",
        "error": "boom",
        "error_type": "RuntimeError",
        "retry_count": 1,
        "max_retries": 3,
        "first_failed_at": "2026-01-02T03:04:05+00:00",
        "last_failed_at": "2026-01-02T03:05:05+00:00",
        "next_retry_at": null,
        "status": "pending",
        "metadata": {}
    })
    .to_string();
    let _: i64 = redis::cmd("HSET")
        .arg(dlq_message_key(&expired_id))
        .arg("data")
        .arg(expired_payload)
        .query_async(&mut conn)
        .await
        .unwrap();
    for key in [&pending_key, &error_key, &agent_event_key] {
        let _: i64 = redis::cmd("ZADD")
            .arg(key)
            .arg(now - 7_200.0)
            .arg(&expired_id)
            .query_async(&mut conn)
            .await
            .unwrap();
    }
    assert_eq!(store.cleanup_expired(1).await.unwrap(), 1);
    assert_eq!(
        store
            .get_message(&expired_id)
            .await
            .unwrap()
            .unwrap()
            .status,
        "expired"
    );

    let resolved_payload = json!({
        "id": resolved_id,
        "event_id": format!("event-{resolved_id}"),
        "event_type": "agent.failed",
        "event_data": "{\"ok\":false}",
        "routing_key": "agent.events.failed",
        "error": "boom",
        "error_type": "RuntimeError",
        "retry_count": 1,
        "max_retries": 3,
        "first_failed_at": "2026-01-02T03:04:05+00:00",
        "last_failed_at": "2026-01-02T03:05:05+00:00",
        "next_retry_at": null,
        "status": "resolved",
        "metadata": {}
    })
    .to_string();
    let _: i64 = redis::cmd("HSET")
        .arg(dlq_message_key(&resolved_id))
        .arg("data")
        .arg(resolved_payload)
        .query_async(&mut conn)
        .await
        .unwrap();
    for key in [&pending_key, &error_key, &agent_event_key] {
        let _: i64 = redis::cmd("ZADD")
            .arg(key)
            .arg(now - 7_200.0)
            .arg(&resolved_id)
            .query_async(&mut conn)
            .await
            .unwrap();
    }
    assert_eq!(store.cleanup_resolved(1).await.unwrap(), 1);
    assert!(store.get_message(&resolved_id).await.unwrap().is_none());

    let _: i64 = redis::cmd("ZREM")
        .arg(&pending_key)
        .arg(&id1)
        .arg(&id2)
        .arg(&expired_id)
        .arg(&resolved_id)
        .query_async(&mut conn)
        .await
        .unwrap();
    let _: i64 = redis::cmd("ZREM")
        .arg(&error_key)
        .arg(&id1)
        .arg(&id2)
        .arg(&expired_id)
        .arg(&resolved_id)
        .query_async(&mut conn)
        .await
        .unwrap();
    let _: i64 = redis::cmd("ZREM")
        .arg(&agent_event_key)
        .arg(&id1)
        .arg(&expired_id)
        .arg(&resolved_id)
        .query_async(&mut conn)
        .await
        .unwrap();
    let _: i64 = redis::cmd("ZREM")
        .arg(&channel_event_key)
        .arg(&id2)
        .query_async(&mut conn)
        .await
        .unwrap();
    del_keys(&message_keys).await;
    restore_redis_hash(&stats_key, original_stats).await;
}

#[tokio::test]
async fn redis_dlq_retry_republishes_to_unified_event_stream() {
    let Some(store) = redis_dlq_or_skip().await else {
        return;
    };
    let _dlq_guard = REDIS_DLQ_TEST_LOCK.lock().await;
    let suffix = unique_topic("dlq-retry").replace(':', "-");
    let message_id = format!("dlq-{suffix}");
    let event_id = format!("event-{suffix}");
    let routing_key = format!("agent.{suffix}.retry");
    let stream_key = format!("events:{routing_key}");
    let message_key = dlq_message_key(&message_id);
    let pending_key = dlq_pending_index_key().to_string();
    let error_key = dlq_error_type_index_key("RuntimeError");
    let event_key = dlq_event_type_index_key("agent.failed");
    let stats_key = dlq_stats_key().to_string();
    let original_stats = redis_hash_snapshot(&stats_key).await;

    let uri = redis_uri();
    let client = redis::Client::open(uri).unwrap();
    let mut conn = client.get_multiplexed_async_connection().await.unwrap();
    del_keys(&[message_key.clone(), stream_key.clone()]).await;
    let _: i64 = redis::cmd("DEL")
        .arg(&stats_key)
        .query_async(&mut conn)
        .await
        .unwrap();

    let envelope = json!({
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": "agent.failed",
        "timestamp": "2026-01-02T03:04:05+00:00",
        "source": "memstack",
        "correlation_id": "corr-dlq-retry",
        "causation_id": null,
        "payload": {"ok": false},
        "metadata": {"source": "integration"}
    });
    let payload = json!({
        "id": message_id,
        "event_id": envelope["event_id"].as_str().unwrap(),
        "event_type": "agent.failed",
        "event_data": envelope.to_string(),
        "routing_key": routing_key,
        "error": "boom",
        "error_type": "RuntimeError",
        "error_traceback": null,
        "retry_count": 0,
        "max_retries": 3,
        "first_failed_at": "2026-01-02T03:04:05+00:00",
        "last_failed_at": "2026-01-02T03:05:05+00:00",
        "next_retry_at": null,
        "status": "pending",
        "metadata": {"source": "integration"}
    })
    .to_string();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    let _: i64 = redis::cmd("HSET")
        .arg(&message_key)
        .arg("data")
        .arg(payload)
        .query_async(&mut conn)
        .await
        .unwrap();
    for key in [&pending_key, &error_key, &event_key] {
        let _: i64 = redis::cmd("ZADD")
            .arg(key)
            .arg(now)
            .arg(&message_id)
            .query_async(&mut conn)
            .await
            .unwrap();
    }
    let _: i64 = redis::cmd("HSET")
        .arg(&stats_key)
        .arg("total_messages")
        .arg("1")
        .arg("pending_count")
        .arg("1")
        .arg("retrying_count")
        .arg("0")
        .arg("discarded_count")
        .arg("0")
        .arg("expired_count")
        .arg("0")
        .arg("resolved_count")
        .arg("0")
        .arg("error:RuntimeError")
        .arg("1")
        .arg("event:agent.failed")
        .arg("1")
        .query_async(&mut conn)
        .await
        .unwrap();

    assert_eq!(store.retry_message(&message_id).await.unwrap(), Some(true));
    let resolved = store.get_message(&message_id).await.unwrap().unwrap();
    assert_eq!(resolved.status, "resolved");
    assert_eq!(resolved.retry_count, 1);
    let stats = store.stats().await.unwrap();
    assert_eq!(stats.pending_count, 0);
    assert_eq!(stats.resolved_count, 1);
    let pending_members: Vec<String> = redis::cmd("ZRANGE")
        .arg(&pending_key)
        .arg(0)
        .arg(-1)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!(!pending_members.contains(&message_id));

    let reply: StreamRangeReply = redis::cmd("XRANGE")
        .arg(&stream_key)
        .arg("-")
        .arg("+")
        .arg("COUNT")
        .arg(1)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert_eq!(reply.ids.len(), 1);
    let entry = &reply.ids[0];
    let stream_event_id: String = entry.get("event_id").unwrap();
    let stream_event_type: String = entry.get("event_type").unwrap();
    let stream_schema_version: String = entry.get("schema_version").unwrap();
    let stream_routing_key: String = entry.get("routing_key").unwrap();
    let stream_data: String = entry.get("data").unwrap();
    assert_eq!(stream_event_id, envelope["event_id"].as_str().unwrap());
    assert_eq!(stream_event_type, "agent.failed");
    assert_eq!(stream_schema_version, "1.0");
    assert_eq!(stream_routing_key, routing_key);
    let stream_envelope: serde_json::Value = serde_json::from_str(&stream_data).unwrap();
    assert_eq!(stream_envelope["payload"], json!({"ok": false}));
    assert_eq!(
        stream_envelope["metadata"],
        json!({"source": "integration"})
    );
    let missing_id = format!("dlq-missing-{suffix}");
    let batch = store
        .retry_batch(&[message_id.clone(), missing_id.clone()])
        .await
        .unwrap();
    assert_eq!(batch.get(&message_id), Some(&false));
    assert_eq!(batch.get(&missing_id), Some(&false));

    let _: i64 = redis::cmd("ZREM")
        .arg(&pending_key)
        .arg(&message_id)
        .query_async(&mut conn)
        .await
        .unwrap();
    let _: i64 = redis::cmd("ZREM")
        .arg(&error_key)
        .arg(&message_id)
        .query_async(&mut conn)
        .await
        .unwrap();
    let _: i64 = redis::cmd("ZREM")
        .arg(&event_key)
        .arg(&message_id)
        .query_async(&mut conn)
        .await
        .unwrap();
    del_keys(&[message_key, stream_key]).await;
    restore_redis_hash(&stats_key, original_stats).await;
}
