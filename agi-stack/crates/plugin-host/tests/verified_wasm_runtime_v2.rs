#![cfg(all(feature = "external-wasm-v2", not(target_arch = "wasm32")))]

#[path = "support/signed_wasm_runtime.rs"]
mod fixture;
use agistack_plugin_host::protocol_v2::wasm_runtime::{
    WasmOperationAuthorityV2, WasmOperationV2, WasmToolAttributionV2, WasmToolSetV2,
    WASM_TOOL_SET_SERVICE_V2,
};
use agistack_plugin_host::{
    DataPlaneTargetV2, GenerationManagerV2, LoaderV2, ScopeKindV2, ScopeV2,
};
use async_trait::async_trait;
use futures::executor::block_on;
use serde_json::json;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

const MARKER: &str =
    "(module (func (export \"score\") (param i32) (result i32) i32.const 20260914))";
const LENGTH: &str = "(module (func (export \"score\") (param i32) (result i32) local.get 0))";
fn scope() -> ScopeV2 {
    ScopeV2 {
        kind: ScopeKindV2::Session,
        tenant_id: Some("tenant".into()),
        project_id: Some("project".into()),
        session_id: Some("session".into()),
    }
}

struct Authority(AtomicBool);
#[async_trait]
impl WasmOperationAuthorityV2 for Authority {
    async fn authorize(&self, operation: &WasmOperationV2, tool: &WasmToolAttributionV2) -> bool {
        self.0.load(Ordering::Acquire)
            && operation.scope() == &scope()
            && tool.bundle.bundle_id == "qa-marketplace-marker-bundle"
            && tool.plugin_id == "qa-marketplace-marker"
            && tool.entry_id == "qa-marketplace-marker"
    }
}

#[test]
fn real_signed_archive_factory_requires_authority_and_revokes_retained_tool_callbacks() {
    block_on(async {
        let (archive, snapshot) = fixture::signed_fixture(MARKER, |_| {});
        let generation = LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, [])
            .with_verified_archives(vec![archive])
            .stage(snapshot)
            .await
            .unwrap();
        let manager = GenerationManagerV2::new();
        manager.publish(Arc::clone(&generation)).await;
        let set = generation
            .resolve::<WasmToolSetV2>(WASM_TOOL_SET_SERVICE_V2, &scope(), None)
            .unwrap();
        let no_auth = Arc::new(WasmOperationV2::new(
            manager.acquire().unwrap(),
            scope(),
            "no-auth".into(),
            None,
        ));
        assert!(set.prepare(&no_auth).await.is_empty());
        no_auth.close().await.unwrap();
        let authority = Arc::new(Authority(AtomicBool::new(true)));
        let operation = Arc::new(WasmOperationV2::new(
            manager.acquire().unwrap(),
            scope(),
            "operation".into(),
            Some(authority.clone()),
        ));
        let tools = set.prepare(&operation).await;
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0].definition().name, "qa_marketplace_marker");
        assert_eq!(
            tools[0].attribution().bundle.bundle_id,
            "qa-marketplace-marker-bundle"
        );
        assert_eq!(
            tools[0].invoke(json!({"input":"中"})).await.unwrap(),
            json!({"score":20260914,"input_bytes":15})
        );
        authority.0.store(false, Ordering::Release);
        assert!(tools[0].invoke(json!({"input":"denied"})).await.is_err());
        assert!(set.prepare(&operation).await.is_empty());
        authority.0.store(true, Ordering::Release);
        manager.close().await;
        operation.close().await.unwrap();
        assert!(tools[0].invoke(json!({"input":"disposed"})).await.is_err());
        assert!(set.prepare(&operation).await.is_empty());
    });
}

#[test]
fn score_v1_counts_serialized_json_utf8_bytes_with_unicode_and_escaping() {
    block_on(async {
        let (archive, snapshot) = fixture::signed_fixture(LENGTH, |_| {});
        let generation = LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, [])
            .with_verified_archives(vec![archive])
            .stage(snapshot)
            .await
            .unwrap();
        let manager = GenerationManagerV2::new();
        manager.publish(Arc::clone(&generation)).await;
        let set = generation
            .resolve::<WasmToolSetV2>(WASM_TOOL_SET_SERVICE_V2, &scope(), None)
            .unwrap();
        let operation = Arc::new(WasmOperationV2::new(
            manager.acquire().unwrap(),
            scope(),
            "abi".into(),
            Some(Arc::new(Authority(AtomicBool::new(true)))),
        ));
        let tools = set.prepare(&operation).await;
        for text in ["", "中", "a\"\n\\", "\u{20000}"] {
            let input = json!({"input":text});
            let bytes = serde_json::to_vec(&input).unwrap().len();
            assert_eq!(
                tools[0].invoke(input).await.unwrap(),
                json!({"score":bytes,"input_bytes":bytes})
            );
        }
        assert!(tools[0].invoke(json!({"text":"legacy"})).await.is_err());
        operation.close().await.unwrap();
        manager.close().await;
    });
}

#[test]
fn real_factory_rejects_host_imports_and_wrong_export_before_activation() {
    block_on(async {
        for wat in ["(module (import \"env\" \"host\" (func)) (func (export \"score\") (param i32) (result i32) i32.const 1))",
            "(module (func (export \"score\") (param i64) (result i32) i32.const 1))"] {
            let (archive, snapshot) = fixture::signed_fixture(wat, |_| {});
            assert!(LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, []).with_verified_archives(vec![archive]).stage(snapshot).await.is_err());
        }
    });
}

#[test]
fn unsigned_snapshot_replacement_and_missing_archive_cannot_inject_executable_code() {
    block_on(async {
        let (archive, mut snapshot) = fixture::signed_fixture(MARKER, |_| {});
        assert!(LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, [])
            .stage(snapshot.clone())
            .await
            .is_err());
        snapshot.manifests[0].version = "9.0.0".into();
        assert!(LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, [])
            .with_verified_archives(vec![archive])
            .stage(snapshot)
            .await
            .is_err());
    });
}

#[test]
fn signed_infinite_guest_and_memory_growth_are_bounded_and_do_not_poison_the_generation() {
    block_on(async {
        for wat in [
            "(module (func (export \"score\") (param i32) (result i32) (loop $forever br $forever) i32.const 0))",
            "(module (memory 1) (func (export \"score\") (param i32) (result i32) i32.const 2 memory.grow))",
        ] {
            let (archive, snapshot) = fixture::signed_fixture(wat, |bundle| {
                bundle["manifests"][0]["quotas"]["max_wall_time_ms"] = 10.into();
            });
            let generation = LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, []).with_verified_archives(vec![archive]).stage(snapshot).await.unwrap();
            let manager = GenerationManagerV2::new(); manager.publish(Arc::clone(&generation)).await;
            let set = generation.resolve::<WasmToolSetV2>(WASM_TOOL_SET_SERVICE_V2, &scope(), None).unwrap();
            let operation = Arc::new(WasmOperationV2::new(manager.acquire().unwrap(), scope(), "quotas".into(), Some(Arc::new(Authority(AtomicBool::new(true))))));
            let tools = set.prepare(&operation).await;
            let started = std::time::Instant::now();
            for _ in 0..2 { assert!(tools[0].invoke(json!({"input":"bounded"})).await.is_err()); }
            assert!(started.elapsed() < std::time::Duration::from_secs(2));
            operation.close().await.unwrap(); manager.close().await;
        }
    });
}

#[test]
fn missing_entry_permission_and_duplicate_archive_ownership_are_rejected() {
    block_on(async {
        let (archive, mut snapshot) = fixture::signed_fixture(MARKER, |_| {});
        assert!(LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, [])
            .with_verified_archives(vec![archive.clone(), archive.clone()])
            .stage(snapshot.clone())
            .await
            .is_err());
        snapshot.entries[0].permissions.clear();
        assert!(LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, [])
            .with_verified_archives(vec![archive])
            .stage(snapshot)
            .await
            .is_err());
    });
}

#[test]
fn custom_catalog_override_cannot_be_combined_with_verified_external_archives() {
    block_on(async {
        let (archive, snapshot) = fixture::signed_fixture(MARKER, |_| {});
        let loader = LoaderV2::for_target_with_catalog_json(
            DataPlaneTargetV2::DesktopSidecar,
            [],
            agistack_plugin_host::protocol_v2::PLUGIN_MODULE_CATALOG_V2_JSON,
        )
        .with_verified_archives(vec![archive]);
        assert!(loader.stage(snapshot).await.is_err());
    });
}
