//! The agent orchestration layer: ReAct execution + the append-only Plan DAG +
//! the pluggable runtime harness.
//!
//! This is the Rust realization of the "robust · orchestratable · hot-pluggable"
//! quality axes from `06-agent-core-design.md`: [`react::ReActEngine`] gives
//! crash-recoverable round-boundary execution (ADR-0005); [`plan::Plan`] gives
//! declarative, level-triggered orchestration (ADR-0004); [`harness`] makes the
//! *execution loop itself* pluggable (ADR-0008).

pub mod harness;
pub mod plan;
pub mod react;
pub mod types;

pub use harness::{
    EmbeddedHarness, HarnessCtx, HarnessPolicy, HarnessRegistry, PreparedAttempt, RuntimeHarness,
    SelectionReason, TurnOutcome,
};
pub use plan::{Plan, PlanStep, StepStatus};
pub use react::{pending_request, ReActEngine};
pub use types::{
    AgentAction, CompletedCall, HitlKind, HitlRequest, HitlResponse, Role, SessionState,
    SessionStatus, TranscriptEntry,
};
