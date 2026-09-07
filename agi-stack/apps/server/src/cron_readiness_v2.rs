//! Generation-local Cron dependency and runtime observations.

use std::sync::Mutex;

use serde::Serialize;
use uuid::Uuid;

use crate::worker_lifecycle_v2::WorkerLifecycleObserverV2;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CronModelBackendV2 {
    #[default]
    Unavailable,
    Stub,
    HttpConfigured,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CronCheckpointBackendV2 {
    #[default]
    Unavailable,
    InMemory,
    Postgres,
}

/// Describes the implementations actually selected by server composition.
/// HttpConfigured is wiring provenance, not a successful provider probe.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub(crate) struct CronRuntimeProvenanceV2 {
    pub(crate) model: CronModelBackendV2,
    pub(crate) checkpoint: CronCheckpointBackendV2,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CronReadinessBlockerV2 {
    ModuleAutostartDisabled,
    AutostartDisabled,
    ProductionGateClosed,
    SchedulerNotConstructed,
    PostgresPersistenceUnavailable,
    PersistentCheckpointUnavailable,
    RealModelUnavailable,
    OrdinaryHitlResumeNotComposed,
    PermissionResumeNotComposed,
    SealedEnvironmentResumeNotComposed,
    ScopedToolReadsNotComposed,
    MutationAuthorityNotComposed,
    WorkerFailed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub(crate) struct CronRuntimeDependenciesV2 {
    pub(crate) provenance: CronRuntimeProvenanceV2,
    blockers: Vec<CronReadinessBlockerV2>,
}

impl CronRuntimeDependenciesV2 {
    /// Matches the production driver: durable stores and pure tools are wired,
    /// while resume coordination and broader tool authority are not composed.
    pub(crate) fn postgres(provenance: CronRuntimeProvenanceV2) -> Self {
        let mut blockers = vec![
            CronReadinessBlockerV2::OrdinaryHitlResumeNotComposed,
            CronReadinessBlockerV2::PermissionResumeNotComposed,
            CronReadinessBlockerV2::SealedEnvironmentResumeNotComposed,
            CronReadinessBlockerV2::ScopedToolReadsNotComposed,
            CronReadinessBlockerV2::MutationAuthorityNotComposed,
        ];
        if provenance.model != CronModelBackendV2::HttpConfigured {
            blockers.push(CronReadinessBlockerV2::RealModelUnavailable);
        }
        if provenance.checkpoint != CronCheckpointBackendV2::Postgres {
            blockers.push(CronReadinessBlockerV2::PersistentCheckpointUnavailable);
        }
        Self {
            provenance,
            blockers,
        }
    }

    pub(crate) fn unavailable() -> Self {
        let mut result = Self::postgres(CronRuntimeProvenanceV2::default());
        result
            .blockers
            .push(CronReadinessBlockerV2::PostgresPersistenceUnavailable);
        result
    }

    #[cfg(test)]
    pub(crate) fn ready_for_test() -> Self {
        Self {
            provenance: CronRuntimeProvenanceV2 {
                model: CronModelBackendV2::HttpConfigured,
                checkpoint: CronCheckpointBackendV2::Postgres,
            },
            blockers: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CronRuntimePhaseV2 {
    Candidate,
    Published,
    Blocked,
    Running,
    Draining,
    Stopped,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub(crate) struct CronReadinessSnapshotV2 {
    /// One identifier per staged resource, independent of a repeated profile digest.
    pub(crate) resource_id: String,
    pub(crate) phase: CronRuntimePhaseV2,
    /// Loop and composed dependency readiness only. This is neither an owner
    /// lease nor Cloud command admission, and never substitutes for DB fencing.
    pub(crate) ready: bool,
    pub(crate) loop_started: bool,
    pub(crate) provenance: CronRuntimeProvenanceV2,
    pub(crate) blockers: Vec<CronReadinessBlockerV2>,
}

pub(crate) struct CronReadinessV2 {
    state: Mutex<CronReadinessSnapshotV2>,
}

impl CronReadinessV2 {
    pub(crate) fn new(dependencies: CronRuntimeDependenciesV2) -> Self {
        Self {
            state: Mutex::new(CronReadinessSnapshotV2 {
                resource_id: Uuid::new_v4().to_string(),
                phase: CronRuntimePhaseV2::Candidate,
                ready: false,
                loop_started: false,
                provenance: dependencies.provenance,
                blockers: dependencies.blockers,
            }),
        }
    }

    pub(crate) fn snapshot(&self) -> CronReadinessSnapshotV2 {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    pub(crate) fn published(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.phase == CronRuntimePhaseV2::Candidate {
            state.phase = if state.blockers.is_empty() {
                CronRuntimePhaseV2::Published
            } else {
                CronRuntimePhaseV2::Blocked
            };
        }
    }

    pub(crate) fn blocked(&self, reason: CronReadinessBlockerV2) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if matches!(
            state.phase,
            CronRuntimePhaseV2::Draining | CronRuntimePhaseV2::Stopped | CronRuntimePhaseV2::Failed
        ) {
            return;
        }
        if !state.blockers.contains(&reason) {
            state.blockers.push(reason);
        }
        state.ready = false;
        if state.phase != CronRuntimePhaseV2::Candidate {
            state.phase = CronRuntimePhaseV2::Blocked;
        }
    }

    pub(crate) fn confirm_loop_started(&self) -> bool {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.phase != CronRuntimePhaseV2::Published || !state.blockers.is_empty() {
            return false;
        }
        state.phase = CronRuntimePhaseV2::Running;
        state.loop_started = true;
        state.ready = true;
        true
    }

    pub(crate) fn draining(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if !matches!(
            state.phase,
            CronRuntimePhaseV2::Stopped | CronRuntimePhaseV2::Failed
        ) {
            state.phase = CronRuntimePhaseV2::Draining;
            state.ready = false;
        }
    }

    pub(crate) fn stopped(&self, failed: bool) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.ready = false;
        if failed {
            state.phase = CronRuntimePhaseV2::Failed;
            if !state
                .blockers
                .contains(&CronReadinessBlockerV2::WorkerFailed)
            {
                state.blockers.push(CronReadinessBlockerV2::WorkerFailed);
            }
        } else if state.phase != CronRuntimePhaseV2::Failed {
            state.phase = CronRuntimePhaseV2::Stopped;
        }
    }
}

impl WorkerLifecycleObserverV2 for CronReadinessV2 {
    fn stop_requested(&self) {
        self.draining();
    }

    fn finished(&self, result: &Result<(), String>) {
        self.stopped(result.is_err());
    }
}

#[cfg(test)]
mod tests;
