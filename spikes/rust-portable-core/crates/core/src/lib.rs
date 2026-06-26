//! memstack-core: the portable core for the cross-platform spike.
//!
//! Mirrors a real slice of the Python backend:
//!   - `src/domain/model/memory/{memory,episode}.py`  -> [`model`]
//!   - `src/domain/ports/repositories/memory_repository.py` -> [`ports::MemoryRepository`]
//!
//! Design rules that make it portable (see rust-spike-plan.md, risk #1):
//!   - no tokio, no runtime-specific APIs
//!   - no `std::time` (time is injected via [`ports::Clock`])
//!   - no task spawning inside the core
//!   - async via `async-trait`, executor chosen by the host (native/wasm/uniffi)

pub mod model;
pub mod ports;
pub mod service;
pub mod util;

pub use model::{Entity, Episode, Memory, SourceType};
pub use ports::{
    Clock, CoreError, CoreResult, EmbeddingPort, LlmPort, MemoryDraft, MemoryRepository,
};
pub use service::MemoryService;
