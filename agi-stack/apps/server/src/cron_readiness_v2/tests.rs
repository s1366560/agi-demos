use super::*;
use std::sync::Arc;

#[test]
fn cron_readiness_candidate_has_no_running_authority() {
    let readiness = CronReadinessV2::new(CronRuntimeDependenciesV2::ready_for_test());
    let snapshot = readiness.snapshot();
    assert_eq!(snapshot.phase, CronRuntimePhaseV2::Candidate);
    assert!(!snapshot.ready);
    assert!(!snapshot.loop_started);
}

#[test]
fn cron_readiness_stub_and_missing_runtime_dependencies_are_explicitly_blocked() {
    let readiness = CronReadinessV2::new(CronRuntimeDependenciesV2::postgres(
        CronRuntimeProvenanceV2 {
            model: CronModelBackendV2::Stub,
            checkpoint: CronCheckpointBackendV2::Postgres,
        },
        CronExecutionCapabilities::default(),
    ));
    readiness.published();
    assert!(!readiness.confirm_loop_started());
    let snapshot = readiness.snapshot();
    assert_eq!(snapshot.phase, CronRuntimePhaseV2::Blocked);
    assert!(!snapshot.ready);
    for reason in [
        CronReadinessBlockerV2::RealModelUnavailable,
        CronReadinessBlockerV2::OrdinaryHitlResumeNotComposed,
        CronReadinessBlockerV2::PermissionResumeNotComposed,
        CronReadinessBlockerV2::SealedEnvironmentResumeNotComposed,
        CronReadinessBlockerV2::ScopedToolReadsNotComposed,
        CronReadinessBlockerV2::MutationAuthorityNotComposed,
    ] {
        assert!(snapshot.blockers.contains(&reason), "missing {reason:?}");
    }
}

#[test]
fn cron_readiness_publication_waits_for_the_actual_loop_and_cannot_reopen_after_stop() {
    let readiness = Arc::new(CronReadinessV2::new(
        CronRuntimeDependenciesV2::ready_for_test(),
    ));
    readiness.published();
    assert_eq!(readiness.snapshot().phase, CronRuntimePhaseV2::Published);
    assert!(!readiness.snapshot().ready);
    assert!(readiness.confirm_loop_started());
    assert!(readiness.snapshot().ready);
    readiness.draining();
    assert!(!readiness.snapshot().ready);
    assert!(!readiness.confirm_loop_started());
    readiness.stopped(false);
    assert_eq!(readiness.snapshot().phase, CronRuntimePhaseV2::Stopped);
    readiness.published();
    assert!(!readiness.confirm_loop_started());
    assert_eq!(readiness.snapshot().phase, CronRuntimePhaseV2::Stopped);
}

#[test]
fn cron_readiness_http_configuration_cannot_hide_in_memory_or_uncomposed_dependencies() {
    let readiness = CronReadinessV2::new(CronRuntimeDependenciesV2::postgres(
        CronRuntimeProvenanceV2 {
            model: CronModelBackendV2::HttpConfigured,
            checkpoint: CronCheckpointBackendV2::InMemory,
        },
        CronExecutionCapabilities::default(),
    ));
    readiness.published();
    let snapshot = readiness.snapshot();
    assert!(!snapshot.ready);
    assert!(snapshot
        .blockers
        .contains(&CronReadinessBlockerV2::PersistentCheckpointUnavailable));
    assert!(snapshot
        .blockers
        .contains(&CronReadinessBlockerV2::SealedEnvironmentResumeNotComposed));
    assert!(!snapshot
        .blockers
        .contains(&CronReadinessBlockerV2::RealModelUnavailable));
}

#[test]
fn released_contract_reports_unsupported_scope_without_claiming_global_readiness() {
    let readiness = CronReadinessV2::new(CronRuntimeDependenciesV2::postgres(
        CronRuntimeProvenanceV2 {
            model: CronModelBackendV2::HttpConfigured,
            checkpoint: CronCheckpointBackendV2::Postgres,
        },
        CronExecutionCapabilities::pure_tools_ordinary_hitl(),
    ));
    readiness.blocked(CronReadinessBlockerV2::ProductionGateClosed);
    readiness.published();
    let snapshot = readiness.snapshot();
    assert_eq!(
        snapshot.blockers,
        vec![CronReadinessBlockerV2::ProductionGateClosed]
    );
    assert!(!snapshot.ready);
    assert!(!readiness.confirm_loop_started());
    let wire = serde_json::to_value(snapshot).unwrap();
    assert_eq!(
        wire["capabilities"]["contract"],
        "pure_tools_ordinary_hitl_v1"
    );
    assert_eq!(
        wire["capabilities"]["supported_hitl"],
        serde_json::json!(["clarification", "decision"])
    );
    assert_eq!(
        wire["capabilities"]["unsupported_hitl"],
        serde_json::json!(["permission", "env_var", "a2ui_action"])
    );
    assert_eq!(wire["capabilities"]["mutations"], false);
    assert_eq!(wire["capabilities"]["scoped_tool_reads"], false);
}

#[test]
fn released_contract_still_requires_actual_supported_dependencies() {
    let mut capabilities = CronExecutionCapabilities::pure_tools_ordinary_hitl();
    capabilities.ordinary_hitl_resume = false;
    capabilities.pure_tools = false;
    let readiness = CronReadinessV2::new(CronRuntimeDependenciesV2::postgres(
        CronRuntimeProvenanceV2 {
            model: CronModelBackendV2::Stub,
            checkpoint: CronCheckpointBackendV2::InMemory,
        },
        capabilities,
    ));
    readiness.published();
    assert!(!readiness.confirm_loop_started());
    for blocker in [
        CronReadinessBlockerV2::OrdinaryHitlResumeNotComposed,
        CronReadinessBlockerV2::PureToolAuthorityNotComposed,
        CronReadinessBlockerV2::RealModelUnavailable,
        CronReadinessBlockerV2::PersistentCheckpointUnavailable,
    ] {
        assert!(readiness.snapshot().blockers.contains(&blocker));
    }
}

#[tokio::test]
async fn cron_readiness_observes_worker_panic_and_repeated_drain_cannot_clear_failure() {
    use crate::worker_lifecycle_v2::WorkerRuntimeV2;
    let readiness = Arc::new(CronReadinessV2::new(
        CronRuntimeDependenciesV2::ready_for_test(),
    ));
    readiness.published();
    let loop_readiness = readiness.clone();
    let (started, start) = tokio::sync::oneshot::channel();
    let runtime = WorkerRuntimeV2::spawn_observed(
        "cron-readiness-panic",
        move |_| async move {
            assert!(loop_readiness.confirm_loop_started());
            started.send(()).unwrap();
            panic!("injected readiness failure");
        },
        Some(readiness.clone()),
    );
    start.await.unwrap();
    assert!(runtime.shutdown().await.is_err());
    let failed = readiness.snapshot();
    assert_eq!(failed.phase, CronRuntimePhaseV2::Failed);
    assert!(!failed.ready);
    assert!(failed
        .blockers
        .contains(&CronReadinessBlockerV2::WorkerFailed));
    assert!(runtime.shutdown().await.is_err());
    assert_eq!(readiness.snapshot(), failed);
}
