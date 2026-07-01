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
pub mod graph;
pub mod model;
pub mod ports;
pub mod service;
pub mod sync;
pub mod util;

pub use agent::{
    pending_request, AgentAction, CostBudget, CostTracker, DoomLoopDetector, EmbeddedHarness,
    HarnessCtx, HarnessPolicy, HarnessRegistry, Health, HitlKind, HitlRequest, HitlResponse,
    MiniOrchestrator, NextAction, OutcomeKind, Plan, PlanStep, PlanStore, PreparedAttempt,
    ReActEngine, Role, RuntimeHarness, RuntimePlan, SelectionReason, SessionState, SessionStatus,
    StepOutcome, StepRunner, StepStatus, SupervisorPort, SupervisorVerdict, TranscriptEntry,
    TriggerReason, TurnOutcome,
};
pub use graph::{
    hybrid_rank, jaccard, mmr_rerank, rrf_fuse, time_decay, tokenize, Candidate, RankedId,
    HALF_LIFE_DAYS, KEYWORD_WEIGHT, MMR_LAMBDA, MS_PER_DAY, RRF_K, VECTOR_WEIGHT,
};
pub use model::{Entity, Episode, GraphEntity, Memory, Project, Relationship, SourceType, Subgraph};
pub use ports::{
    ChangeEvent, ChangeLog, CheckpointStore, Clock, ContainerRuntime, ContainerSpec,
    ContainerState, ContainerStatus, CoreError, CoreResult, EmailMessage, EmailSender,
    EmbeddingPort, EventStream, GraphStore, LlmPort, MemoryDraft, MemoryRepository, ObjectMeta,
    ObjectStore, ScoredId, StreamEntry, ToolHost, VectorIndexPort,
};
pub use service::MemoryService;
pub use sync::{reconcile, Replica, SyncRecord, VersionVector};
