//! In-memory [`EventStream`] — the test/browser tier of the agent-event bus
//! (F5). Mirrors the Redis Streams adapter's observable behaviour (append order,
//! `max_len` trimming, incremental read-after) without any I/O, so it backs unit
//! tests and the wasm build and serves as the parity oracle for the Redis tier.
//!
//! Ids are zero-padded monotonic counters (`{:020}`) so lexical string ordering
//! equals append ordering — the same property Redis stream ids have — which makes
//! `read_after` a binary search for the first id greater than `after_id`. Ids are
//! per-adapter opaque handles; callers echo them back and never compare them
//! across adapters.

use std::collections::HashMap;
use std::sync::Mutex;

use async_trait::async_trait;

use agistack_core::ports::{CoreError, CoreResult, EventStream, StreamEntry};

/// Process-local event bus: `topic -> ordered entries`, plus a global monotonic
/// counter for id assignment. Cloneable handles share one backing store via
/// `Arc` at the call site if needed; here it is a plain `Mutex` for simplicity.
#[derive(Default)]
pub struct InMemoryEventStream {
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    topics: HashMap<String, Vec<StreamEntry>>,
    seq: u64,
}

impl InMemoryEventStream {
    pub fn new() -> Self {
        Self::default()
    }
}

/// Normalise the "from the beginning" sentinels to an id that sorts before every
/// real id (all real ids are 20-digit, so `""` and `"0"` both sort before them).
fn from_start(after_id: &str) -> &str {
    if after_id == "0" {
        ""
    } else {
        after_id
    }
}

fn poisoned() -> CoreError {
    CoreError::Event("poisoned event stream lock".into())
}

#[async_trait]
impl EventStream for InMemoryEventStream {
    async fn append(&self, topic: &str, payload: &str, max_len: usize) -> CoreResult<String> {
        let mut inner = self.inner.lock().map_err(|_| poisoned())?;
        inner.seq += 1;
        let id = format!("{:020}", inner.seq);
        let entry = StreamEntry {
            id: id.clone(),
            payload: payload.to_string(),
        };
        let entries = inner.topics.entry(topic.to_string()).or_default();
        entries.push(entry);
        if max_len > 0 && entries.len() > max_len {
            let overflow = entries.len() - max_len;
            entries.drain(0..overflow);
        }
        Ok(id)
    }

    async fn read_after(
        &self,
        topic: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        let after = from_start(after_id);
        let inner = self.inner.lock().map_err(|_| poisoned())?;
        let Some(entries) = inner.topics.get(topic) else {
            return Ok(Vec::new());
        };
        // Ids are zero-padded monotonic, so entries are sorted by id: binary
        // search the first entry past `after` instead of scanning the topic.
        let start = entries.partition_point(|e| e.id.as_str() <= after);
        Ok(entries[start..].iter().take(limit).cloned().collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    #[test]
    fn append_then_read_from_start_preserves_order() {
        let s = InMemoryEventStream::new();
        for p in ["a", "b", "c"] {
            block_on(s.append("agent:events:c1", p, 0)).unwrap();
        }
        let got: Vec<String> = block_on(s.read_after("agent:events:c1", "", 100))
            .unwrap()
            .into_iter()
            .map(|e| e.payload)
            .collect();
        assert_eq!(got, vec!["a", "b", "c"]);
    }

    #[test]
    fn topics_are_isolated() {
        let s = InMemoryEventStream::new();
        block_on(s.append("t1", "x", 0)).unwrap();
        block_on(s.append("t2", "y", 0)).unwrap();
        let t1: Vec<String> = block_on(s.read_after("t1", "", 100))
            .unwrap()
            .into_iter()
            .map(|e| e.payload)
            .collect();
        assert_eq!(t1, vec!["x"]);
        // unknown topic reads empty
        assert!(block_on(s.read_after("nope", "", 100)).unwrap().is_empty());
    }

    #[test]
    fn incremental_read_after_last_id() {
        let s = InMemoryEventStream::new();
        for p in ["a", "b", "c", "d"] {
            block_on(s.append("t", p, 0)).unwrap();
        }
        let first = block_on(s.read_after("t", "", 2)).unwrap();
        assert_eq!(
            first.iter().map(|e| e.payload.as_str()).collect::<Vec<_>>(),
            vec!["a", "b"]
        );
        let last_id = &first.last().unwrap().id;
        let rest: Vec<String> = block_on(s.read_after("t", last_id, 100))
            .unwrap()
            .into_iter()
            .map(|e| e.payload)
            .collect();
        assert_eq!(rest, vec!["c", "d"]);
    }

    #[test]
    fn max_len_trims_to_most_recent() {
        let s = InMemoryEventStream::new();
        for p in ["a", "b", "c", "d", "e"] {
            block_on(s.append("t", p, 3)).unwrap();
        }
        let got: Vec<String> = block_on(s.read_after("t", "", 100))
            .unwrap()
            .into_iter()
            .map(|e| e.payload)
            .collect();
        assert_eq!(got, vec!["c", "d", "e"]);
    }

    #[test]
    fn zero_sentinel_reads_from_start() {
        let s = InMemoryEventStream::new();
        block_on(s.append("t", "a", 0)).unwrap();
        let got = block_on(s.read_after("t", "0", 100)).unwrap();
        assert_eq!(got.len(), 1);
    }

    #[test]
    fn poisoned_lock_returns_event_error() {
        static PANIC_HOOK_LOCK: Mutex<()> = Mutex::new(());

        let s = InMemoryEventStream::new();
        let _panic_hook_guard = PANIC_HOOK_LOCK.lock().unwrap();
        let previous_hook = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let poisoned = std::panic::catch_unwind(|| {
            let _guard = s.inner.lock().unwrap();
            panic!("poison event stream mutex");
        });
        std::panic::set_hook(previous_hook);
        assert!(poisoned.is_err());

        let err = block_on(s.append("t", "a", 0)).unwrap_err();
        assert!(
            matches!(err, CoreError::Event(message) if message == "poisoned event stream lock")
        );
    }
}
