//! `agistack-core`: the runtime-agnostic portable core of agi-stack.
//!
//! It is the production realization of the architecture in
//! `agi-stack/docs/architecture/` — distilled from the decision spike in
//! `spikes/rust-portable-core/`. It carries the domain model, the hexagonal
//! ports, the `MemoryService`, and the agent orchestration (ReAct + Plan DAG).
//!
//! Portability discipline (`01-portable-core.md` §1, ADR-0001):
//!   - no tokio, no runtime-specific APIs;
//!   - no `std::time` (time is injected via [`ports::Clock`]);
//!   - no task spawning inside the core;
//!   - every side effect is a port in [`ports`].
//!
//! These rules are what let the same crate compile unchanged to native servers,
//! `wasm32-unknown-unknown`, iOS and Android.

pub mod agent;
pub mod model;
pub mod ports;
pub mod service;
pub mod util;

pub use agent::{
    pending_request, AgentAction, EmbeddedHarness, HarnessCtx, HarnessPolicy, HarnessRegistry,
    HitlKind, HitlRequest, HitlResponse, Plan, PlanStep, PreparedAttempt, ReActEngine, Role,
    RuntimeHarness, SelectionReason, SessionState, SessionStatus, StepStatus, TranscriptEntry,
    TurnOutcome,
};
pub use model::{Entity, Episode, Memory, Project, SourceType};
pub use ports::{
    ChangeEvent, ChangeLog, CheckpointStore, Clock, CoreError, CoreResult, EmbeddingPort, LlmPort,
    MemoryDraft, MemoryRepository, ScoredId, ToolHost, VectorIndexPort,
};
pub use service::MemoryService;
