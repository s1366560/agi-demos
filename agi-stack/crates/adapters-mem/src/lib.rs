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
//!   - [`event_stream::InMemoryEventStream`] — [`agistack_core::ports::EventStream`]
//!     (agent-event bus, F5; parity oracle for the Redis Streams tier)
//!   - [`object_store::InMemoryObjectStore`] — [`agistack_core::ports::ObjectStore`]
//!     (blob store, F6; parity oracle for the S3/MinIO tier)
//!   - [`container_runtime::InMemoryContainerRuntime`] — [`agistack_core::ports::ContainerRuntime`]
//!     (sandbox provisioning, F9; state-machine oracle for the Docker/bollard tier)
//!   - [`email::InMemoryEmailSender`] — [`agistack_core::ports::EmailSender`]
//!     (transactional email, F10; behavioural oracle for the lettre/SMTP tier)
//!   - [`clock::FixedClock`] / [`clock::SystemClock`] — [`agistack_core::Clock`]

pub mod changelog;
pub mod checkpoint;
pub mod clock;
pub mod container_runtime;
pub mod email;
pub mod embedding;
pub mod event_stream;
pub mod graph;
pub mod llm;
pub mod object_store;
pub mod repo;
pub mod vector;

pub use changelog::InMemoryChangeLog;
pub use checkpoint::InMemoryCheckpointStore;
pub use clock::FixedClock;
#[cfg(not(target_arch = "wasm32"))]
pub use clock::SystemClock;
pub use container_runtime::InMemoryContainerRuntime;
pub use email::InMemoryEmailSender;
pub use embedding::{HashEmbedding, NgramHashEmbedding};
pub use event_stream::InMemoryEventStream;
pub use graph::InMemoryGraphStore;
pub use llm::{ScriptedLlm, StubLlm};
pub use object_store::InMemoryObjectStore;
pub use repo::InMemoryMemoryRepository;
pub use vector::InMemoryVectorIndex;
