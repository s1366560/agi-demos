use std::{sync::Arc, time::Duration};

use agistack_plugin_host::{GenerationManagerV2, RuntimeV2Error};

use crate::background_worker_control_v2::BackgroundWorkerGenerationV2;

mod pg;
mod support;
mod readiness;
use support::*;

#[tokio::test]
async fn cron_candidates_build_distinct_paused_resources_and_failure_releases_them() {
    let probe = Probe::new();
    let first = loader(probe.factory(), false)
        .stage(profile(1))
        .await
        .unwrap();
    let second = loader(probe.factory(), false)
        .stage(profile(2))
        .await
        .unwrap();
    assert_eq!(
        probe.built(),
        2,
        "each candidate must own a constructed scheduler"
    );
    assert_eq!(
        probe.ownership.acquires(),
        0,
        "candidate cannot poll or take DB authority"
    );
    assert!(probe.alive(0) && probe.alive(1));
    assert!(!Arc::ptr_eq(&probe.scheduler(0), &probe.scheduler(1)));
    let failed = loader(probe.factory(), true).stage(profile(3)).await;
    assert!(failed.is_err());
    assert_eq!(probe.built(), 3);
    assert!(
        !probe.alive(2),
        "failed candidate must release its scheduler resources"
    );
    assert_eq!(probe.ownership.acquires(), 0);
    let manager = GenerationManagerV2::new();
    manager.publish(first).await;
    manager.publish(second).await;
    manager.close().await;
    assert!(!probe.alive(0) && !probe.alive(1));
}

#[tokio::test]
async fn cron_generation_replacement_and_cancelled_drain_keep_admitted_work_alive() {
    let probe = Probe::new();
    let old = loader(probe.factory(), false)
        .stage(profile(1))
        .await
        .unwrap();
    let manager = GenerationManagerV2::new();
    manager.publish(old.clone()).await;
    let old_owner =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&old))
            .await
            .unwrap();
    probe.wait_entered(0).await;

    let next = loader(probe.factory(), false)
        .stage(profile(2))
        .await
        .unwrap();
    assert_eq!(
        probe.driver(1).starts(),
        0,
        "staged replacement cannot execute"
    );
    manager.publish(next.clone()).await;
    old_owner.request_stop();
    let new_owner =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&next))
            .await
            .unwrap();
    probe.wait_entered(1).await;
    assert!(
        tokio::time::timeout(Duration::from_millis(20), old_owner.shutdown())
            .await
            .is_err()
    );
    assert!(
        probe.alive(0),
        "cancelled drain must keep old resources leased"
    );
    assert!(resolve_controller(&old).is_ok());
    probe.driver(0).finish.add_permits(1);
    tokio::time::timeout(LIMIT, old_owner.shutdown())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        probe.driver(0).starts(),
        1,
        "old generation must stop admission before the next scope"
    );
    assert_eq!(probe.driver(0).settled(), 1);
    assert!(matches!(
        resolve_controller(&old),
        Err(RuntimeV2Error::GenerationDisposed)
    ));
    assert!(!probe.alive(0));
    assert!(probe.alive(1));

    new_owner.request_stop();
    probe.driver(1).finish.add_permits(1);
    new_owner.shutdown().await.unwrap();
    manager.close().await;
    assert!(!probe.alive(1));
    assert_eq!(probe.ownership.releases(), 2);
}
