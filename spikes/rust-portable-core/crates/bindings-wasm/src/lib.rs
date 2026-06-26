//! Web (WASM) binding for the portable core.
//!
//! Same `MemoryService` + adapters as the native server — only the FFI shell
//! differs. Async methods are bridged to JS Promises via `future_to_promise`,
//! which keeps the returned futures `'static` (no borrow of `&self`).

use std::sync::Arc;

use js_sys::Promise;
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::future_to_promise;

use memstack_adapters_mem::{FixedClock, HashEmbedding, InMemoryMemoryRepository, StubLlm};
use memstack_core::{Episode, MemoryService, SourceType};

#[wasm_bindgen]
pub struct MemstackCore {
    service: MemoryService,
}

impl Default for MemstackCore {
    fn default() -> Self {
        Self::new()
    }
}

#[wasm_bindgen]
impl MemstackCore {
    #[wasm_bindgen(constructor)]
    pub fn new() -> MemstackCore {
        MemstackCore {
            service: MemoryService::new(
                Arc::new(InMemoryMemoryRepository::new()),
                Arc::new(StubLlm),
                Arc::new(HashEmbedding::new(8)),
                // Deterministic clock: SystemClock is unavailable on wasm by design.
                Arc::new(FixedClock(1_700_000_000_000)),
            ),
        }
    }

    /// Promise -> the created Memory as a JSON string.
    #[wasm_bindgen]
    pub fn ingest(&self, project_id: String, author_id: String, content: String) -> Promise {
        let service = self.service.clone();
        future_to_promise(async move {
            let episode = Episode {
                content,
                source_type: SourceType::Text,
                valid_at_ms: 0,
                name: None,
                project_id: Some(project_id.clone()),
                user_id: None,
            };
            let memory = service
                .ingest_episode(&project_id, &author_id, &episode)
                .await
                .map_err(|e| JsValue::from_str(&e.to_string()))?;
            let json =
                serde_json::to_string(&memory).map_err(|e| JsValue::from_str(&e.to_string()))?;
            Ok(JsValue::from_str(&json))
        })
    }

    /// Promise -> JSON array of matching Memories.
    #[wasm_bindgen]
    pub fn search(&self, project_id: String, q: String, limit: usize) -> Promise {
        let service = self.service.clone();
        future_to_promise(async move {
            let hits = service
                .search(&project_id, &q, limit)
                .await
                .map_err(|e| JsValue::from_str(&e.to_string()))?;
            let json =
                serde_json::to_string(&hits).map_err(|e| JsValue::from_str(&e.to_string()))?;
            Ok(JsValue::from_str(&json))
        })
    }
}
