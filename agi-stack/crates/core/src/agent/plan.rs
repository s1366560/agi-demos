//! Append-only Plan DAG (ADR-0004) with a **declarative, level-triggered**
//! reconcile, mirroring the orchestration primitive distilled from Argo Workflows
//! and the K8s controller model (`06-agent-core-design.md`, `08-control-data-
//! plane-separation.md`).
//!
//! Two properties matter:
//!   - **Append-only**: steps and their edges are never mutated destructively;
//!     you append nodes and flip statuses. This gives a tamper-evident execution
//!     history and makes replay/resume trivial.
//!   - **Level-triggered `ready()`**: instead of firing imperative "run step X"
//!     events, the planner repeatedly asks "given current statuses, which steps
//!     are runnable?". Re-asking is idempotent and self-heals after a crash —
//!     exactly how a K8s controller converges to desired state.

use serde::{Deserialize, Serialize};

use crate::ports::{CoreError, CoreResult};

/// Execution status of a single plan step.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum StepStatus {
    Pending,
    Running,
    Done,
    Failed,
}

/// A node in the plan DAG. `deps` are the ids of steps that must be [`Done`]
/// before this one becomes runnable.
///
/// [`Done`]: StepStatus::Done
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlanStep {
    pub id: String,
    pub description: String,
    #[serde(default)]
    pub deps: Vec<String>,
    pub status: StepStatus,
}

impl PlanStep {
    pub fn new(id: impl Into<String>, description: impl Into<String>, deps: Vec<String>) -> Self {
        Self {
            id: id.into(),
            description: description.into(),
            deps,
            status: StepStatus::Pending,
        }
    }
}

/// An append-only DAG of [`PlanStep`]s.
#[derive(Debug, Default, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Plan {
    steps: Vec<PlanStep>,
}

impl Plan {
    pub fn new() -> Self {
        Self::default()
    }

    /// Append a step. Rejects a duplicate id and any dependency that does not
    /// already exist, so the DAG stays acyclic and well-formed by construction
    /// (a step can only depend on earlier-appended steps).
    pub fn append(&mut self, step: PlanStep) -> CoreResult<()> {
        if self.steps.iter().any(|s| s.id == step.id) {
            return Err(CoreError::Plan(format!("duplicate step id: {}", step.id)));
        }
        for dep in &step.deps {
            if !self.steps.iter().any(|s| &s.id == dep) {
                return Err(CoreError::Plan(format!(
                    "step {} depends on unknown step {dep}",
                    step.id
                )));
            }
        }
        self.steps.push(step);
        Ok(())
    }

    pub fn get(&self, id: &str) -> Option<&PlanStep> {
        self.steps.iter().find(|s| s.id == id)
    }

    pub fn steps(&self) -> &[PlanStep] {
        &self.steps
    }

    /// Flip a step's status (the only mutation allowed besides append).
    pub fn mark(&mut self, id: &str, status: StepStatus) -> CoreResult<()> {
        let step = self
            .steps
            .iter_mut()
            .find(|s| s.id == id)
            .ok_or_else(|| CoreError::Plan(format!("unknown step: {id}")))?;
        step.status = status;
        Ok(())
    }

    /// **Level-triggered reconcile**: the ids of every `Pending` step whose deps
    /// are all `Done`. Pure function of current state → calling it repeatedly is
    /// idempotent and order-independent.
    pub fn ready(&self) -> Vec<String> {
        let done: std::collections::BTreeSet<&str> = self
            .steps
            .iter()
            .filter(|s| s.status == StepStatus::Done)
            .map(|s| s.id.as_str())
            .collect();
        let mut ids: Vec<String> = self
            .steps
            .iter()
            .filter(|s| s.status == StepStatus::Pending)
            .filter(|s| s.deps.iter().all(|d| done.contains(d.as_str())))
            .map(|s| s.id.clone())
            .collect();
        ids.sort();
        ids
    }

    /// Every step is `Done`.
    pub fn is_complete(&self) -> bool {
        !self.steps.is_empty() && self.steps.iter().all(|s| s.status == StepStatus::Done)
    }

    /// Any step has `Failed`.
    pub fn has_failure(&self) -> bool {
        self.steps.iter().any(|s| s.status == StepStatus::Failed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn step(id: &str, deps: &[&str]) -> PlanStep {
        PlanStep::new(id, format!("do {id}"), deps.iter().map(|d| d.to_string()).collect())
    }

    #[test]
    fn append_is_validated_and_dedup() {
        let mut plan = Plan::new();
        plan.append(step("a", &[])).unwrap();
        // duplicate id rejected
        assert!(plan.append(step("a", &[])).is_err());
        // unknown dependency rejected
        assert!(plan.append(step("b", &["zzz"])).is_err());
        plan.append(step("b", &["a"])).unwrap();
        assert_eq!(plan.steps().len(), 2);
    }

    #[test]
    fn ready_is_level_triggered_and_idempotent() {
        let mut plan = Plan::new();
        plan.append(step("a", &[])).unwrap();
        plan.append(step("b", &["a"])).unwrap();
        plan.append(step("c", &["a"])).unwrap();
        plan.append(step("d", &["b", "c"])).unwrap();

        // only the root is ready; asking twice gives the same answer (idempotent)
        assert_eq!(plan.ready(), vec!["a"]);
        assert_eq!(plan.ready(), vec!["a"]);

        plan.mark("a", StepStatus::Done).unwrap();
        // a's two children unlock together
        assert_eq!(plan.ready(), vec!["b", "c"]);

        plan.mark("b", StepStatus::Done).unwrap();
        // d still blocked on c
        assert_eq!(plan.ready(), vec!["c"]);

        plan.mark("c", StepStatus::Done).unwrap();
        assert_eq!(plan.ready(), vec!["d"]);

        plan.mark("d", StepStatus::Done).unwrap();
        assert!(plan.ready().is_empty());
        assert!(plan.is_complete());
    }
}
