use super::*;
use crate::background_workers_v2::{
    definitions_from_factories_v2, WORKER_MODULES_V2, WORKER_SERVICES_V2,
};
use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;
use agistack_plugin_host::{
    parse_profile_snapshot_v2, rust_server_host_definition_v2,
    rust_server_http_routes_definition_v2, ContextV2, DataPlaneTargetV2, GenerationManagerV2,
    LoaderV2, PluginDefinitionV2, PluginModuleRuntimeV2, RuntimeGenerationV2, RuntimeV2Error,
    ScopeKindV2, ScopeV2,
};
use async_trait::async_trait;
use serde_json::Value;
use std::{
    collections::BTreeMap,
    sync::atomic::{AtomicUsize, Ordering},
    time::Duration,
};

const LIMIT: Duration = Duration::from_secs(2);

fn profile(generation: u64) -> ProfileSnapshotV2 {
    let mut snapshot = parse_profile_snapshot_v2(include_str!(
        "../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    snapshot.generation = generation;
    snapshot.digest = format!("worker-generation-{generation}");
    snapshot
}

fn loader(factories: [WorkerFactoryV2; 3]) -> LoaderV2 {
    LoaderV2::for_target(
        DataPlaneTargetV2::RustServer,
        [
            rust_server_host_definition_v2(),
            rust_server_http_routes_definition_v2(),
        ]
        .into_iter()
        .chain(definitions_from_factories_v2(factories)),
    )
}

fn controllers(generation: &RuntimeGenerationV2) -> Vec<Arc<BackgroundWorkerControllerV2>> {
    let scope = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    WORKER_SERVICES_V2
        .iter()
        .map(|service| {
            generation
                .resolve::<Arc<BackgroundWorkerControllerV2>>(service, &scope, None)
                .unwrap()
                .as_ref()
                .clone()
        })
        .collect()
}

fn no_workers() -> [WorkerFactoryV2; 3] {
    std::array::from_fn(|_| Arc::new(|| None) as WorkerFactoryV2)
}

struct Probe {
    starts: AtomicUsize,
    entered: tokio::sync::Notify,
    finish: tokio::sync::Semaphore,
    settled: AtomicUsize,
}

impl Probe {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            starts: AtomicUsize::new(0),
            entered: tokio::sync::Notify::new(),
            finish: tokio::sync::Semaphore::new(0),
            settled: AtomicUsize::new(0),
        })
    }
    fn factory(self: &Arc<Self>) -> WorkerFactoryV2 {
        let probe = self.clone();
        Arc::new(move || {
            probe.starts.fetch_add(1, Ordering::SeqCst);
            let probe = probe.clone();
            Some(WorkerRuntimeV2::spawn(
                "blocked-generation-worker",
                move |_stop| async move {
                    probe.entered.notify_one();
                    probe.finish.acquire().await.unwrap().forget();
                    probe.settled.fetch_add(1, Ordering::SeqCst);
                },
            ))
        })
    }
}

struct FailApply;
#[async_trait]
impl PluginModuleRuntimeV2 for FailApply {
    async fn apply(
        &self,
        _: &mut ContextV2,
        _: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        Err(RuntimeV2Error::Module(
            "injected candidate apply failure".into(),
        ))
    }
}

#[tokio::test]
async fn worker_modules_apply_paused_and_candidate_failure_starts_no_jobs() {
    let probe = Probe::new();
    let definitions =
        definitions_from_factories_v2([probe.factory(), probe.factory(), probe.factory()]);
    let mut failed: Vec<PluginDefinitionV2> = definitions;
    failed[2].module = Arc::new(FailApply);
    let candidate = LoaderV2::for_target(
        DataPlaneTargetV2::RustServer,
        [
            rust_server_host_definition_v2(),
            rust_server_http_routes_definition_v2(),
        ]
        .into_iter()
        .chain(failed),
    );
    let error = candidate
        .stage(profile(1))
        .await
        .err()
        .expect("candidate apply fails");
    assert!(error
        .to_string()
        .contains("injected candidate apply failure"));
    assert_eq!(probe.starts.load(Ordering::SeqCst), 0);
    let generation = loader([probe.factory(), probe.factory(), probe.factory()])
        .stage(profile(2))
        .await
        .unwrap();
    assert_eq!(probe.starts.load(Ordering::SeqCst), 0);
    let manager = GenerationManagerV2::new();
    manager.publish(generation).await;
    assert_eq!(probe.starts.load(Ordering::SeqCst), 0);
    tokio::time::timeout(LIMIT, manager.close()).await.unwrap();
}

#[tokio::test]
async fn published_worker_generation_starts_once_and_cancelled_shutdown_holds_old_lease() {
    let probe = Probe::new();
    let mut factories = no_workers();
    factories[0] = probe.factory();
    let old = loader(factories).stage(profile(1)).await.unwrap();
    let handles = controllers(&old);
    let manager = GenerationManagerV2::new();
    manager.publish(old.clone()).await;
    let owner = BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), handles.clone())
        .await
        .unwrap();
    tokio::time::timeout(LIMIT, probe.entered.notified())
        .await
        .unwrap();
    handles[0].activate().unwrap();
    assert_eq!(probe.starts.load(Ordering::SeqCst), 1);
    let new = loader(no_workers()).stage(profile(2)).await.unwrap();
    manager.publish(new).await;
    assert!(
        tokio::time::timeout(Duration::from_millis(20), owner.shutdown())
            .await
            .is_err()
    );
    assert_eq!(
        controllers(&old).len(),
        3,
        "old services retained while work drains"
    );
    probe.finish.add_permits(1);
    tokio::time::timeout(LIMIT, owner.shutdown())
        .await
        .unwrap()
        .unwrap();
    owner.shutdown().await.unwrap();
    assert_eq!(probe.settled.load(Ordering::SeqCst), 1);
    let scope = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    assert!(matches!(
        old.resolve::<Arc<BackgroundWorkerControllerV2>>(WORKER_SERVICES_V2[0], &scope, None),
        Err(RuntimeV2Error::GenerationDisposed)
    ));
    manager.close().await;
}

#[tokio::test]
async fn dropped_generation_owner_drains_before_releasing_retired_generation() {
    let probe = Probe::new();
    let mut factories = no_workers();
    factories[0] = probe.factory();
    let old = loader(factories).stage(profile(1)).await.unwrap();
    let manager = GenerationManagerV2::new();
    manager.publish(old.clone()).await;
    let owner = BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&old))
        .await
        .unwrap();
    tokio::time::timeout(LIMIT, probe.entered.notified())
        .await
        .unwrap();
    manager.close().await;
    drop(owner);
    assert_eq!(controllers(&old).len(), 3);
    probe.finish.add_permits(1);
    let scope = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    tokio::time::timeout(LIMIT, async {
        while old
            .resolve::<Arc<BackgroundWorkerControllerV2>>(WORKER_SERVICES_V2[0], &scope, None)
            .is_ok()
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(probe.settled.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn generation_panic_failure_repeats_after_other_workers_finish_draining() {
    let probe = Probe::new();
    let mut factories = no_workers();
    factories[0] = Arc::new(|| {
        Some(WorkerRuntimeV2::spawn("panic-worker", |_| async {
            panic!("injected worker panic")
        }))
    });
    factories[1] = probe.factory();
    let generation = loader(factories).stage(profile(1)).await.unwrap();
    let manager = GenerationManagerV2::new();
    manager.publish(generation.clone()).await;
    let owner =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&generation))
            .await
            .unwrap();
    tokio::time::timeout(LIMIT, probe.entered.notified())
        .await
        .unwrap();
    assert!(
        tokio::time::timeout(Duration::from_millis(20), owner.shutdown())
            .await
            .is_err()
    );
    probe.finish.add_permits(1);
    let first = tokio::time::timeout(LIMIT, owner.shutdown())
        .await
        .unwrap()
        .expect_err("panic retained");
    assert!(first.contains("panic-worker"));
    assert_eq!(owner.shutdown().await.unwrap_err(), first);
    assert_eq!(probe.settled.load(Ordering::SeqCst), 1);
    manager.close().await;
}

#[tokio::test]
async fn each_disabled_worker_entry_suppresses_only_its_factory() {
    for disabled in 0..WORKER_MODULES_V2.len() {
        let probes: [Arc<Probe>; 3] = std::array::from_fn(|_| Probe::new());
        let mut snapshot = profile(10 + disabled as u64);
        snapshot
            .entries
            .iter_mut()
            .find(|entry| entry.module_ref == WORKER_MODULES_V2[disabled])
            .unwrap()
            .enabled = false;
        let generation = loader(std::array::from_fn(|index| probes[index].factory()))
            .stage(snapshot)
            .await
            .unwrap();
        let scope = ScopeV2 {
            kind: ScopeKindV2::Root,
            tenant_id: None,
            project_id: None,
            session_id: None,
        };
        assert!(generation
            .resolve::<Arc<BackgroundWorkerControllerV2>>(
                WORKER_SERVICES_V2[disabled],
                &scope,
                None
            )
            .is_err());
        let enabled = WORKER_SERVICES_V2
            .iter()
            .enumerate()
            .filter(|(index, _)| *index != disabled)
            .map(|(_, service)| {
                generation
                    .resolve::<Arc<BackgroundWorkerControllerV2>>(service, &scope, None)
                    .unwrap()
                    .as_ref()
                    .clone()
            })
            .collect();
        let manager = GenerationManagerV2::new();
        manager.publish(generation).await;
        let owner = BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), enabled)
            .await
            .unwrap();
        for (index, probe) in probes.iter().enumerate() {
            assert_eq!(
                probe.starts.load(Ordering::SeqCst),
                usize::from(index != disabled),
                "disabled module {disabled}, observed factory {index}"
            );
            probe.finish.add_permits(1);
        }
        tokio::time::timeout(LIMIT, owner.shutdown())
            .await
            .unwrap()
            .unwrap();
        manager.close().await;
    }
}

#[tokio::test]
async fn each_worker_autostart_false_suppresses_only_its_factory() {
    for disabled in 0..WORKER_MODULES_V2.len() {
        let probes: [Arc<Probe>; 3] = std::array::from_fn(|_| Probe::new());
        let mut snapshot = profile(20 + disabled as u64);
        snapshot
            .entries
            .iter_mut()
            .find(|entry| entry.module_ref == WORKER_MODULES_V2[disabled])
            .unwrap()
            .config
            .insert("autostart".into(), Value::Bool(false));
        let generation = loader(std::array::from_fn(|index| probes[index].factory()))
            .stage(snapshot)
            .await
            .unwrap();
        let handles = controllers(&generation);
        assert_eq!(
            handles.len(),
            3,
            "autostart false keeps module service available"
        );
        let manager = GenerationManagerV2::new();
        manager.publish(generation).await;
        let owner = BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), handles)
            .await
            .unwrap();
        for (index, probe) in probes.iter().enumerate() {
            assert_eq!(
                probe.starts.load(Ordering::SeqCst),
                usize::from(index != disabled),
                "autostart false module {disabled}, observed factory {index}"
            );
            probe.finish.add_permits(1);
        }
        tokio::time::timeout(LIMIT, owner.shutdown())
            .await
            .unwrap()
            .unwrap();
        manager.close().await;
    }
}

#[tokio::test]
async fn factory_panic_cannot_restart_controller_and_stops_later_factories() {
    let attempts = Arc::new(AtomicUsize::new(0));
    let attempts_in_factory = attempts.clone();
    let later = Probe::new();
    let factories = [
        Arc::new(move || -> Option<WorkerRuntimeV2> {
            attempts_in_factory.fetch_add(1, Ordering::SeqCst);
            panic!("injected factory panic");
        }) as WorkerFactoryV2,
        later.factory(),
        Arc::new(|| None),
    ];
    let generation = loader(factories).stage(profile(30)).await.unwrap();
    let handles = controllers(&generation);
    let manager = GenerationManagerV2::new();
    manager.publish(generation).await;
    let result = tokio::time::timeout(
        LIMIT,
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), handles.clone()),
    )
    .await
    .unwrap();
    assert!(result.is_err());
    assert!(handles[0].activate().is_err());
    assert!(handles[1].activate().is_err());
    assert_eq!(attempts.load(Ordering::SeqCst), 1);
    assert_eq!(later.starts.load(Ordering::SeqCst), 0);
    manager.close().await;
}

#[tokio::test]
async fn dropping_unpolled_generation_start_releases_lease_without_starting_jobs() {
    let probe = Probe::new();
    let generation = loader([probe.factory(), probe.factory(), probe.factory()])
        .stage(profile(40))
        .await
        .unwrap();
    let manager = GenerationManagerV2::new();
    manager.publish(generation.clone()).await;
    let startup =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&generation));
    // The current-thread executor cannot poll the spawned owner until we yield.
    // Dropping this unpolled startup must still stop it and return its lease.
    drop(startup);
    manager.close().await;
    let scope = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    tokio::time::timeout(LIMIT, async {
        loop {
            match generation.resolve::<Arc<BackgroundWorkerControllerV2>>(
                WORKER_SERVICES_V2[0],
                &scope,
                None,
            ) {
                Err(RuntimeV2Error::GenerationDisposed) => break,
                Ok(_) => tokio::task::yield_now().await,
                Err(error) => panic!("unexpected service resolution failure: {error}"),
            }
        }
    })
    .await
    .expect("unpolled startup lease drains");
    assert_eq!(probe.starts.load(Ordering::SeqCst), 0);
}
