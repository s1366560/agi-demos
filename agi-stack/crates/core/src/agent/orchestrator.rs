//! `MiniOrchestrator`: a single-threaded, runtime-agnostic driver that reconciles
//! a [`Plan`] DAG to convergence (Wave L, closes the "orchestratable" quality
//! axis of `06-agent-core-design.md`).
//!
//! It is the agent-layer realization of the same primitive distilled from Argo's
//! `operate()` reconcile and the K8s controller model (`08-control-data-plane-
//! separation.md`): **the plan's status is the single source of truth, and every
//! step is driven by re-asking [`Plan::ready`] — never by firing imperative
//! "run step X" events.** Because `ready()` is a pure, level-triggered function of
//! current status, re-running it is idempotent and self-heals after a crash.
//!
//! Robustness (ADR-0005): the plan is persisted through an injected [`PlanStore`]
//! **after every step**, so a crash mid-reconcile resumes from the last-good plan
//! and re-runs only the steps that are still `Pending`. Already-`Done` steps are
//! never re-dispatched — the Plan-DAG analog of the ReAct engine reusing a
//! completed tool call.
//!
//! Portability: like the rest of the core this carries **no tokio, no
//! `std::time`, no task spawning**. Ready steps are dispatched **sequentially**
//! (the lightweight, on-device edition). Parallel fan-out — dispatching every
//! id `ready()` returns at once under an actor supervisor (Kameo) — is a
//! native-only runner layered *on top* of this same reconcile logic, noted
//! future. The reconcile logic itself is identical on server, device and browser.

use std::sync::Arc;

use async_trait::async_trait;

use crate::agent::plan::{Plan, PlanStep, StepStatus};
use crate::ports::{CoreError, CoreResult};

/// The result of executing one plan step. Structural, not a judgment: the
/// [`StepRunner`] reports success/handled-failure; the orchestrator only flips
/// the status. A transport/crash error is surfaced as `Err` from
/// [`StepRunner::run_step`] instead (so the plan is left untouched and resume
/// re-runs the step).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StepOutcome {
    /// The step finished successfully → mark [`StepStatus::Done`].
    Done,
    /// The step ran but reported a handled failure → mark [`StepStatus::Failed`]
    /// (carrying a reason for the transcript/audit).
    Failed(String),
}

/// Injected port that actually executes a single plan step. Keeping this a port
/// is what lets the orchestrator stay runtime-agnostic: the real runner (which
/// might dispatch a ReAct sub-session, call a tool, or hand off to a harness)
/// lives outside the core, while the reconcile loop here is pure.
#[async_trait]
pub trait StepRunner: Send + Sync {
    /// Execute one ready step. `Ok(StepOutcome)` records a terminal status for
    /// the step; `Err` means the attempt could not complete (e.g. a crash or
    /// transport fault) and the step is left `Pending` so resume re-runs it.
    async fn run_step(&self, plan_id: &str, step: &PlanStep) -> CoreResult<StepOutcome>;
}

/// Persistence for the [`Plan`] under reconcile — the checkpoint store behind
/// crash recovery (ADR-0005), the Plan-DAG analog of
/// [`crate::ports::CheckpointStore`] for sessions. In-memory for tests/browser,
/// SQLite on device, Postgres on the server: all behind this one port.
#[async_trait]
pub trait PlanStore: Send + Sync {
    /// Persist the plan's current state (insert-or-replace by `plan_id`).
    async fn save(&self, plan_id: &str, plan: &Plan) -> CoreResult<()>;
    /// Load a plan's last checkpoint, if any.
    async fn load(&self, plan_id: &str) -> CoreResult<Option<Plan>>;
}

/// Drives a [`Plan`] DAG to convergence via level-triggered reconcile, persisting
/// a checkpoint after every step so the run is crash-recoverable and resumable.
#[derive(Clone)]
pub struct MiniOrchestrator {
    runner: Arc<dyn StepRunner>,
    store: Arc<dyn PlanStore>,
}

impl MiniOrchestrator {
    pub fn new(runner: Arc<dyn StepRunner>, store: Arc<dyn PlanStore>) -> Self {
        Self { runner, store }
    }

    /// Reconcile the plan identified by `plan_id` to a terminal state
    /// (all steps `Done`, or any step `Failed`).
    ///
    /// If a checkpoint already exists it is **resumed** (the passed `initial`
    /// plan is ignored); otherwise `initial` seeds a fresh run and is persisted.
    /// This makes `run` idempotent: calling it again on a converged plan is a
    /// no-op that re-returns the terminal plan without dispatching anything.
    pub async fn run(&self, plan_id: &str, initial: &Plan) -> CoreResult<Plan> {
        // Resume from the last checkpoint if present; else seed + persist.
        let mut plan = match self.store.load(plan_id).await? {
            Some(existing) => existing,
            None => {
                self.store.save(plan_id, initial).await?;
                initial.clone()
            }
        };

        // Level-triggered reconcile: re-ask `ready()` until convergence.
        while !plan.is_complete() && !plan.has_failure() {
            let ready = plan.ready();
            if ready.is_empty() {
                // Not complete, not failed, yet nothing is runnable: the plan is
                // structurally stuck (e.g. resumed into an inconsistent state).
                // Stop deterministically rather than spin forever.
                break;
            }

            for id in ready {
                // `ready()` only ever returns `Pending` steps, so a `Done` step
                // is never re-dispatched — this is what makes crash-recovery
                // reuse completed work instead of repeating it (ADR-0005).
                let step = plan
                    .get(&id)
                    .ok_or_else(|| CoreError::Plan(format!("ready step vanished: {id}")))?
                    .clone();

                match self.runner.run_step(plan_id, &step).await? {
                    StepOutcome::Done => plan.mark(&id, StepStatus::Done)?,
                    StepOutcome::Failed(_) => plan.mark(&id, StepStatus::Failed)?,
                }

                // Incremental persist after each step: a crash after this line
                // reloads the step as terminal and never re-runs it (ADR-0005).
                self.store.save(plan_id, &plan).await?;

                if plan.has_failure() {
                    // Short-circuit: once a step fails, stop dispatching the rest
                    // of this ready batch and preserve the last-good plan.
                    break;
                }
            }

            // Reconcile-boundary checkpoint (idempotent; state already persisted).
            self.store.save(plan_id, &plan).await?;
        }

        Ok(plan)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Mutex;

    use futures::executor::block_on;

    /// In-memory [`PlanStore`] for tests (the on-device SQLite / server Postgres
    /// stores implement the same port). A `std::sync::Mutex` is fine here: the
    /// core reconcile loop is single-threaded and never held across an await in
    /// a way that could deadlock under `block_on`.
    #[derive(Default)]
    struct MemPlanStore(Mutex<HashMap<String, Plan>>);

    #[async_trait]
    impl PlanStore for MemPlanStore {
        async fn save(&self, plan_id: &str, plan: &Plan) -> CoreResult<()> {
            self.0
                .lock()
                .unwrap()
                .insert(plan_id.to_string(), plan.clone());
            Ok(())
        }
        async fn load(&self, plan_id: &str) -> CoreResult<Option<Plan>> {
            Ok(self.0.lock().unwrap().get(plan_id).cloned())
        }
    }

    /// A runner that logs the id of every step it executes (shared across
    /// orchestrator instances via `Arc`), optionally *crashing* (returning `Err`
    /// before recording) on a chosen id, or reporting a handled *failure* on one.
    struct RecordingRunner {
        log: Arc<Mutex<Vec<String>>>,
        crash_on: Option<String>,
        fail_on: Option<String>,
    }

    impl RecordingRunner {
        fn new(log: Arc<Mutex<Vec<String>>>) -> Self {
            Self {
                log,
                crash_on: None,
                fail_on: None,
            }
        }
        fn crashing(log: Arc<Mutex<Vec<String>>>, crash_on: &str) -> Self {
            Self {
                log,
                crash_on: Some(crash_on.into()),
                fail_on: None,
            }
        }
        fn failing(log: Arc<Mutex<Vec<String>>>, fail_on: &str) -> Self {
            Self {
                log,
                crash_on: None,
                fail_on: Some(fail_on.into()),
            }
        }
    }

    #[async_trait]
    impl StepRunner for RecordingRunner {
        async fn run_step(&self, _plan_id: &str, step: &PlanStep) -> CoreResult<StepOutcome> {
            // Simulate a crash *before* doing (or logging) any work.
            if self.crash_on.as_deref() == Some(step.id.as_str()) {
                return Err(CoreError::Plan(format!("simulated crash at {}", step.id)));
            }
            self.log.lock().unwrap().push(step.id.clone());
            if self.fail_on.as_deref() == Some(step.id.as_str()) {
                return Ok(StepOutcome::Failed(format!("boom at {}", step.id)));
            }
            Ok(StepOutcome::Done)
        }
    }

    fn step(id: &str, deps: &[&str]) -> PlanStep {
        PlanStep::new(
            id,
            format!("do {id}"),
            deps.iter().map(|d| d.to_string()).collect(),
        )
    }

    /// a → {b, c} → d : a diamond DAG converges to all-Done, and each step runs
    /// exactly once, in a level-triggered order.
    #[test]
    fn diamond_dag_converges_to_completion() {
        let mut plan = Plan::new();
        plan.append(step("a", &[])).unwrap();
        plan.append(step("b", &["a"])).unwrap();
        plan.append(step("c", &["a"])).unwrap();
        plan.append(step("d", &["b", "c"])).unwrap();

        let log = Arc::new(Mutex::new(Vec::new()));
        let orch = MiniOrchestrator::new(
            Arc::new(RecordingRunner::new(log.clone())),
            Arc::new(MemPlanStore::default()),
        );

        let done = block_on(orch.run("p-diamond", &plan)).unwrap();
        assert!(done.is_complete());
        // Root first, then its two children (sorted), then the join.
        assert_eq!(*log.lock().unwrap(), vec!["a", "b", "c", "d"]);
    }

    /// A crash mid-reconcile: on resume, the previously-`Done` steps are reused
    /// (not re-dispatched) and only the interrupted step re-runs.
    #[test]
    fn crash_mid_reconcile_resumes_without_repeating_done_steps() {
        let mut plan = Plan::new();
        plan.append(step("a", &[])).unwrap();
        plan.append(step("b", &["a"])).unwrap();
        plan.append(step("c", &["b"])).unwrap();

        let store = Arc::new(MemPlanStore::default());
        let log = Arc::new(Mutex::new(Vec::new()));

        // First run crashes when it reaches "b" (after "a" is Done + persisted).
        let orch1 = MiniOrchestrator::new(
            Arc::new(RecordingRunner::crashing(log.clone(), "b")),
            store.clone(),
        );
        assert!(block_on(orch1.run("p-crash", &plan)).is_err());
        assert_eq!(*log.lock().unwrap(), vec!["a"]); // only "a" ran + persisted

        // Resume with a healthy runner + the SAME store. "a" is already Done, so
        // it is not re-dispatched; "b" (left Pending) and "c" run to completion.
        let orch2 =
            MiniOrchestrator::new(Arc::new(RecordingRunner::new(log.clone())), store.clone());
        let done = block_on(orch2.run("p-crash", &plan)).unwrap();
        assert!(done.is_complete());
        // "a" appears exactly once across both runs (reused, never repeated).
        assert_eq!(*log.lock().unwrap(), vec!["a", "b", "c"]);
    }

    /// A failed step short-circuits: downstream steps never run and the last-good
    /// plan (with the completed prefix) is preserved.
    #[test]
    fn failed_step_short_circuits_and_preserves_last_good() {
        let mut plan = Plan::new();
        plan.append(step("a", &[])).unwrap();
        plan.append(step("b", &["a"])).unwrap();
        plan.append(step("c", &["b"])).unwrap();

        let store = Arc::new(MemPlanStore::default());
        let log = Arc::new(Mutex::new(Vec::new()));
        let orch = MiniOrchestrator::new(
            Arc::new(RecordingRunner::failing(log.clone(), "b")),
            store.clone(),
        );

        let out = block_on(orch.run("p-fail", &plan)).unwrap();
        assert!(out.has_failure());
        assert!(!out.is_complete());
        assert_eq!(out.get("a").unwrap().status, StepStatus::Done);
        assert_eq!(out.get("b").unwrap().status, StepStatus::Failed);
        assert_eq!(out.get("c").unwrap().status, StepStatus::Pending); // never ran
        assert_eq!(*log.lock().unwrap(), vec!["a", "b"]); // "c" never dispatched

        // Last-good is persisted: reloading shows the same terminal state.
        let reloaded = block_on(store.load("p-fail")).unwrap().unwrap();
        assert_eq!(reloaded, out);
    }

    /// Re-running a converged plan is an idempotent no-op: nothing is dispatched.
    #[test]
    fn rerun_of_converged_plan_is_idempotent_noop() {
        let mut plan = Plan::new();
        plan.append(step("a", &[])).unwrap();
        plan.append(step("b", &["a"])).unwrap();

        let store = Arc::new(MemPlanStore::default());
        let log = Arc::new(Mutex::new(Vec::new()));

        let orch1 =
            MiniOrchestrator::new(Arc::new(RecordingRunner::new(log.clone())), store.clone());
        block_on(orch1.run("p-idem", &plan)).unwrap();
        assert_eq!(*log.lock().unwrap(), vec!["a", "b"]);

        // Second orchestrator, fresh log, same store: the plan is already
        // complete, so reconcile dispatches nothing.
        let log2 = Arc::new(Mutex::new(Vec::new()));
        let orch2 =
            MiniOrchestrator::new(Arc::new(RecordingRunner::new(log2.clone())), store.clone());
        let done = block_on(orch2.run("p-idem", &plan)).unwrap();
        assert!(done.is_complete());
        assert!(log2.lock().unwrap().is_empty());
    }
}
