//! Robustness primitives for the ReAct loop: a **structural doom-loop detector**,
//! an **arithmetic cost tracker**, and an injected **supervisor port** that turns
//! a fired trigger into an agent-authored verdict.
//!
//! This is the literal encoding of the repository's defining architectural rule
//! (AGENTS.md "Agent First"): a *deterministic threshold may fire the trigger, but
//! the verdict must come from an agent tool-call*. So the split here is deliberate:
//!
//!   - [`DoomLoopDetector`] and [`CostTracker`] are **pure and deterministic** —
//!     a sliding-window repeat count and integer budget counters. They only ever
//!     answer the *structural* question "did something cross a threshold?".
//!   - [`SupervisorPort`] is the **semantic** half: once a trigger fires, the
//!     engine does not decide the outcome itself. It calls the supervisor (an
//!     agent, exactly like [`LlmPort`]) which returns a structured
//!     [`SupervisorVerdict`] — `{ health, next, rationale }` — and the engine then
//!     acts on that verdict deterministically.
//!
//! Portability: no tokio, no `std::time`. The detector/tracker are plain data
//! structures and the supervisor is an injected async port, so this compiles to
//! `wasm32` alongside the rest of the core (Flink's failure-rate backoff, `06 §4`,
//! realized without any runtime dependency).
//!
//! [`LlmPort`]: crate::ports::LlmPort

use std::collections::VecDeque;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use crate::agent::types::TranscriptEntry;
use crate::ports::CoreResult;

/// A sliding-window detector for repeated identical actions — a **structural**
/// circuit-breaker, never a semantic judgment. It answers exactly one question:
/// has the same action key recurred at least `threshold` times within the last
/// `window` observations?
///
/// It deliberately does *not* decide what to do about that — firing only arms the
/// engine to consult the [`SupervisorPort`] (Agent First).
#[derive(Debug, Clone)]
pub struct DoomLoopDetector {
    window: usize,
    threshold: usize,
    recent: VecDeque<String>,
}

impl DoomLoopDetector {
    /// `window` = how many recent actions to remember; `threshold` = how many
    /// repeats of one key within that window trips the trigger. Both are clamped
    /// to sane minimums (`threshold >= 1`, `window >= threshold`) so a
    /// misconfiguration cannot silently disable detection or panic.
    pub fn new(window: usize, threshold: usize) -> Self {
        let threshold = threshold.max(1);
        let window = window.max(threshold);
        Self {
            window,
            threshold,
            recent: VecDeque::with_capacity(window),
        }
    }

    /// Record an action key (e.g. `"tool {input_json}"`) and report whether it has
    /// now recurred `threshold`+ times inside the window. Deterministic.
    pub fn observe(&mut self, key: &str) -> bool {
        self.recent.push_back(key.to_string());
        while self.recent.len() > self.window {
            self.recent.pop_front();
        }
        let count = self.recent.iter().filter(|k| k.as_str() == key).count();
        count >= self.threshold
    }
}

/// A per-session spend ceiling. Each bound is optional; `None` means "unbounded on
/// that axis". Counting is pure arithmetic — AGENTS.md explicitly lists budget
/// counters (rounds, tool-calls, tokens) as *deterministic*, not agent judgments.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CostBudget {
    pub max_rounds: Option<u64>,
    pub max_tool_calls: Option<u64>,
    pub max_tokens: Option<u64>,
}

impl CostBudget {
    /// A budget bounded only by round count.
    pub fn rounds(max_rounds: u64) -> Self {
        Self {
            max_rounds: Some(max_rounds),
            ..Self::default()
        }
    }

    /// A budget bounded only by tool-call count.
    pub fn tool_calls(max_tool_calls: u64) -> Self {
        Self {
            max_tool_calls: Some(max_tool_calls),
            ..Self::default()
        }
    }

    /// A budget bounded only by token count.
    pub fn tokens(max_tokens: u64) -> Self {
        Self {
            max_tokens: Some(max_tokens),
            ..Self::default()
        }
    }
}

/// Accumulates spend against a [`CostBudget`]. All counters are monotonic; the
/// only question it answers ([`over_budget`](Self::over_budget)) is a set of
/// integer comparisons — deterministic, so it may *fire* the cost-ceiling trigger,
/// but the resulting verdict is still the supervisor's (Agent First).
#[derive(Debug, Clone)]
pub struct CostTracker {
    budget: CostBudget,
    rounds: u64,
    tool_calls: u64,
    tokens: u64,
}

impl CostTracker {
    pub fn new(budget: CostBudget) -> Self {
        Self {
            budget,
            rounds: 0,
            tool_calls: 0,
            tokens: 0,
        }
    }

    /// Seed the round counter when resuming a checkpointed session so the budget
    /// spans the whole session, not just the current process.
    pub fn seed_rounds(&mut self, rounds: u64) {
        self.rounds = rounds;
    }

    pub fn record_round(&mut self) {
        self.rounds = self.rounds.saturating_add(1);
    }

    pub fn record_tool_call(&mut self) {
        self.tool_calls = self.tool_calls.saturating_add(1);
    }

    pub fn add_tokens(&mut self, tokens: u64) {
        self.tokens = self.tokens.saturating_add(tokens);
    }

    pub fn rounds(&self) -> u64 {
        self.rounds
    }

    /// Whether any bounded axis has reached its ceiling (`counter >= max`). Pure
    /// arithmetic over the set bounds.
    pub fn over_budget(&self) -> bool {
        self.budget.max_rounds.is_some_and(|m| self.rounds >= m)
            || self
                .budget
                .max_tool_calls
                .is_some_and(|m| self.tool_calls >= m)
            || self.budget.max_tokens.is_some_and(|m| self.tokens >= m)
    }
}

/// Why the engine paused to ask the supervisor — a *structural* fact.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TriggerReason {
    /// The [`DoomLoopDetector`] saw a repeated action cross its threshold.
    DoomLoop,
    /// The [`CostTracker`] hit a budget ceiling.
    CostCeiling,
}

/// The supervisor's read on session health (the *semantic* diagnosis).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Health {
    Healthy,
    Stalled,
    Looping,
    GoalDrift,
}

/// What the engine should do next, per the supervisor.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NextAction {
    /// Override the structural trigger and keep going.
    Continue,
    /// Hand off to a different agent/strategy (terminal for this loop).
    Reassign,
    /// Give up and surface to a human/caller (terminal for this loop).
    Escalate,
}

/// The structured verdict an agent returns when consulted about a fired trigger.
/// This is the payload of the Agent-First tool-call: the engine acts on `next`
/// deterministically and records `rationale` for audit.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SupervisorVerdict {
    pub health: Health,
    pub next: NextAction,
    pub rationale: String,
}

impl SupervisorVerdict {
    pub fn new(health: Health, next: NextAction, rationale: impl Into<String>) -> Self {
        Self {
            health,
            next,
            rationale: rationale.into(),
        }
    }
}

/// The injected **agent** that judges a fired trigger. It is a port exactly like
/// [`LlmPort`] — a semantic decision made outside the deterministic core — so the
/// engine never hardcodes "looping ⇒ stop". Implementations may wrap an LLM, a
/// heuristic, or (in tests) a canned verdict; a real one would log the tool-call
/// (agent_id / input / output / rationale) for audit as AGENTS.md requires.
///
/// [`LlmPort`]: crate::ports::LlmPort
#[async_trait]
pub trait SupervisorPort: Send + Sync {
    /// Review a fired trigger at `round` given the transcript so far and return a
    /// structured verdict. The engine supplies the *structural* `reason`; the port
    /// supplies the *semantic* `{ health, next, rationale }`.
    async fn review(
        &self,
        reason: TriggerReason,
        round: u64,
        transcript: &[TranscriptEntry],
    ) -> CoreResult<SupervisorVerdict>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detector_fires_only_after_threshold_repeats() {
        let mut d = DoomLoopDetector::new(5, 3);
        assert!(!d.observe("a")); // 1
        assert!(!d.observe("a")); // 2
        assert!(d.observe("a")); // 3 -> fires
    }

    #[test]
    fn distinct_actions_never_fire() {
        let mut d = DoomLoopDetector::new(5, 3);
        assert!(!d.observe("a"));
        assert!(!d.observe("b"));
        assert!(!d.observe("c"));
        assert!(!d.observe("d"));
    }

    #[test]
    fn window_eviction_forgets_old_repeats() {
        // window == threshold == 2: an intervening distinct key evicts the first
        // occurrence, so two "a"s separated by a "b" never coexist in the window.
        let mut d = DoomLoopDetector::new(2, 2);
        assert!(!d.observe("a")); // [a]
        assert!(!d.observe("b")); // [a,b]
        assert!(!d.observe("a")); // [b,a] -> only one "a" in window
        assert!(d.observe("a")); // [a,a] -> fires
    }

    #[test]
    fn new_clamps_degenerate_config() {
        // threshold 0 -> 1, window 0 -> threshold: one observation fires.
        let mut d = DoomLoopDetector::new(0, 0);
        assert!(d.observe("x"));
    }

    #[test]
    fn cost_tracker_is_pure_arithmetic() {
        let mut c = CostTracker::new(CostBudget::rounds(3));
        assert!(!c.over_budget());
        c.record_round();
        c.record_round();
        assert!(!c.over_budget()); // 2 < 3
        c.record_round();
        assert!(c.over_budget()); // 3 >= 3
    }

    #[test]
    fn cost_tracker_seed_and_multiaxis() {
        let mut c = CostTracker::new(CostBudget {
            max_rounds: Some(10),
            max_tool_calls: Some(2),
            max_tokens: None,
        });
        c.seed_rounds(5);
        assert_eq!(c.rounds(), 5);
        assert!(!c.over_budget());
        c.record_tool_call();
        c.record_tool_call();
        assert!(c.over_budget()); // tool_calls 2 >= 2
    }

    #[test]
    fn verdict_serializes_snake_case() {
        let v = SupervisorVerdict::new(Health::GoalDrift, NextAction::Escalate, "drifted");
        let json = serde_json::to_string(&v).unwrap();
        assert!(json.contains("\"health\":\"goal_drift\""), "{json}");
        assert!(json.contains("\"next\":\"escalate\""), "{json}");
        let back: SupervisorVerdict = serde_json::from_str(&json).unwrap();
        assert_eq!(back, v);
    }

    #[test]
    fn trigger_reason_serializes_snake_case() {
        assert_eq!(
            serde_json::to_string(&TriggerReason::CostCeiling).unwrap(),
            "\"cost_ceiling\""
        );
        assert_eq!(
            serde_json::to_string(&TriggerReason::DoomLoop).unwrap(),
            "\"doom_loop\""
        );
    }
}
