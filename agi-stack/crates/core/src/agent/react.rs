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
    AgentAction, CompletedCall, HitlRequest, Role, SessionState, SessionStatus, TranscriptEntry,
};
use crate::ports::{CheckpointStore, Clock, CoreError, CoreResult, LlmPort, ToolHost};

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
                AgentAction::RequestHuman { request } => {
                    // The "ask" is recorded once (dedup-safe on replay).
                    state.push_unique(TranscriptEntry::new(
                        state.round,
                        Role::Action,
                        format!("request_human[{:?}] {}", request.kind, request.prompt),
                    ));

                    match state.hitl_answer(&request.id).map(|a| a.to_string()) {
                        // Already answered (we are replaying after a resume): feed
                        // the human answer as this round's observation and advance.
                        // The HITL analog of reusing a completed tool call.
                        Some(answer) => {
                            state.push_unique(TranscriptEntry::new(
                                state.round,
                                Role::Human,
                                answer,
                            ));
                        }
                        // Unanswered: SUSPEND at the round boundary (ADR-0005).
                        // Persist the pending request and exit the loop without
                        // advancing the round, so resume replays this exact round.
                        None => {
                            state.pending_hitl = Some(request);
                            state.status = SessionStatus::AwaitingInput;
                            self.checkpoints.save(&state).await?;
                            break;
                        }
                    }
                }
            }

            state.round += 1;
            // Round-boundary checkpoint (ADR-0005).
            self.checkpoints.save(&state).await?;
        }

        Ok(state)
    }

    /// Resume a session that is [`AwaitingInput`] by supplying the human answer
    /// to its pending HITL request, then drive the loop to completion.
    ///
    /// The answer is persisted before the loop restarts, so this is **idempotent
    /// and crash-safe**: a fresh engine (new process) replays the suspended round,
    /// sees the recorded answer instead of re-asking, and continues — reusing any
    /// already-completed tool calls exactly as ordinary recovery does (ADR-0005).
    ///
    /// Errors if the session is not awaiting input or if `request_id` does not
    /// match the pending request (a structural guard, not a semantic judgment).
    ///
    /// [`AwaitingInput`]: SessionStatus::AwaitingInput
    pub async fn resume(
        &self,
        session_id: &str,
        request_id: &str,
        answer: &str,
    ) -> CoreResult<SessionState> {
        let mut state = self
            .checkpoints
            .load(session_id)
            .await?
            .ok_or(CoreError::NotFound)?;

        // Idempotent: nothing to resume if the session already moved on.
        if state.status != SessionStatus::AwaitingInput {
            return Ok(state);
        }

        match &state.pending_hitl {
            Some(req) if req.id == request_id => {}
            Some(req) => {
                return Err(CoreError::Tool(format!(
                    "resume id mismatch: pending '{}', got '{request_id}'",
                    req.id
                )))
            }
            None => {
                return Err(CoreError::Tool(
                    "session is awaiting input but has no pending request".into(),
                ))
            }
        }

        // Record the answer, clear the suspension, flip back to Running, persist —
        // then let the (round-indexed) loop replay the suspended round and proceed.
        state.record_hitl_answer(request_id, answer);
        state.pending_hitl = None;
        state.status = SessionStatus::Running;
        self.checkpoints.save(&state).await?;

        let goal = state.goal.clone();
        let project_id = state.project_id.clone();
        self.run(session_id, &goal, project_id.as_deref()).await
    }
}

/// The pending HITL request for a suspended session, if any — a convenience for
/// callers (e.g. an HTTP handler) that need to surface what the loop is waiting
/// on without inspecting the whole [`SessionState`].
pub fn pending_request(state: &SessionState) -> Option<&HitlRequest> {
    state.pending_hitl.as_ref()
}
