use super::*;

struct LifecycleProvider {
    generation: u64,
    events: Arc<Mutex<Vec<String>>>,
}

#[async_trait]
impl PluginModuleRuntimeV2 for LifecycleProvider {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        lock(&self.events).push(format!("provider-apply:{}", self.generation));
        context.provide("service:clock", self.generation)?;
        let generation = self.generation;
        let events = Arc::clone(&self.events);
        context.effect(
            "provider-lifecycle",
            Box::new(move || {
                Box::pin(async move {
                    lock(&events).push(format!("provider-dispose:{generation}"));
                    Ok(())
                })
            }),
        )?;
        Ok(())
    }
}

struct LifecycleConsumer {
    generation: u64,
    events: Arc<Mutex<Vec<String>>>,
}

#[async_trait]
impl PluginModuleRuntimeV2 for LifecycleConsumer {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        let provider_generation = context.require::<u64>("clock")?;
        lock(&self.events).push(format!(
            "consumer-apply:{}->{provider_generation}",
            self.generation
        ));
        let generation = self.generation;
        let events = Arc::clone(&self.events);
        context.effect(
            "consumer-lifecycle",
            Box::new(move || {
                Box::pin(async move {
                    lock(&events).push(format!("consumer-dispose:{generation}"));
                    Ok(())
                })
            }),
        )?;
        Ok(())
    }
}

fn lifecycle_definitions(
    snapshot: &ProfileSnapshotV2,
    generation: u64,
    events: Arc<Mutex<Vec<String>>>,
) -> [PluginDefinitionV2; 2] {
    [
        PluginDefinitionV2 {
            module_ref: "builtin://conformance/root-provider".into(),
            contract_digest: module_contract_digest(
                snapshot,
                "builtin://conformance/root-provider",
            ),
            module: Arc::new(LifecycleProvider {
                generation,
                events: Arc::clone(&events),
            }),
        },
        PluginDefinitionV2 {
            module_ref: "builtin://conformance/session-consumer".into(),
            contract_digest: module_contract_digest(
                snapshot,
                "builtin://conformance/session-consumer",
            ),
            module: Arc::new(LifecycleConsumer { generation, events }),
        },
    ]
}

fn snapshot_generation(generation: u64, entries_enabled: bool) -> ProfileSnapshotV2 {
    let mut raw: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    raw["generation"] = Value::from(generation);
    if !entries_enabled {
        raw["entries"] = serde_json::json!([]);
    }
    refresh_snapshot_digest(&mut raw);
    parse_profile_snapshot_v2(&raw.to_string()).expect("generation snapshot must parse")
}

fn lifecycle_fixture() -> Value {
    let conformance: Value =
        serde_json::from_str(CONFORMANCE).expect("shared conformance fixture must parse");
    conformance["provider_generation_lifecycle"].clone()
}

fn fixture_generation(fixture: &Value, key: &str) -> u64 {
    fixture[key].as_u64().expect("lifecycle generation")
}

fn fixture_events(fixture: &Value, key: &str) -> Vec<String> {
    fixture[key]
        .as_array()
        .expect("lifecycle event sequence")
        .iter()
        .map(|event| event.as_str().expect("lifecycle event").to_owned())
        .collect()
}

#[test]
fn provider_removal_disposes_consumers_first_and_later_generation_reassembles() {
    block_on(async {
        let fixture = lifecycle_fixture();
        let initial_generation = fixture_generation(&fixture, "initial_generation");
        let removed_generation = fixture_generation(&fixture, "removed_generation");
        let restored_generation = fixture_generation(&fixture, "restored_generation");
        let events = Arc::new(Mutex::new(Vec::new()));
        let first_snapshot = snapshot_generation(initial_generation, true);
        let first = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            lifecycle_definitions(&first_snapshot, initial_generation, Arc::clone(&events)),
            target_catalog_json(&first_snapshot, &DataPlaneTargetV2::RustServer),
        )
        .stage(first_snapshot)
        .await
        .expect("first generation must stage");
        let manager = GenerationManagerV2::new();
        manager.publish(first).await;
        assert_eq!(*lock(&events), fixture_events(&fixture, "after_initial"));

        let empty_snapshot = snapshot_generation(removed_generation, false);
        let empty = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            std::iter::empty::<PluginDefinitionV2>(),
            target_catalog_json(&empty_snapshot, &DataPlaneTargetV2::RustServer),
        )
        .stage(empty_snapshot)
        .await
        .expect("empty generation must stage");
        manager.publish(empty).await;
        assert_eq!(*lock(&events), fixture_events(&fixture, "after_removal"));

        let restored_snapshot = snapshot_generation(restored_generation, true);
        let restored = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            lifecycle_definitions(&restored_snapshot, restored_generation, Arc::clone(&events)),
            target_catalog_json(&restored_snapshot, &DataPlaneTargetV2::RustServer),
        )
        .stage(restored_snapshot)
        .await
        .expect("restored generation must stage");
        manager.publish(restored).await;
        assert_eq!(*lock(&events), fixture_events(&fixture, "after_restore"));

        manager.close().await;
        assert_eq!(*lock(&events), fixture_events(&fixture, "after_close"));
    });
}
