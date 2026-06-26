//! Agent domain types: the ReAct transcript, actions, and the persisted session
//! state that makes a long-running agent loop **crash-recoverable**.
//!
//! These types are pure data (serde) so a [`SessionState`] can be snapshotted to
//! any [`crate::ports::CheckpointStore`] — in-memory, SQLite on device, or
//! Postgres on the server — without the core knowing which.

use serde::{Deserialize, Serialize};

/// One decision a planner/LLM makes at a ReAct round — the **Think** output.
///
/// Agent First: *which* action to take is a semantic judgment delegated to the
/// [`crate::ports::LlmPort`]; the engine only executes the structured result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AgentAction {
    /// Invoke a registered tool with a JSON input (the **Act** step).
    CallTool { tool: String, input_json: String },
    /// Terminate the loop with a final answer.
    Finish { answer: String },
}

/// The role of a transcript line, mirroring the ReAct trichotomy plus the final
/// answer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    /// Model reasoning ("Think").
    Thought,
    /// A tool invocation request ("Act").
    Action,
    /// A tool result fed back to the model ("Observe").
    Observation,
    /// The final answer that ended the loop.
    Answer,
}

/// One line of the ReAct transcript, tagged with the round it belongs to so the
/// loop can be replayed deterministically after a crash.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TranscriptEntry {
    pub round: u64,
    pub role: Role,
    pub content: String,
}

impl TranscriptEntry {
    pub fn new(round: u64, role: Role, content: impl Into<String>) -> Self {
        Self {
            round,
            role,
            content: content.into(),
        }
    }
}

/// A tool call that already executed and whose output was persisted. On resume,
/// the engine reuses this output instead of re-invoking the tool — the heart of
/// "recover without repeating completed work" (ADR-0005).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompletedCall {
    pub round: u64,
    pub tool: String,
    pub input_json: String,
    pub output_json: String,
}

/// Lifecycle of an agent session.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SessionStatus {
    /// Loop is active (or interrupted mid-flight and resumable).
    Running,
    /// Loop ended with an answer.
    Finished,
    /// Loop hit a terminal error / round budget.
    Failed,
}

impl Default for SessionStatus {
    fn default() -> Self {
        SessionStatus::Running
    }
}

/// The full, serializable state of a ReAct session — the checkpoint unit.
///
/// `round` is a monotonic counter (ADR-0005): every checkpoint advances it, and
/// recovery resumes from the persisted value, so already-completed rounds are
/// never re-executed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionState {
    pub session_id: String,
    pub goal: String,
    #[serde(default)]
    pub project_id: Option<String>,
    pub round: u64,
    #[serde(default)]
    pub transcript: Vec<TranscriptEntry>,
    #[serde(default)]
    pub completed_tool_calls: Vec<CompletedCall>,
    #[serde(default)]
    pub answer: Option<String>,
    #[serde(default)]
    pub status: SessionStatus,
}

impl SessionState {
    pub fn new(session_id: impl Into<String>, goal: impl Into<String>, project_id: Option<&str>) -> Self {
        Self {
            session_id: session_id.into(),
            goal: goal.into(),
            project_id: project_id.map(|p| p.to_string()),
            round: 0,
            transcript: Vec::new(),
            completed_tool_calls: Vec::new(),
            answer: None,
            status: SessionStatus::Running,
        }
    }

    /// Append a transcript entry only if an identical one is not already present.
    ///
    /// This makes round re-entry after a mid-round crash idempotent: the
    /// previously-persisted `Action` line is not duplicated when the round is
    /// replayed (the `Observation` differs and is added once).
    pub fn push_unique(&mut self, entry: TranscriptEntry) {
        if !self.transcript.contains(&entry) {
            self.transcript.push(entry);
        }
    }

    /// The already-recorded output for a tool call at `round`, if any.
    pub fn completed_output(&self, round: u64, tool: &str, input_json: &str) -> Option<&str> {
        self.completed_tool_calls
            .iter()
            .find(|c| c.round == round && c.tool == tool && c.input_json == input_json)
            .map(|c| c.output_json.as_str())
    }
}
