use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};

use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;
use agistack_plugin_host::{
    parse_control_plane_distribution_v2, parse_profile_snapshot_v2, project_snapshot_entries_v2,
    ApplyStatusV2, ContextV2, DataPlaneTargetV2, GenerationManagerV2, LoaderV2, PluginDefinitionV2,
    PluginModuleRuntimeV2, PluginProtocolV2Error, PluginSnapshotReconcilerV2, RuntimeGenerationV2,
    RuntimeV2Error,
};
use async_trait::async_trait;
use futures::executor::block_on;
use serde_json::Value;
use sha2::{Digest, Sha256};

const SNAPSHOT: &str = include_str!("../../../../shared/fixtures/platform-plugin-profile.v2.json");
const CONFORMANCE: &str =
    include_str!("../../../../shared/fixtures/plugin-runtime-conformance.v2.json");
const CONTRACT_CONFORMANCE: &str =
    include_str!("../../../../shared/fixtures/plugin-contract-conformance.v2.json");

#[path = "protocol_v2/generation_lifecycle.rs"]
mod generation_lifecycle;

fn sha256_digest(value: &Value) -> String {
    let canonical = serde_jcs::to_vec(value).expect("value must canonicalize");
    format!("sha256:{:x}", Sha256::digest(canonical))
}

fn refresh_snapshot_digest(snapshot: &mut Value) {
    let mut digest_payload = snapshot.clone();
    digest_payload
        .as_object_mut()
        .expect("snapshot object")
        .remove("digest");
    snapshot["digest"] = Value::String(
        sha256_digest(&digest_payload)
            .strip_prefix("sha256:")
            .expect("digest prefix")
            .to_owned(),
    );
}

fn refresh_contract_digests(snapshot: &mut Value) {
    for manifest in snapshot["manifests"]
        .as_array_mut()
        .expect("snapshot manifests")
    {
        for module in manifest["modules"]
            .as_array_mut()
            .expect("manifest modules")
        {
            module["contract_digest"] = Value::String(sha256_digest(&module["contract"]));
        }
    }
}

fn apply_fixture_mutation(document: &mut Value, mutation: &Value) {
    if let Some(operations) = mutation["operations"].as_array() {
        for operation in operations {
            apply_fixture_mutation(document, operation);
        }
        return;
    }
    let path = mutation["path"].as_str().expect("mutation path");
    let (parent_path, raw_key) = path.rsplit_once('/').expect("nested JSON pointer");
    let key = raw_key.replace("~1", "/").replace("~0", "~");
    let parent = document
        .pointer_mut(parent_path)
        .expect("mutation parent must exist");
    let operation = mutation["operation"].as_str().expect("mutation operation");
    match parent {
        Value::Object(object) => match operation {
            "add" | "replace" => {
                object.insert(key, mutation["value"].clone());
            }
            "remove" => {
                object.remove(&key).expect("object member must exist");
            }
            _ => panic!("unsupported fixture mutation {operation}"),
        },
        Value::Array(array) => {
            let index = key.parse::<usize>().expect("array index");
            match operation {
                "add" => array.insert(index, mutation["value"].clone()),
                "replace" => array[index] = mutation["value"].clone(),
                "remove" => {
                    array.remove(index);
                }
                _ => panic!("unsupported fixture mutation {operation}"),
            }
        }
        _ => panic!("fixture mutation parent must be a container"),
    }
}

fn target_catalog_json(snapshot: &ProfileSnapshotV2, target: &DataPlaneTargetV2) -> String {
    let modules: Vec<Value> = snapshot
        .manifests
        .iter()
        .flat_map(|manifest| {
            manifest
                .modules
                .iter()
                .filter(|module| module.targets.contains(target))
                .map(|module| {
                    serde_json::json!({
                        "plugin_id": manifest.plugin_id,
                        "plugin_version": manifest.version,
                        "module_ref": module.module_ref,
                        "entrypoint": module.entrypoint,
                        "artifact_digest": module.artifact.digest,
                        "artifact_source": module.artifact.source,
                        "targets": module.targets,
                        "contract": module.contract,
                        "contract_digest": module.contract_digest,
                    })
                })
        })
        .collect();
    let mut catalog = serde_json::json!({
        "schema_version": 2,
        "modules": modules,
    });
    catalog["catalog_digest"] = Value::String(sha256_digest(&catalog));
    catalog.to_string()
}

fn refresh_catalog_digest(catalog: &mut Value) {
    let mut digest_payload = catalog.clone();
    digest_payload
        .as_object_mut()
        .expect("catalog object")
        .remove("catalog_digest");
    catalog["catalog_digest"] = Value::String(sha256_digest(&digest_payload));
}

fn module_contract_digest(snapshot: &ProfileSnapshotV2, module_ref: &str) -> String {
    snapshot
        .manifests
        .iter()
        .flat_map(|manifest| &manifest.modules)
        .find(|module| module.module_ref == module_ref)
        .expect("module contract must exist")
        .contract_digest
        .clone()
}

async fn dispose_generation(generation: Arc<RuntimeGenerationV2>) {
    let manager = GenerationManagerV2::new();
    manager.publish(generation).await;
    manager.close().await;
}

fn distribution(snapshot: Value, version: u64, nonce: &str) -> String {
    let digest = snapshot["digest"]
        .as_str()
        .expect("snapshot digest")
        .to_owned();
    serde_json::json!({
        "schema_version": 2,
        "descriptor": {
            "profile_id": snapshot["profile_id"],
            "generation": snapshot["generation"],
            "digest": digest,
        },
        "snapshot": snapshot,
        "envelope": {
            "version": version,
            "nonce": nonce,
            "snapshot_digest": digest,
            "type_url": "types.memstack.ai/plugin.profile.v2",
        },
    })
    .to_string()
}

fn snapshot_with_target(target: &str) -> Value {
    let mut snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    for module in snapshot["manifests"][0]["modules"]
        .as_array_mut()
        .expect("fixture modules")
    {
        module["targets"]
            .as_array_mut()
            .expect("fixture targets")
            .push(Value::String(target.to_owned()));
    }
    refresh_snapshot_digest(&mut snapshot);
    snapshot
}

fn ordered_sibling_snapshot(target: &str) -> ProfileSnapshotV2 {
    let mut snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    let base_module = snapshot["manifests"][0]["modules"][0].clone();
    let contract = serde_json::json!({
        "services": {"provides": [], "requires": []},
        "events": {
            "emits": [{
                "event": "ordered",
                "mode": "serial",
                "payload_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object"
                },
                "result_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "string"
                }
            }],
            "handles": [{
                "event": "ordered",
                "mode": "serial",
                "payload_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object"
                },
                "result_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "string"
                }
            }]
        },
        "config_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": false
        }
    });
    let module = |module_ref: &str| {
        let mut module = base_module.clone();
        module["module_ref"] = Value::String(module_ref.to_owned());
        module["entrypoint"] = Value::String(format!("conformance:{module_ref}"));
        module["targets"] = serde_json::json!([target]);
        module["contract"] = contract.clone();
        module
    };
    snapshot["manifests"][0]["modules"] = serde_json::json!([
        module("builtin://conformance/declared-first"),
        module("builtin://conformance/declared-second")
    ]);

    let base_entry = snapshot["entries"][0].clone();
    let entry = |entry_id: &str, module_ref: &str| {
        let mut entry = base_entry.clone();
        entry["entry_id"] = Value::String(entry_id.to_owned());
        entry["parent_entry_id"] = Value::Null;
        entry["module_ref"] = Value::String(module_ref.to_owned());
        entry["config"] = serde_json::json!({});
        entry["inject"] = serde_json::json!({});
        entry["isolate"] = serde_json::json!({});
        entry["scope"] = serde_json::json!({"kind": "root"});
        entry["permissions"] = serde_json::json!([]);
        entry
    };
    snapshot["entries"] = serde_json::json!([
        entry("z-declared-first", "builtin://conformance/declared-first"),
        entry("a-declared-second", "builtin://conformance/declared-second")
    ]);
    refresh_contract_digests(&mut snapshot);
    refresh_snapshot_digest(&mut snapshot);
    parse_profile_snapshot_v2(&snapshot.to_string()).expect("ordered sibling snapshot must parse")
}

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
    snapshot: &ProfileSnapshotV2,
    value: u64,
    fail: bool,
    disposed: Arc<Mutex<Vec<String>>>,
    observed: Arc<Mutex<Vec<u64>>>,
) -> LoaderV2 {
    LoaderV2::for_target_with_catalog_json(
        DataPlaneTargetV2::RustServer,
        definitions(snapshot, value, fail, disposed, observed),
        target_catalog_json(snapshot, &DataPlaneTargetV2::RustServer),
    )
}

fn definitions(
    snapshot: &ProfileSnapshotV2,
    value: u64,
    fail: bool,
    disposed: Arc<Mutex<Vec<String>>>,
    observed: Arc<Mutex<Vec<u64>>>,
) -> [PluginDefinitionV2; 2] {
    [
        PluginDefinitionV2 {
            module_ref: "builtin://conformance/root-provider".into(),
            contract_digest: module_contract_digest(
                snapshot,
                "builtin://conformance/root-provider",
            ),
            module: Arc::new(RootProvider { value, disposed }),
        },
        PluginDefinitionV2 {
            module_ref: "builtin://conformance/session-consumer".into(),
            contract_digest: module_contract_digest(
                snapshot,
                "builtin://conformance/session-consumer",
            ),
            module: Arc::new(SessionConsumer { observed, fail }),
        },
    ]
}

struct CompletenessProbe {
    operation: String,
    name: String,
    root: bool,
}

#[async_trait]
impl PluginModuleRuntimeV2 for CompletenessProbe {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        if self.root && self.operation != "provide" {
            context.provide("service:clock", 1_u64)?;
        }
        match self.operation.as_str() {
            "provide" => context.provide(&self.name, 1_u64),
            "require" => context.require::<u64>(&self.name).map(|_| ()),
            "on" => context.on(&self.name, |payload| async move { Ok(payload) }),
            "dispatch" => context.dispatch(&self.name, Value::Null).await.map(|_| ()),
            operation => panic!("unsupported runtime operation {operation}"),
        }
    }
}

struct EventProvider {
    invalid_choose_result: bool,
}

#[async_trait]
impl PluginModuleRuntimeV2 for EventProvider {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        context.provide("service:clock", 7_u64)?;
        context.on("choose", |_payload| async { Ok(Value::Null) })?;
        let invalid_choose_result = self.invalid_choose_result;
        context.on("choose", move |_payload| async move {
            if invalid_choose_result {
                Ok(serde_json::json!(7))
            } else {
                Ok(serde_json::json!("selected"))
            }
        })?;
        context.on("transform", |payload| async move {
            let value = payload
                .as_i64()
                .ok_or_else(|| RuntimeV2Error::Module("transform expected integer".into()))?;
            Ok(serde_json::json!(value + 1))
        })?;
        context.on("transform", |payload| async move {
            let value = payload
                .as_i64()
                .ok_or_else(|| RuntimeV2Error::Module("transform expected integer".into()))?;
            Ok(serde_json::json!(value * 2))
        })?;
        for event in ["notify", "audit"] {
            context.on(event, |_payload| async move { Ok(serde_json::json!([3])) })?;
            context.on(event, |_payload| async move { Ok(serde_json::json!([4])) })?;
        }
        Ok(())
    }
}

struct EventConsumer {
    context: Arc<Mutex<Option<ContextV2>>>,
}

struct OrderedListener {
    label: String,
    applied: Arc<Mutex<Vec<String>>>,
    contexts: Arc<Mutex<Vec<ContextV2>>>,
}

#[async_trait]
impl PluginModuleRuntimeV2 for OrderedListener {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        lock(&self.applied).push(self.label.clone());
        let label = self.label.clone();
        context.on("ordered", move |_payload| {
            let result = Value::String(label.clone());
            async move { Ok(result) }
        })?;
        lock(&self.contexts).push(context.clone());
        Ok(())
    }
}

#[async_trait]
impl PluginModuleRuntimeV2 for EventConsumer {
    async fn apply(
        &self,
        context: &mut ContextV2,
        _config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        context.require::<u64>("clock")?;
        *lock(&self.context) = Some(context.clone());
        Ok(())
    }
}

fn event_definitions(
    snapshot: &ProfileSnapshotV2,
    context: Arc<Mutex<Option<ContextV2>>>,
    invalid_choose_result: bool,
) -> [PluginDefinitionV2; 2] {
    [
        PluginDefinitionV2 {
            module_ref: "builtin://conformance/root-provider".into(),
            contract_digest: module_contract_digest(
                snapshot,
                "builtin://conformance/root-provider",
            ),
            module: Arc::new(EventProvider {
                invalid_choose_result,
            }),
        },
        PluginDefinitionV2 {
            module_ref: "builtin://conformance/session-consumer".into(),
            contract_digest: module_contract_digest(
                snapshot,
                "builtin://conformance/session-consumer",
            ),
            module: Arc::new(EventConsumer { context }),
        },
    ]
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
fn shared_contract_conformance_negative_cases_match_stable_error_codes() {
    block_on(async {
        let fixture: Value =
            serde_json::from_str(CONTRACT_CONFORMANCE).expect("contract fixture must parse");
        for case in fixture["negative_cases"]
            .as_array()
            .expect("negative cases")
        {
            let mut raw: Value = serde_json::from_str(SNAPSHOT).expect("snapshot fixture");
            let mutation = &case["mutation"];
            apply_fixture_mutation(&mut raw, mutation);
            if mutation["refresh_contract_digest"].as_bool() == Some(true) {
                refresh_contract_digests(&mut raw);
            }
            refresh_snapshot_digest(&mut raw);

            let expected = case["expected_error"].as_str().expect("expected error");
            let actual = match parse_profile_snapshot_v2(&raw.to_string()) {
                Err(error) => error.code(),
                Ok(snapshot) => {
                    let disposed = Arc::new(Mutex::new(Vec::new()));
                    let observed = Arc::new(Mutex::new(Vec::new()));
                    let result = loader(&snapshot, 1, false, Arc::clone(&disposed), observed)
                        .stage(snapshot)
                        .await;
                    let error = match result {
                        Ok(generation) => {
                            dispose_generation(generation).await;
                            panic!("negative case {} must fail", case["name"])
                        }
                        Err(error) => error,
                    };
                    assert!(
                        lock(&disposed).is_empty(),
                        "case {} must fail before apply",
                        case["name"]
                    );
                    error.code()
                }
            };
            assert_eq!(actual, expected, "negative case {}", case["name"]);
        }
    });
}

#[test]
fn loader_requires_manifest_catalog_and_runtime_contract_digests_to_match() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("snapshot fixture must parse");
        let disposed = Arc::new(Mutex::new(Vec::new()));
        let observed = Arc::new(Mutex::new(Vec::new()));

        let mut runtime_definitions = definitions(
            &snapshot,
            1,
            false,
            Arc::clone(&disposed),
            Arc::clone(&observed),
        );
        runtime_definitions[0].contract_digest = format!("sha256:{}", "0".repeat(64));
        let result = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            runtime_definitions,
            target_catalog_json(&snapshot, &DataPlaneTargetV2::RustServer),
        )
        .stage(snapshot.clone())
        .await;
        let error = match result {
            Ok(_) => panic!("runtime digest mismatch must fail"),
            Err(error) => error,
        };
        assert_eq!(error.code(), "contract_digest_mismatch");

        let mut catalog: Value = serde_json::from_str(&target_catalog_json(
            &snapshot,
            &DataPlaneTargetV2::RustServer,
        ))
        .expect("catalog fixture");
        catalog["modules"][0]["contract_digest"] =
            Value::String(format!("sha256:{}", "1".repeat(64)));
        refresh_catalog_digest(&mut catalog);
        let result = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            definitions(
                &snapshot,
                1,
                false,
                Arc::clone(&disposed),
                Arc::clone(&observed),
            ),
            catalog.to_string(),
        )
        .stage(snapshot.clone())
        .await;
        let error = match result {
            Ok(_) => panic!("catalog contract digest mismatch must fail"),
            Err(error) => error,
        };
        assert_eq!(error.code(), "contract_digest_mismatch");

        let mut source_mismatch: Value = serde_json::from_str(&target_catalog_json(
            &snapshot,
            &DataPlaneTargetV2::RustServer,
        ))
        .expect("catalog fixture");
        source_mismatch["modules"][0]["artifact_source"] =
            Value::String("package://unexpected/artifact".into());
        refresh_catalog_digest(&mut source_mismatch);
        let result = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            definitions(
                &snapshot,
                1,
                false,
                Arc::clone(&disposed),
                Arc::clone(&observed),
            ),
            source_mismatch.to_string(),
        )
        .stage(snapshot.clone())
        .await;
        let error = match result {
            Ok(_) => panic!("catalog artifact source mismatch must fail"),
            Err(error) => error,
        };
        assert_eq!(error.code(), "invalid_target_catalog");

        let mut corrupt_catalog: Value = serde_json::from_str(&target_catalog_json(
            &snapshot,
            &DataPlaneTargetV2::RustServer,
        ))
        .expect("catalog fixture");
        corrupt_catalog["catalog_digest"] = Value::String(format!("sha256:{}", "2".repeat(64)));
        let result = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            definitions(&snapshot, 1, false, Arc::clone(&disposed), observed),
            corrupt_catalog.to_string(),
        )
        .stage(snapshot)
        .await;
        let error = match result {
            Ok(_) => panic!("catalog document digest mismatch must fail"),
            Err(error) => error,
        };
        assert_eq!(error.code(), "catalog_digest_mismatch");
        assert!(
            lock(&disposed).is_empty(),
            "digest checks must precede apply"
        );
    });
}

#[test]
fn shared_runtime_completeness_cases_are_enforced_by_context() {
    block_on(async {
        let fixture: Value =
            serde_json::from_str(CONTRACT_CONFORMANCE).expect("contract fixture must parse");
        let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("snapshot fixture must parse");
        for case in fixture["runtime_completeness_cases"]
            .as_array()
            .expect("runtime completeness cases")
        {
            let module_ref = case["module_ref"].as_str().expect("module ref");
            let operation = case["operation"].as_str().expect("operation");
            let mut definitions = definitions(
                &snapshot,
                1,
                false,
                Arc::new(Mutex::new(Vec::new())),
                Arc::new(Mutex::new(Vec::new())),
            );
            let definition = definitions
                .iter_mut()
                .find(|definition| definition.module_ref == module_ref)
                .expect("probe definition");
            definition.module = Arc::new(CompletenessProbe {
                operation: operation.to_owned(),
                name: case["name"].as_str().expect("operation name").to_owned(),
                root: module_ref.ends_with("root-provider"),
            });
            let result = LoaderV2::for_target_with_catalog_json(
                DataPlaneTargetV2::RustServer,
                definitions,
                target_catalog_json(&snapshot, &DataPlaneTargetV2::RustServer),
            )
            .stage(snapshot.clone())
            .await;
            let error = match result {
                Ok(generation) => {
                    dispose_generation(generation).await;
                    panic!("runtime completeness case {} must fail", case["name"])
                }
                Err(error) => error,
            };
            assert_eq!(
                error.code(),
                case["expected_error"].as_str().expect("expected error"),
                "runtime completeness case {}",
                case["name"]
            );
        }
    });
}

#[test]
fn dispatch_uses_declared_emit_serial_bail_and_waterfall_modes() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("event snapshot must parse");
        let captured = Arc::new(Mutex::new(None));
        let generation = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            event_definitions(&snapshot, Arc::clone(&captured), false),
            target_catalog_json(&snapshot, &DataPlaneTargetV2::RustServer),
        )
        .stage(snapshot)
        .await
        .expect("event generation must stage");
        let context = lock(&captured).clone().expect("consumer context");

        assert_eq!(
            context
                .dispatch("notify", serde_json::json!({}))
                .await
                .expect("emit dispatch"),
            serde_json::json!([[3], [4]])
        );
        assert_eq!(
            context
                .dispatch("audit", serde_json::json!({}))
                .await
                .expect("serial dispatch"),
            serde_json::json!([[3], [4]])
        );
        assert_eq!(
            context
                .dispatch("choose", Value::Null)
                .await
                .expect("bail dispatch"),
            serde_json::json!("selected")
        );
        assert_eq!(
            context
                .dispatch("transform", serde_json::json!(2))
                .await
                .expect("waterfall dispatch"),
            serde_json::json!(6)
        );
        let error = context
            .dispatch("transform", serde_json::json!("not-an-integer"))
            .await
            .expect_err("invalid event payload must fail");
        assert_eq!(error.code(), "invalid_event_payload");
        dispose_generation(generation).await;
    });
}

#[test]
fn dispatch_validates_handler_results_against_the_public_contract() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("event snapshot must parse");
        let captured = Arc::new(Mutex::new(None));
        let generation = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            event_definitions(&snapshot, Arc::clone(&captured), true),
            target_catalog_json(&snapshot, &DataPlaneTargetV2::RustServer),
        )
        .stage(snapshot)
        .await
        .expect("event generation must stage");
        let context = lock(&captured).clone().expect("consumer context");

        let error = context
            .dispatch("choose", Value::Null)
            .await
            .expect_err("invalid event result must fail");
        assert_eq!(error.code(), "invalid_event_result");
        dispose_generation(generation).await;
    });
}

#[test]
fn same_scope_listeners_follow_profile_declaration_order() {
    block_on(async {
        let snapshot = ordered_sibling_snapshot("rust-server");
        let applied = Arc::new(Mutex::new(Vec::new()));
        let contexts = Arc::new(Mutex::new(Vec::new()));
        let definitions = [
            ("builtin://conformance/declared-first", "first"),
            ("builtin://conformance/declared-second", "second"),
        ]
        .map(|(module_ref, label)| PluginDefinitionV2 {
            module_ref: module_ref.to_owned(),
            contract_digest: module_contract_digest(&snapshot, module_ref),
            module: Arc::new(OrderedListener {
                label: label.to_owned(),
                applied: Arc::clone(&applied),
                contexts: Arc::clone(&contexts),
            }),
        });
        let generation = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::RustServer,
            definitions,
            target_catalog_json(&snapshot, &DataPlaneTargetV2::RustServer),
        )
        .stage(snapshot)
        .await
        .expect("ordered sibling generation must stage");

        assert_eq!(*lock(&applied), vec!["first", "second"]);
        let context = lock(&contexts)
            .first()
            .cloned()
            .expect("listener context must be captured");
        assert_eq!(
            context
                .dispatch("ordered", serde_json::json!({}))
                .await
                .expect("ordered event must dispatch"),
            serde_json::json!(["first", "second"])
        );
        dispose_generation(generation).await;
    });
}

#[test]
fn dependencies_activate_before_an_earlier_declared_consumer() {
    block_on(async {
        let mut raw: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
        raw["entries"]
            .as_array_mut()
            .expect("fixture entries")
            .reverse();
        refresh_snapshot_digest(&mut raw);
        let snapshot = parse_profile_snapshot_v2(&raw.to_string())
            .expect("reversed dependency snapshot must parse");
        let observed = Arc::new(Mutex::new(Vec::new()));
        let generation = loader(
            &snapshot,
            7,
            false,
            Arc::new(Mutex::new(Vec::new())),
            Arc::clone(&observed),
        )
        .stage(snapshot)
        .await
        .expect("dependency must activate before its consumer");

        assert_eq!(*lock(&observed), vec![7]);
        dispose_generation(generation).await;
    });
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
fn unknown_data_plane_target_is_rejected() {
    let mut changed: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    changed["manifests"][0]["modules"][0]["targets"][0] = Value::String("unknown-plane".into());

    assert!(matches!(
        parse_profile_snapshot_v2(&changed.to_string()),
        Err(PluginProtocolV2Error::InvalidShape(_))
    ));
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
fn distribution_validates_the_full_snapshot_before_target_projection() {
    let mut invalid: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    invalid["entries"][0]["plugin_ref"] = Value::String("missing-plugin".into());

    assert!(matches!(
        parse_control_plane_distribution_v2(&distribution(invalid, 11, "nonce-invalid")),
        Err(PluginProtocolV2Error::MissingManifest { .. })
    ));
}

#[test]
fn distribution_rejects_v1_and_mismatched_descriptor_or_envelope() {
    assert_eq!(
        parse_control_plane_distribution_v2(r#"{"schema_version":1}"#),
        Err(PluginProtocolV2Error::IncompatibleSchemaVersion)
    );

    let snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    let mut mismatched: Value = serde_json::from_str(&distribution(snapshot, 11, "nonce-mismatch"))
        .expect("distribution must parse");
    mismatched["envelope"]["snapshot_digest"] = Value::String("0".repeat(64));
    assert!(matches!(
        parse_control_plane_distribution_v2(&mismatched.to_string()),
        Err(PluginProtocolV2Error::DistributionMismatch(_))
    ));
}

#[test]
fn distribution_serialization_preserves_explicit_null_snapshot_fields() {
    let mut snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
    snapshot["manifests"][0]["modules"][0]["artifact"]["signature"] = Value::Null;
    let mut digest_payload = snapshot.clone();
    digest_payload
        .as_object_mut()
        .expect("snapshot object")
        .remove("digest");
    let canonical = serde_jcs::to_vec(&digest_payload).expect("snapshot must canonicalize");
    snapshot["digest"] = Value::String(format!("{:x}", Sha256::digest(canonical)));
    let parsed =
        parse_control_plane_distribution_v2(&distribution(snapshot, 12, "nonce-explicit-null"))
            .expect("distribution must parse");

    let persisted = serde_json::to_value(&parsed).expect("distribution must serialize");
    let artifact = persisted["snapshot"]["manifests"][0]["modules"][0]["artifact"]
        .as_object()
        .expect("artifact must remain an object");
    assert_eq!(artifact.get("signature"), Some(&Value::Null));
    let reparsed = parse_control_plane_distribution_v2(&persisted.to_string())
        .expect("serialized distribution must reparse");
    assert_eq!(reparsed, parsed);
}

#[test]
fn desktop_reconciler_acks_only_its_empty_target_projection() {
    block_on(async {
        let snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
        let distribution =
            parse_control_plane_distribution_v2(&distribution(snapshot, 11, "nonce-desktop"))
                .expect("distribution must parse");
        let mut reconciler = PluginSnapshotReconcilerV2::new(LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            std::iter::empty::<PluginDefinitionV2>(),
        ));

        let receipt = reconciler.apply(&distribution).await;

        assert_eq!(receipt.status, ApplyStatusV2::Ack);
        assert_eq!(receipt.applied_version, Some(11));
        assert_eq!(
            receipt.applied_digest,
            Some(distribution.snapshot.digest.clone())
        );
        let lease = reconciler
            .manager()
            .acquire()
            .expect("generation must publish");
        assert!(lease
            .generation()
            .expect("generation must remain active")
            .phases()
            .is_empty());
        lease.release().await.expect("lease must release");
        reconciler.close().await;
    });
}

#[test]
fn desktop_reconciler_activates_non_empty_catalog_and_nacks_missing_definition() {
    block_on(async {
        let snapshot = snapshot_with_target("desktop-sidecar");
        let distribution =
            parse_control_plane_distribution_v2(&distribution(snapshot, 11, "nonce-desktop"))
                .expect("distribution must parse");
        let disposed = Arc::new(Mutex::new(Vec::new()));
        let observed = Arc::new(Mutex::new(Vec::new()));
        let loader = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::DesktopSidecar,
            definitions(
                &distribution.snapshot,
                42,
                false,
                Arc::clone(&disposed),
                Arc::clone(&observed),
            ),
            target_catalog_json(&distribution.snapshot, &DataPlaneTargetV2::DesktopSidecar),
        );
        let mut reconciler = PluginSnapshotReconcilerV2::new(loader);

        let receipt = reconciler.apply(&distribution).await;

        assert_eq!(receipt.status, ApplyStatusV2::Ack);
        assert_eq!(*lock(&observed), vec![42]);
        let lease = reconciler
            .manager()
            .acquire()
            .expect("generation must publish");
        assert_eq!(
            lease
                .generation()
                .expect("generation must remain active")
                .phases()
                .len(),
            2
        );
        lease.release().await.expect("lease must release");
        reconciler.close().await;

        let mut missing = PluginSnapshotReconcilerV2::new(LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::DesktopSidecar,
            std::iter::empty::<PluginDefinitionV2>(),
            target_catalog_json(&distribution.snapshot, &DataPlaneTargetV2::DesktopSidecar),
        ));
        let receipt = missing.apply(&distribution).await;
        assert_eq!(receipt.status, ApplyStatusV2::Nack);
        assert_eq!(
            receipt.error_code.as_deref(),
            Some("generation_apply_failed")
        );
        assert!(receipt
            .error_message
            .as_deref()
            .is_some_and(|message| message.contains("is unavailable")));
        assert!(missing.manager().acquire().is_err());
        missing.close().await;
    });
}

#[test]
fn reconciler_nacks_stale_versions_and_retains_last_good() {
    block_on(async {
        let snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
        let first =
            parse_control_plane_distribution_v2(&distribution(snapshot.clone(), 11, "nonce-11"))
                .expect("first distribution must parse");
        let stale = parse_control_plane_distribution_v2(&distribution(snapshot, 10, "nonce-10"))
            .expect("stale distribution must parse");
        let mut reconciler = PluginSnapshotReconcilerV2::new(LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            std::iter::empty::<PluginDefinitionV2>(),
        ));

        assert_eq!(reconciler.apply(&first).await.status, ApplyStatusV2::Ack);
        let receipt = reconciler.apply(&stale).await;

        assert_eq!(receipt.status, ApplyStatusV2::Nack);
        assert_eq!(receipt.error_code.as_deref(), Some("stale_version"));
        assert_eq!(receipt.applied_version, Some(11));
        assert_eq!(receipt.applied_digest, Some(first.snapshot.digest.clone()));
        reconciler.close().await;
    });
}

#[test]
fn reconciler_exposes_one_shared_generation_manager_handle() {
    let reconciler = PluginSnapshotReconcilerV2::new(LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        std::iter::empty::<PluginDefinitionV2>(),
    ));

    let first = reconciler.manager();
    let second = reconciler.manager();

    assert!(Arc::ptr_eq(&first, &second));
}

#[test]
fn loader_resolves_inject_and_disposes_effects_in_lifo_order() {
    block_on(async {
        let snapshot = parse_profile_snapshot_v2(SNAPSHOT).expect("fixture must parse");
        let disposed = Arc::new(Mutex::new(Vec::new()));
        let observed = Arc::new(Mutex::new(Vec::new()));
        let generation = loader(
            &snapshot,
            7,
            false,
            Arc::clone(&disposed),
            Arc::clone(&observed),
        )
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
        let result = loader(&snapshot, 1, true, Arc::clone(&disposed), observed)
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
            &first_snapshot,
            1,
            false,
            Arc::clone(&first_disposed),
            Arc::new(Mutex::new(Vec::new())),
        )
        .stage(first_snapshot)
        .await
        .expect("first generation must stage");
        let second = loader(
            &second_snapshot,
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
