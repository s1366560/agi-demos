use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};

use agistack_plugin_host::{
    parse_profile_snapshot_v2, project_snapshot_entries_v2, ContextV2, DataPlaneTargetV2,
    GenerationManagerV2, LoaderV2, PluginDefinitionV2, PluginModuleRuntimeV2,
    PluginProtocolV2Error, RuntimeV2Error,
};
use async_trait::async_trait;
use futures::executor::block_on;
use serde_json::Value;

const SNAPSHOT: &str = include_str!("../../../../shared/fixtures/platform-plugin-profile.v2.json");
const CONFORMANCE: &str =
    include_str!("../../../../shared/fixtures/plugin-runtime-conformance.v2.json");

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

struct RootProvider {
    value: u64,
    disposed: Arc<Mutex<Vec<String>>>,
}

#[async_trait]
impl PluginModuleRuntimeV2 for RootProvider {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        context.provide("service:clock", self.value)?;
        for label in ["listener", "module"] {
            let disposed = Arc::clone(&self.disposed);
            let owned_label = label.to_owned();
            context.effect(
                label,
                Box::new(move || {
                    Box::pin(async move {
                        lock(&disposed).push(owned_label);
                        Ok(())
                    })
                }),
            )?;
        }
        Ok(())
    }
}

struct SessionConsumer {
    observed: Arc<Mutex<Vec<u64>>>,
    fail: bool,
}

#[async_trait]
impl PluginModuleRuntimeV2 for SessionConsumer {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        let value = context.require::<u64>("clock")?;
        lock(&self.observed).push(*value);
        if self.fail {
            return Err(RuntimeV2Error::Module("boom".into()));
        }
        Ok(())
    }
}

fn loader(
    value: u64,
    fail: bool,
    disposed: Arc<Mutex<Vec<String>>>,
    observed: Arc<Mutex<Vec<u64>>>,
) -> LoaderV2 {
    LoaderV2::new([
        PluginDefinitionV2 {
            module_ref: "builtin://conformance/root-provider".into(),
            provides: vec!["service:clock".into()],
            module: Arc::new(RootProvider { value, disposed }),
        },
        PluginDefinitionV2 {
            module_ref: "builtin://conformance/session-consumer".into(),
            provides: Vec::new(),
            module: Arc::new(SessionConsumer { observed, fail }),
        },
    ])
}

#[test]
fn shared_snapshot_digest_and_canonical_vector_match_python() {
    let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("shared v2 snapshot must parse");
    let conformance: Value =
        serde_json::from_str(CONFORMANCE).expect("shared conformance fixture must parse");
    assert_eq!(
        conformance["snapshot_digest"].as_str(),
        Some(snapshot.digest.as_str())
    );

    let vector = &conformance["canonical_json"][0];
    let canonical = serde_jcs::to_string(&vector["input"]).expect("JCS vector must serialize");
    assert_eq!(canonical, vector["expected"]);
    for (target, expected) in [
        (
            DataPlaneTargetV2::Python,
            &conformance["target_projection"]["python"],
        ),
        (
            DataPlaneTargetV2::RustServer,
            &conformance["target_projection"]["rust-server"],
        ),
        (
            DataPlaneTargetV2::DesktopSidecar,
            &conformance["target_projection"]["desktop-sidecar"],
        ),
        (
            DataPlaneTargetV2::Web,
            &conformance["target_projection"]["web"],
        ),
        (
            DataPlaneTargetV2::DesktopRenderer,
            &conformance["target_projection"]["desktop-renderer"],
        ),
    ] {
        let projected: Vec<&str> = project_snapshot_entries_v2(&snapshot, &target)
            .into_iter()
            .map(|entry| entry.entry_id.as_str())
            .collect();
        assert_eq!(
            serde_json::to_value(projected).expect("projection must encode"),
            *expected
        );
    }
}

#[test]
fn child_targets_must_be_a_subset_of_parent_targets() {
    let mut changed: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    changed["manifests"][0]["modules"][1]["targets"] =
        serde_json::json!(["python", "rust-server", "web", "desktop-renderer"]);

    assert!(matches!(
        parse_profile_snapshot_v2(&changed.to_string()),
        Err(PluginProtocolV2Error::InvalidParentTargets { .. })
    ));
}

#[test]
fn module_targets_must_be_non_empty_and_unique() {
    for targets in [
        serde_json::json!([]),
        serde_json::json!(["python", "python"]),
    ] {
        let mut changed: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
        changed["manifests"][0]["modules"][0]["targets"] = targets;

        assert!(matches!(
            parse_profile_snapshot_v2(&changed.to_string()),
            Err(PluginProtocolV2Error::InvalidShape(_))
        ));
    }
}

#[test]
fn v1_unknown_fields_and_digest_mutation_are_rejected() {
    assert_eq!(
        parse_profile_snapshot_v2(r#"{"schema_version":1,"plugins":[]}"#),
        Err(PluginProtocolV2Error::IncompatibleSchemaVersion)
    );

    let mut unknown: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    unknown["unexpected"] = Value::Bool(true);
    assert!(matches!(
        parse_profile_snapshot_v2(&unknown.to_string()),
        Err(PluginProtocolV2Error::InvalidShape(_))
    ));

    let mut changed: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    changed["digest"] = Value::String("0".repeat(64));
    assert!(matches!(
        parse_profile_snapshot_v2(&changed.to_string()),
        Err(PluginProtocolV2Error::DigestMismatch { .. })
    ));
}

#[test]
fn loader_resolves_inject_and_disposes_effects_in_lifo_order() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("fixture must parse");
        let disposed = Arc::new(Mutex::new(Vec::new()));
        let observed = Arc::new(Mutex::new(Vec::new()));
        let generation = loader(7, false, Arc::clone(&disposed), Arc::clone(&observed))
            .stage(snapshot)
            .await
            .expect("generation must stage");

        assert_eq!(*lock(&observed), vec![7]);
        assert_eq!(
            generation.phases(),
            vec![
                agistack_plugin_host::FiberPhaseV2::Active,
                agistack_plugin_host::FiberPhaseV2::Active,
            ]
        );

        let manager = GenerationManagerV2::new();
        manager.publish(Arc::clone(&generation)).await;
        manager.close().await;
        assert_eq!(*lock(&disposed), vec!["module", "listener"]);
    });
}

#[test]
fn loader_skips_entries_outside_its_data_plane_target() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("fixture must parse");
        let generation = LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            std::iter::empty::<PluginDefinitionV2>(),
        )
        .stage(snapshot)
        .await
        .expect("empty projection must stage");

        assert!(generation.phases().is_empty());
    });
}

#[test]
fn failed_staging_rolls_back_and_never_publishes() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("fixture must parse");
        let disposed = Arc::new(Mutex::new(Vec::new()));
        let observed = Arc::new(Mutex::new(Vec::new()));
        let result = loader(1, true, Arc::clone(&disposed), observed)
            .stage(snapshot)
            .await;
        let error = match result {
            Ok(_) => panic!("consumer failure must reject staging"),
            Err(error) => error,
        };

        assert_eq!(error, RuntimeV2Error::Module("boom".into()));
        assert_eq!(*lock(&disposed), vec!["module", "listener"]);
        assert!(matches!(
            GenerationManagerV2::new().acquire(),
            Err(RuntimeV2Error::GenerationUnavailable)
        ));
    });
}

#[test]
fn generation_lease_pins_old_services_until_release() {
    block_on(async {
        let first_snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("fixture must parse");
        let mut second_snapshot = first_snapshot.clone();
        second_snapshot.generation += 1;
        let first_disposed = Arc::new(Mutex::new(Vec::new()));
        let second_disposed = Arc::new(Mutex::new(Vec::new()));
        let first = loader(
            1,
            false,
            Arc::clone(&first_disposed),
            Arc::new(Mutex::new(Vec::new())),
        )
        .stage(first_snapshot)
        .await
        .expect("first generation must stage");
        let second = loader(
            2,
            false,
            Arc::clone(&second_disposed),
            Arc::new(Mutex::new(Vec::new())),
        )
        .stage(second_snapshot)
        .await
        .expect("second generation must stage");
        let scope = first.snapshot.entries[0].scope.clone();
        let manager = GenerationManagerV2::new();
        manager.publish(first).await;
        let old_lease = manager.acquire().expect("old lease must acquire");

        manager.publish(second).await;
        let new_lease = manager.acquire().expect("new lease must acquire");

        assert_eq!(
            *old_lease
                .generation()
                .expect("old generation must remain pinned")
                .resolve::<u64>("service:clock", &scope, None)
                .expect("old service must resolve"),
            1
        );
        assert_eq!(
            *new_lease
                .generation()
                .expect("new generation must be current")
                .resolve::<u64>("service:clock", &scope, None)
                .expect("new service must resolve"),
            2
        );
        assert!(lock(&first_disposed).is_empty());
        old_lease.release().await.expect("old lease must release");
        assert_eq!(*lock(&first_disposed), vec!["module", "listener"]);
        new_lease.release().await.expect("new lease must release");
        manager.close().await;
        assert_eq!(*lock(&second_disposed), vec!["module", "listener"]);
    });
}
