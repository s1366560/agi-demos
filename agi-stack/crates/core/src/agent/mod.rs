//! The agent orchestration layer: ReAct execution + the append-only Plan DAG.
//!
//! This is the Rust realization of the "robust · orchestratable" quality axis
//! from `06-agent-core-design.md`: [`react::ReActEngine`] gives crash-recoverable
//! round-boundary execution (ADR-0005); [`plan::Plan`] gives declarative,
//! level-triggered orchestration (ADR-0004).

pub mod plan;
pub mod react;
pub mod types;

pub use plan::{Plan, PlanStep, StepStatus};
pub use react::ReActEngine;
pub use types::{
    AgentAction, CompletedCall, Role, SessionState, SessionStatus, TranscriptEntry,
};
