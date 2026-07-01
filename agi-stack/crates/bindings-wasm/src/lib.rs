//! Web (WASM) binding: the **same** portable core that runs on the server and on
//! device, embedded directly in the browser as `core-as-guest` (01/03 docs).
//!
//! Only the FFI shell differs from the native server — the `MemoryService` and
//! in-memory adapters are identical. Two web-specific concerns are handled here:
//!
//!   1. **Time**: `SystemClock` (`std::time`) panics on `wasm32-unknown-unknown`,
//!      so the host injects [`WasmClock`], which reads wall-clock millis from the
//!      JS `Date.now()`. This is the platform split the `Clock` port exists for
//!      (ADR-0001) — the core stays runtime-agnostic.
//!   2. **Async**: core futures are bridged to JS `Promise`s via
//!      `future_to_promise`, which requires `'static` futures — hence each method
//!      clones the (cheap, `Arc`-backed) `MemoryService` before `await`.

use std::sync::Arc;

use js_sys::Promise;
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::future_to_promise;

use agistack_adapters_mem::{HashEmbedding, InMemoryMemoryRepository, InMemoryVectorIndex, StubLlm};
use agistack_core::ports::Clock;
use agistack_core::{Episode, MemoryService, SourceType};

/// Wall-clock time for the browser, backed by JS `Date.now()` (millis since the
/// Unix epoch). The web counterpart to `SystemClock`, which is unavailable on
/// `wasm32-unknown-unknown`.
struct WasmClock;

impl Clock for WasmClock {
    fn now_ms(&self) -> i64 {
        js_sys::Date::now() as i64
    }
}

/// The portable core exposed to JS/TS. Construct once, then call `ingest` /
/// `search` / `semanticSearch`; each returns a `Promise`.
#[wasm_bindgen]
pub struct AgistackCore {
    service: MemoryService,
}

impl Default for AgistackCore {
    fn default() -> Self {
        Self::new()
    }
}

#[wasm_bindgen]
impl AgistackCore {
    #[wasm_bindgen(constructor)]
    pub fn new() -> AgistackCore {
        let dim = 32;
        let service = MemoryService::new(
            Arc::new(InMemoryMemoryRepository::new()),
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(dim)),
            Arc::new(WasmClock),
        )
        .with_vectors(Arc::new(InMemoryVectorIndex::new()));
        AgistackCore { service }
    }

    /// Ingest an episode. Promise -> the created `Memory` as a JSON string.
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
                .map_err(to_js)?;
            Ok(JsValue::from_str(&serde_json::to_string(&memory).map_err(to_js)?))
        })
    }

    /// Keyword search. Promise -> JSON array of matching `Memory` objects.
    #[wasm_bindgen]
    pub fn search(&self, project_id: String, q: String, limit: usize) -> Promise {
        let service = self.service.clone();
        future_to_promise(async move {
            let hits = service.search(&project_id, &q, limit).await.map_err(to_js)?;
            Ok(JsValue::from_str(&serde_json::to_string(&hits).map_err(to_js)?))
        })
    }

    /// Vector/semantic search over the in-memory index. Promise -> JSON array.
    #[wasm_bindgen(js_name = semanticSearch)]
    pub fn semantic_search(&self, project_id: String, q: String, limit: usize) -> Promise {
        let service = self.service.clone();
        future_to_promise(async move {
            let hits = service
                .semantic_search(&project_id, &q, limit)
                .await
                .map_err(to_js)?;
            Ok(JsValue::from_str(&serde_json::to_string(&hits).map_err(to_js)?))
        })
    }
}

fn to_js<E: std::fmt::Display>(e: E) -> JsValue {
    JsValue::from_str(&e.to_string())
}
