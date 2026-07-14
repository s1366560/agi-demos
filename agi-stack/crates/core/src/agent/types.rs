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
    /// Suspend the loop and ask a human (the **HITL** step, ADR-0004/0005). The
    /// decision *to* ask is the agent's; the engine only suspends at the round
    /// boundary and persists the request.
    RequestHuman { request: HitlRequest },
    /// Terminate the loop with a final answer.
    Finish { answer: String },
}

/// The four kinds of human-in-the-loop interruption, mirroring the Python
/// system's HITL types.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HitlKind {
    /// "I need more information to proceed."
    Clarification,
    /// "Choose between these options."
    Decision,
    /// "Provide a secret/credential." (Production seals the answer as
    /// `response_data_encrypted`; this spike carries it in plaintext — noted
    /// future.)
    EnvVar,
    /// "Approve this side-effecting action."
    Permission,
}

/// The action the agent is asking a human to authorize. These fields are
/// agent-authored structured output; hosts display and validate them but must
/// not infer them from prompt text.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionAction {
    pub name: String,
    pub label: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionTarget {
    pub kind: String,
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub version_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionData {
    /// Human-readable, redacted summary of the payload that will be applied.
    pub summary: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub redacted_fields: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecisionRiskLevel {
    Low,
    Medium,
    High,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionRisk {
    pub level: DecisionRiskLevel,
    pub rationale: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecisionReversibilityMode {
    Reversible,
    Partial,
    Irreversible,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionReversibility {
    pub mode: DecisionReversibilityMode,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recovery: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionScope {
    pub kind: String,
    pub ids: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionEvidence {
    pub kind: String,
    pub id: String,
    pub label: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub digest: Option<String>,
}

/// Complete evidence packet for a subjective human decision. The LLM must
/// supply every semantic field through its structured action. Deterministic
/// hosts may only validate presence and schema conformance.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionContext {
    pub action: DecisionAction,
    pub target: DecisionTarget,
    pub data: DecisionData,
    pub reason: String,
    pub risk: DecisionRisk,
    pub reversibility: DecisionReversibility,
    pub scope: DecisionScope,
    pub evidence: Vec<DecisionEvidence>,
}

impl DecisionContext {
    /// Structural completeness only. This deliberately makes no semantic risk
    /// or appropriateness judgment.
    pub fn is_complete(&self) -> bool {
        non_empty(&self.action.name)
            && non_empty(&self.action.label)
            && non_empty(&self.target.kind)
            && non_empty(&self.target.id)
            && non_empty(&self.data.summary)
            && non_empty(&self.reason)
            && non_empty(&self.risk.rationale)
            && non_empty(&self.scope.kind)
            && !self.scope.ids.is_empty()
            && self.scope.ids.iter().all(|id| non_empty(id))
            && !self.evidence.is_empty()
            && self.evidence.iter().all(|evidence| {
                non_empty(&evidence.kind) && non_empty(&evidence.id) && non_empty(&evidence.label)
            })
    }
}

fn non_empty(value: &str) -> bool {
    !value.trim().is_empty()
}

/// A request for human input raised at a round boundary. `id` keys the eventual
/// [`HitlResponse`] so a resumed loop reuses the answer instead of re-asking
/// (the HITL analog of [`CompletedCall`], ADR-0005).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HitlRequest {
    pub id: String,
    pub kind: HitlKind,
    pub prompt: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub decision: Option<Box<DecisionContext>>,
}

impl HitlRequest {
    pub fn new(id: impl Into<String>, kind: HitlKind, prompt: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            kind,
            prompt: prompt.into(),
            decision: None,
        }
    }

    pub fn with_decision(mut self, decision: DecisionContext) -> Self {
        self.decision = Some(Box::new(decision));
        self
    }
}

#[cfg(test)]
mod hitl_request_tests {
    use super::{
        DecisionAction, DecisionContext, DecisionData, DecisionEvidence, DecisionReversibility,
        DecisionReversibilityMode, DecisionRisk, DecisionRiskLevel, DecisionScope, DecisionTarget,
        HitlKind, HitlRequest,
    };

    #[test]
    fn structured_decision_context_round_trips_without_losing_evidence() {
        let request = HitlRequest::new(
            "approval-1",
            HitlKind::Permission,
            "Allow the workspace write?",
        )
        .with_decision(DecisionContext {
            action: DecisionAction {
                name: "workspace.write".to_string(),
                label: "Apply patch".to_string(),
            },
            target: DecisionTarget {
                kind: "worktree".to_string(),
                id: "worktree-1".to_string(),
                version_id: Some("checkpoint-7".to_string()),
                path: Some("src/lib.rs".to_string()),
            },
            data: DecisionData {
                summary: "Update the selected source file".to_string(),
                redacted_fields: vec!["api_key".to_string()],
            },
            reason: "The approved task requires this source change".to_string(),
            risk: DecisionRisk {
                level: DecisionRiskLevel::Medium,
                rationale: "The edit changes runtime behavior".to_string(),
            },
            reversibility: DecisionReversibility {
                mode: DecisionReversibilityMode::Reversible,
                recovery: Some("Restore checkpoint-7".to_string()),
            },
            scope: DecisionScope {
                kind: "files".to_string(),
                ids: vec!["src/lib.rs".to_string()],
            },
            evidence: vec![DecisionEvidence {
                kind: "diff".to_string(),
                id: "diff-7".to_string(),
                label: "Patch preview".to_string(),
                uri: Some("artifact://diff-7".to_string()),
                digest: Some("sha256:abc".to_string()),
            }],
        });

        let encoded = serde_json::to_string(&request).expect("serialize request");
        let decoded: HitlRequest = serde_json::from_str(&encoded).expect("deserialize request");

        assert_eq!(decoded, request);
        assert!(decoded.decision.expect("decision context").is_complete());
    }

    #[test]
    fn legacy_hitl_request_without_decision_context_remains_compatible() {
        let decoded: HitlRequest = serde_json::from_str(
            r#"{"id":"clarify-1","kind":"clarification","prompt":"Which project?"}"#,
        )
        .expect("deserialize legacy request");

        assert_eq!(decoded.id, "clarify-1");
        assert!(decoded.decision.is_none());
    }
}

/// A human's answer to a [`HitlRequest`], persisted so resume is idempotent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HitlResponse {
    pub id: String,
    pub answer: String,
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
    /// A human's answer to a HITL request, fed back into the loop.
    Human,
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
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionStatus {
    /// Loop is active (or interrupted mid-flight and resumable).
    #[default]
    Running,
    /// Loop is **suspended** awaiting a human answer (HITL). Resumable via
    /// [`crate::ReActEngine::resume`] once the answer arrives.
    AwaitingInput,
    /// Loop stopped at a durable round boundary because the host requested a
    /// pause. The same session can be resumed without repeating completed work.
    Paused,
    /// Loop ended with an answer.
    Finished,
    /// Loop hit a terminal error / round budget.
    Failed,
    /// Loop stopped at a durable round boundary because the user cancelled it.
    /// Hosts may expose recovery as a separate fork/retry operation, but an
    /// ordinary resume must not silently restart this session.
    Cancelled,
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
    /// Set while [`status`](Self::status) is [`AwaitingInput`]: the unanswered
    /// HITL request the loop suspended on.
    ///
    /// [`AwaitingInput`]: SessionStatus::AwaitingInput
    #[serde(default)]
    pub pending_hitl: Option<HitlRequest>,
    /// Answered HITL requests, keyed by id. On resume the engine reuses these
    /// instead of re-asking — the HITL analog of `completed_tool_calls`.
    #[serde(default)]
    pub hitl_responses: Vec<HitlResponse>,
    /// Durable ids of host steering instructions already projected into the
    /// transcript. Hosts acknowledge an instruction only after this checkpoint
    /// is saved, so a crash cannot apply the same instruction twice.
    #[serde(default)]
    pub applied_steering_ids: Vec<String>,
    #[serde(default)]
    pub answer: Option<String>,
    #[serde(default)]
    pub status: SessionStatus,
}

impl SessionState {
    pub fn new(
        session_id: impl Into<String>,
        goal: impl Into<String>,
        project_id: Option<&str>,
    ) -> Self {
        Self {
            session_id: session_id.into(),
            goal: goal.into(),
            project_id: project_id.map(|p| p.to_string()),
            round: 0,
            transcript: Vec::new(),
            completed_tool_calls: Vec::new(),
            pending_hitl: None,
            hitl_responses: Vec::new(),
            applied_steering_ids: Vec::new(),
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

    /// The recorded human answer for a HITL request id, if it has been answered.
    pub fn hitl_answer(&self, id: &str) -> Option<&str> {
        self.hitl_responses
            .iter()
            .find(|r| r.id == id)
            .map(|r| r.answer.as_str())
    }

    /// Record (or replace) a human answer for a HITL request id. Idempotent: a
    /// repeated answer for the same id overwrites rather than duplicates.
    pub fn record_hitl_answer(&mut self, id: impl Into<String>, answer: impl Into<String>) {
        let id = id.into();
        let answer = answer.into();
        if let Some(existing) = self.hitl_responses.iter_mut().find(|r| r.id == id) {
            existing.answer = answer;
        } else {
            self.hitl_responses.push(HitlResponse { id, answer });
        }
    }
}
