//! The ReAct engine: a runtime-agnostic Think → Act → Observe loop with
//! **round-boundary checkpointing** and **crash recovery** (ADR-0005).
//!
//! Robustness model:
//!   - Every iteration is a *round* with a monotonic counter.
//!   - After a tool executes, its output is persisted **immediately**
//!     (incremental write) so a crash cannot cause the tool to run twice.
//!   - At each round boundary the whole [`SessionState`] is checkpointed.
//!   - [`run`](ReActEngine::run) is **resumable**: it loads any prior checkpoint
//!     and continues, reusing completed tool calls instead of repeating them.
//!
//! Portability: this loop uses only injected ports (`LlmPort`, `ToolHost`,
//! `CheckpointStore`, `Clock`). It never spawns a task, never touches
//! `std::time`, and never names a concrete runtime — so it runs identically on
//! the server, on device, and in the browser. Concurrency (running independent
//! plan branches in parallel) is the host runner's job, not the core's.

use std::sync::Arc;

use crate::agent::types::{
    AgentAction, CompletedCall, Role, SessionState, SessionStatus, TranscriptEntry,
};
use crate::ports::{CheckpointStore, Clock, CoreResult, LlmPort, ToolHost};

/// Drives a single agent session to completion (or until the round budget is
/// exhausted), persisting a checkpoint at every step.
#[derive(Clone)]
pub struct ReActEngine {
    llm: Arc<dyn LlmPort>,
    tools: Arc<dyn ToolHost>,
    checkpoints: Arc<dyn CheckpointStore>,
    #[allow(dead_code)]
    clock: Arc<dyn Clock>,
    max_rounds: u64,
}

impl ReActEngine {
    pub fn new(
        llm: Arc<dyn LlmPort>,
        tools: Arc<dyn ToolHost>,
        checkpoints: Arc<dyn CheckpointStore>,
        clock: Arc<dyn Clock>,
    ) -> Self {
        Self {
            llm,
            tools,
            checkpoints,
            clock,
            max_rounds: 16,
        }
    }

    /// Override the default round budget (a circuit-breaker against runaway
    /// loops — a structural bound, not a semantic verdict).
    pub fn with_max_rounds(mut self, max_rounds: u64) -> Self {
        self.max_rounds = max_rounds;
        self
    }

    /// Run (or resume) the session identified by `session_id`.
    ///
    /// If a checkpoint exists it is loaded and the loop continues from the
    /// persisted round; otherwise a fresh session is started for `goal`.
    pub async fn run(
        &self,
        session_id: &str,
        goal: &str,
        project_id: Option<&str>,
    ) -> CoreResult<SessionState> {
        let mut state = match self.checkpoints.load(session_id).await? {
            Some(existing) => existing,
            None => SessionState::new(session_id, goal, project_id),
        };

        while state.status == SessionStatus::Running {
            // Circuit-breaker: structural round budget.
            if state.round >= self.max_rounds {
                state.push_unique(TranscriptEntry::new(
                    state.round,
                    Role::Answer,
                    "round budget exhausted",
                ));
                state.status = SessionStatus::Failed;
                self.checkpoints.save(&state).await?;
                break;
            }

            // THINK — delegate the semantic decision to the planner/LLM.
            let available = self.tools.list_tools();
            let action = self
                .llm
                .decide(&state.goal, state.round, &state.transcript, &available)
                .await?;

            match action {
                AgentAction::Finish { answer } => {
                    state.push_unique(TranscriptEntry::new(
                        state.round,
                        Role::Answer,
                        answer.clone(),
                    ));
                    state.answer = Some(answer);
                    state.status = SessionStatus::Finished;
                }
                AgentAction::CallTool { tool, input_json } => {
                    state.push_unique(TranscriptEntry::new(
                        state.round,
                        Role::Action,
                        format!("{tool} {input_json}"),
                    ));

                    // Crash recovery: if this exact call already completed in
                    // this round, reuse its output — do NOT re-invoke the tool.
                    let output = match state
                        .completed_output(state.round, &tool, &input_json)
                        .map(|s| s.to_string())
                    {
                        Some(prior) => prior,
                        None => {
                            let out = self.tools.call(&tool, &input_json).await?;
                            state.completed_tool_calls.push(CompletedCall {
                                round: state.round,
                                tool: tool.clone(),
                                input_json: input_json.clone(),
                                output_json: out.clone(),
                            });
                            // Incremental persist (ADR-0005): from here on, a
                            // crash + resume must not run this tool again.
                            self.checkpoints.save(&state).await?;
                            out
                        }
                    };

                    state.push_unique(TranscriptEntry::new(
                        state.round,
                        Role::Observation,
                        output,
                    ));
                }
            }

            state.round += 1;
            // Round-boundary checkpoint (ADR-0005).
            self.checkpoints.save(&state).await?;
        }

        Ok(state)
    }
}
