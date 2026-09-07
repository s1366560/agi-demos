use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use std::time::Duration;

use agistack_plugin_host::GenerationManagerV2;

use super::support::*;
use crate::background_worker_control_v2::BackgroundWorkerGenerationV2;
use crate::background_workers_v2::CronWorkerResourceV2;
use crate::cron_readiness_v2::{
    CronReadinessBlockerV2, CronReadinessV2, CronRuntimeDependenciesV2, CronRuntimePhaseV2,
};

#[tokio::test]
async fn cron_readiness_none_factory_is_published_blocked_and_never_running() {
    let calls = Arc::new(AtomicUsize::new(0));
    let counter = calls.clone();
    let generation = loader(
        Arc::new(move || {
            let counter = counter.clone();
            CronWorkerResourceV2 {
                readiness: Arc::new(CronReadinessV2::new(
                    CronRuntimeDependenciesV2::ready_for_test(),
                )),
                factory: Arc::new(move || {
                    counter.fetch_add(1, Ordering::SeqCst);
                    None
                }),
            }
        }),
        false,
    )
    .stage(profile(1))
    .await
    .unwrap();
    let controller = resolve_controller(&generation).unwrap();
    assert_eq!(
        controller.cron_readiness().unwrap().phase,
        CronRuntimePhaseV2::Candidate
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let manager = GenerationManagerV2::new();
    manager.publish(generation.clone()).await;
    let owner =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&generation))
            .await
            .unwrap();
    let snapshot = controller.cron_readiness().unwrap();
    assert_eq!(snapshot.phase, CronRuntimePhaseV2::Blocked);
    assert_eq!(
        snapshot.blockers,
        vec![CronReadinessBlockerV2::SchedulerNotConstructed]
    );
    assert!(!snapshot.ready && !snapshot.loop_started);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    owner.shutdown().await.unwrap();
    assert_eq!(
        controller.cron_readiness().unwrap().phase,
        CronRuntimePhaseV2::Stopped
    );
    manager.close().await;
}

#[tokio::test]
async fn cron_readiness_missing_dependencies_prevent_even_factory_activation() {
    let calls = Arc::new(AtomicUsize::new(0));
    let counter = calls.clone();
    let generation = loader(
        Arc::new(move || {
            let counter = counter.clone();
            CronWorkerResourceV2 {
                readiness: Arc::new(CronReadinessV2::new(
                    CronRuntimeDependenciesV2::unavailable(),
                )),
                factory: Arc::new(move || {
                    counter.fetch_add(1, Ordering::SeqCst);
                    None
                }),
            }
        }),
        false,
    )
    .stage(profile(1))
    .await
    .unwrap();
    let controller = resolve_controller(&generation).unwrap();
    assert_eq!(
        controller.cron_readiness().unwrap().phase,
        CronRuntimePhaseV2::Candidate
    );
    let manager = GenerationManagerV2::new();
    manager.publish(generation.clone()).await;
    let owner =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&generation))
            .await
            .unwrap();
    let snapshot = controller.cron_readiness().unwrap();
    assert_eq!(snapshot.phase, CronRuntimePhaseV2::Blocked);
    assert!(snapshot
        .blockers
        .contains(&CronReadinessBlockerV2::PostgresPersistenceUnavailable));
    assert!(snapshot
        .blockers
        .contains(&CronReadinessBlockerV2::RealModelUnavailable));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    owner.shutdown().await.unwrap();
    manager.close().await;
}

#[tokio::test]
async fn cron_readiness_same_digest_resources_isolate_running_and_cancelled_drain() {
    let probe = Probe::new();
    let first_profile = profile(1);
    let mut second_profile = profile(2);
    second_profile.digest = first_profile.digest.clone();
    let first = loader(probe.factory(), false)
        .stage(first_profile)
        .await
        .unwrap();
    let second = loader(probe.factory(), false)
        .stage(second_profile)
        .await
        .unwrap();
    let first_controller = resolve_controller(&first).unwrap();
    let second_controller = resolve_controller(&second).unwrap();
    assert_ne!(
        first_controller.cron_readiness().unwrap().resource_id,
        second_controller.cron_readiness().unwrap().resource_id
    );
    let manager = GenerationManagerV2::new();
    manager.publish(first.clone()).await;
    let first_owner =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&first))
            .await
            .unwrap();
    probe.wait_entered(0).await;
    assert!(first_controller.cron_readiness().unwrap().ready);
    assert_eq!(
        second_controller.cron_readiness().unwrap().phase,
        CronRuntimePhaseV2::Candidate
    );
    manager.publish(second.clone()).await;
    let second_owner =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&second))
            .await
            .unwrap();
    probe.wait_entered(1).await;
    assert!(second_controller.cron_readiness().unwrap().ready);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), first_owner.shutdown())
            .await
            .is_err()
    );
    assert_eq!(
        first_controller.cron_readiness().unwrap().phase,
        CronRuntimePhaseV2::Draining
    );
    assert!(!first_controller.cron_readiness().unwrap().ready);
    assert!(second_controller.cron_readiness().unwrap().ready);
    probe.driver(0).finish.add_permits(1);
    first_owner.shutdown().await.unwrap();
    assert_eq!(
        first_controller.cron_readiness().unwrap().phase,
        CronRuntimePhaseV2::Stopped
    );
    assert!(second_controller.cron_readiness().unwrap().ready);
    second_controller.request_stop();
    probe.driver(1).finish.add_permits(1);
    second_owner.shutdown().await.unwrap();
    manager.close().await;
}

#[tokio::test]
async fn cron_readiness_runtime_handle_is_not_a_loop_acknowledgement() {
    let probe = Probe::new();
    let generation = loader(probe.factory(), false)
        .stage(profile(1))
        .await
        .unwrap();
    let scheduler = probe.scheduler(0);
    let readiness = scheduler.readiness();
    let runtime = scheduler.spawn_if_enabled().unwrap();
    // This current-thread test has not yielded to the spawned task yet.
    assert_eq!(readiness.snapshot().phase, CronRuntimePhaseV2::Published);
    assert!(!readiness.snapshot().ready);
    runtime.request_stop();
    assert_eq!(readiness.snapshot().phase, CronRuntimePhaseV2::Draining);
    runtime.shutdown().await.unwrap();
    assert_eq!(readiness.snapshot().phase, CronRuntimePhaseV2::Stopped);
    assert!(!readiness.snapshot().loop_started);
    assert_eq!(probe.ownership.acquires(), 0);
    let manager = GenerationManagerV2::new();
    manager.publish(generation).await;
    manager.close().await;
}
