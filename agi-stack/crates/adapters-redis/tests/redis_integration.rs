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

use std::time::{SystemTime, UNIX_EPOCH};

use agistack_adapters_mem::InMemoryEventStream;
use agistack_adapters_redis::{
    agent_finished_key, agent_running_key, connect, device_code_key, device_user_code_key,
    sandbox_http_services_key, sandbox_mcp_upstream_token_key, sandbox_preview_session_key,
    sandbox_terminal_session_key, worker_launch_cooldown_key, workspace_autonomy_cooldown_key,
    DeviceGrant, RedisDeviceGrantStore, RedisEventStream, RedisSandboxHttpRegistry,
    RedisWorkerLaunchStateStore, RedisWorkspaceAutonomyCooldownStore, SandboxHttpServiceRecord,
    SandboxMcpUpstreamTokenRecord, SandboxPreviewSessionRecord, SandboxTerminalSessionRecord,
};
use agistack_core::ports::EventStream;

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
    assert_eq!(store.get(&device_code).await.unwrap(), Some(pending));

    let approved = DeviceGrant::approved(user_code, "user-1", "ms_sk_test");
    store
        .save_preserving_ttl(&device_code, &approved, 600)
        .await
        .unwrap();
    assert_eq!(store.get(&device_code).await.unwrap(), Some(approved));

    store.delete_pair(&device_code, user_code).await.unwrap();
    assert!(!store.user_code_exists(user_code).await.unwrap());
    assert_eq!(store.get(&device_code).await.unwrap(), None);
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
