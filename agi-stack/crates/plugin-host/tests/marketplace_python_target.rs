use agistack_plugin_host::{
    parse_control_plane_distribution_v2, project_snapshot_entries_v2, ApplyStatusV2,
    DataPlaneTargetV2, LoaderV2, PluginDefinitionV2, PluginSnapshotReconcilerV2,
};
use futures::executor::block_on;
use serde_json::Value;
use sha2::{Digest, Sha256};

const FIXTURE: &str =
    include_str!("../../../../shared/fixtures/marketplace-python-wasm-distribution.v2.json");

fn refresh_digest(payload: &mut Value) {
    let mut snapshot = payload["snapshot"].clone();
    snapshot
        .as_object_mut()
        .expect("snapshot object")
        .remove("digest");
    let canonical = serde_jcs::to_vec(&snapshot).expect("canonical JSON");
    let digest = format!("{:x}", Sha256::digest(canonical));
    payload["snapshot"]["digest"] = digest.clone().into();
    payload["descriptor"]["digest"] = digest.clone().into();
    payload["envelope"]["snapshot_digest"] = digest.into();
}

#[test]
fn signed_python_package_is_retained_but_not_executed_by_sidecar() {
    block_on(async {
        let value: Value = serde_json::from_str(FIXTURE).expect("signed fixture projection");
        let distribution =
            parse_control_plane_distribution_v2(&value.to_string()).expect("valid protocol");
        assert_eq!(distribution.snapshot.manifests.len(), 1);
        assert_eq!(distribution.snapshot.entries.len(), 1);
        assert_eq!(
            distribution.snapshot.manifests[0].modules[0].targets,
            vec![DataPlaneTargetV2::Python]
        );
        assert!(project_snapshot_entries_v2(
            &distribution.snapshot,
            &DataPlaneTargetV2::DesktopSidecar
        )
        .is_empty());
        let mut reconciler = PluginSnapshotReconcilerV2::new(LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            std::iter::empty::<PluginDefinitionV2>(),
        ));
        let receipt = reconciler.apply(&distribution).await;
        assert_eq!(receipt.status, ApplyStatusV2::Ack);
        assert_eq!(receipt.applied_digest, Some(distribution.snapshot.digest));
        assert_eq!(receipt.applied_version, Some(distribution.envelope.version));
        reconciler.close().await;
    });
}

#[test]
fn sidecar_target_injection_is_rejected_by_the_real_generated_catalog() {
    block_on(async {
        let mut value: Value = serde_json::from_str(FIXTURE).expect("fixture JSON");
        value["snapshot"]["manifests"][0]["modules"][0]["targets"] =
            serde_json::json!(["desktop-sidecar"]);
        refresh_digest(&mut value);
        let distribution =
            parse_control_plane_distribution_v2(&value.to_string()).expect("valid protocol");
        let loader = LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            std::iter::empty::<PluginDefinitionV2>(),
        );
        let rejected = loader.stage(distribution.snapshot.clone()).await;
        assert!(matches!(rejected, Err(ref error) if error.code() == "missing_target_catalog"));
        let mut reconciler = PluginSnapshotReconcilerV2::new(LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            std::iter::empty::<PluginDefinitionV2>(),
        ));
        let receipt = reconciler.apply(&distribution).await;
        assert_eq!(receipt.status, ApplyStatusV2::Nack);
        assert_eq!(
            receipt.error_code.as_deref(),
            Some("generation_apply_failed")
        );
        reconciler.close().await;
    });
}

#[test]
fn ignored_python_modules_still_require_valid_protocol_and_digest() {
    let mut value: Value = serde_json::from_str(FIXTURE).expect("fixture JSON");
    value["snapshot"]["manifests"][0]["modules"][0]["artifact"]["digest"] = "0".repeat(64).into();
    assert!(parse_control_plane_distribution_v2(&value.to_string()).is_err());
    value["snapshot"]["manifests"][0]["modules"][0]["targets"] =
        serde_json::json!(["unregistered-plane"]);
    refresh_digest(&mut value);
    assert!(parse_control_plane_distribution_v2(&value.to_string()).is_err());
}
