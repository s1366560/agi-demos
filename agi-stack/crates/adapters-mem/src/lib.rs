//! `agistack-adapters-mem`: portable, dependency-light **in-memory adapters** for
//! every core port — the test/browser tier of agi-stack.
//!
//! These compile to native, wasm, iOS and Android unchanged (the only platform
//! split is [`clock::SystemClock`], gated off wasm). On the server they are swapped
//! for the heavy stack (Postgres/pgvector/Neo4j); on device for the embedded stack
//! (SQLite/sqlite-vec, see `agistack-adapters-device`). The portable core never
//! changes — only which adapter is wired (`02-platform-adapters.md`).
//!
//! Provided adapters:
//!   - [`repo::InMemoryMemoryRepository`]  — [`agistack_core::MemoryRepository`]
//!   - [`llm::StubLlm`] / [`llm::ScriptedLlm`] — [`agistack_core::LlmPort`]
//!   - [`embedding::HashEmbedding`]        — [`agistack_core::EmbeddingPort`]
//!     (toy bag-of-words hash); [`embedding::NgramHashEmbedding`] adds char
//!     n-gram sub-word signal at higher dim for the on-device vector bench
//!   - [`vector::InMemoryVectorIndex`]     — [`agistack_core::VectorIndexPort`]
//!   - [`checkpoint::InMemoryCheckpointStore`] — [`agistack_core::CheckpointStore`]
//!   - [`changelog::InMemoryChangeLog`]    — [`agistack_core::ChangeLog`]
//!   - [`clock::FixedClock`] / [`clock::SystemClock`] — [`agistack_core::Clock`]

pub mod changelog;
pub mod checkpoint;
pub mod clock;
pub mod embedding;
pub mod llm;
pub mod repo;
pub mod vector;

pub use changelog::InMemoryChangeLog;
pub use checkpoint::InMemoryCheckpointStore;
#[cfg(not(target_arch = "wasm32"))]
pub use clock::SystemClock;
pub use clock::FixedClock;
pub use embedding::{HashEmbedding, NgramHashEmbedding};
pub use llm::{ScriptedLlm, StubLlm};
pub use repo::InMemoryMemoryRepository;
pub use vector::InMemoryVectorIndex;
