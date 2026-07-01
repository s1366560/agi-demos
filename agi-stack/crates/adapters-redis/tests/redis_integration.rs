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
use agistack_adapters_redis::{connect, RedisEventStream};
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

async fn del(stream: &RedisEventStream, topic: &str) {
    // Best-effort cleanup via a throwaway append+trim is awkward; instead issue a
    // raw DEL through a fresh connection helper. RedisEventStream doesn't expose
    // DEL, so we reconnect with the low-level client here.
    let uri = redis_uri();
    if let Ok(client) = redis::Client::open(uri) {
        if let Ok(mut conn) = client.get_multiplexed_async_connection().await {
            let _: Result<i64, _> = redis::cmd("DEL")
                .arg(topic)
                .query_async(&mut conn)
                .await;
        }
    }
    // Keep the reference used so the signature stays honest about needing a live stream.
    let _ = stream;
}

async fn payloads_after(s: &dyn EventStream, topic: &str, after: &str, limit: usize) -> Vec<String> {
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
    assert_eq!(r_rest, m_rest, "remainder parity (ids differ, payloads match)");

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
