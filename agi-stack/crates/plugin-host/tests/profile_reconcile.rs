use std::cell::RefCell;
use std::rc::Rc;

use agistack_plugin_host::profile_reconcile::{
    PlatformPluginActivator, PlatformPluginEnvelope, PlatformPluginSnapshotReconciler,
    PluginActivation, PLUGIN_APPLY_STATUS_ACK, PLUGIN_APPLY_STATUS_NACK,
};
use agistack_plugin_host::{
    PlatformPluginSnapshot, SnapshotPlugin, PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL,
};
use serde_json::{Map, Value};

#[derive(Clone, Default)]
struct RecordingActivator {
    committed: Rc<RefCell<Vec<String>>>,
    deactivated: Rc<RefCell<Vec<String>>>,
}

impl PlatformPluginActivator for RecordingActivator {
    fn prepare(&self, plugin: &SnapshotPlugin) -> Result<PluginActivation, String> {
        if plugin.id == "broken" {
            return Err("host cannot activate plugin".to_string());
        }
        let committed = self.committed.clone();
        let plugin_id = plugin.id.clone();
        Ok(PluginActivation::new(
            plugin.id.clone(),
            Box::new(move || committed.borrow_mut().push(plugin_id)),
        ))
    }

    fn deactivate(&self, plugin_id: &str) {
        self.deactivated.borrow_mut().push(plugin_id.to_string());
    }
}

fn snapshot(profile_id: &str, digest: &str, plugin_id: &str) -> PlatformPluginSnapshot {
    let mut activation = Map::new();
    activation.insert(
        "default_scope".to_string(),
        Value::String("tenant".to_string()),
    );
    activation.insert(
        "restart_policy".to_string(),
        Value::String("process-boundary".to_string()),
    );
    let plugin = SnapshotPlugin {
        schema_version: 1,
        id: plugin_id.to_string(),
        version: "1.0.0".to_string(),
        runtime: "python-trusted".to_string(),
        trust: "builtin".to_string(),
        requires: Vec::new(),
        provides: Vec::new(),
        activation: serde_json::from_value(Value::Object(activation)).unwrap(),
        config: Map::new(),
        layer_id: "test-layer".to_string(),
    };
    PlatformPluginSnapshot {
        schema_version: 1,
        profile_id: profile_id.to_string(),
        plugins: vec![plugin],
        digest: digest.to_string(),
    }
}

fn envelope(version: u64, digest: &str) -> PlatformPluginEnvelope {
    PlatformPluginEnvelope {
        version,
        nonce: format!("nonce-{version}"),
        snapshot_digest: digest.to_string(),
        type_url: PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL.to_string(),
    }
}

#[test]
fn accepts_valid_profile_and_keeps_last_good() {
    let activator = RecordingActivator::default();
    let mut reconciler = PlatformPluginSnapshotReconciler::new(activator.clone());
    let snapshot = snapshot("test", &"a".repeat(64), "workspace-runtime");

    let receipt = reconciler.reconcile(&envelope(2, &snapshot.digest), &snapshot);

    assert_eq!(receipt.status, PLUGIN_APPLY_STATUS_ACK);
    assert_eq!(receipt.activated, vec!["workspace-runtime".to_string()]);
    assert_eq!(reconciler.applied_version(), 2);
    assert_eq!(reconciler.last_good().unwrap().digest, snapshot.digest);
    assert_eq!(
        activator.committed.borrow().as_slice(),
        ["workspace-runtime"]
    );
}

#[test]
fn duplicate_version_with_different_digest_is_rejected() {
    let mut reconciler = PlatformPluginSnapshotReconciler::new(RecordingActivator::default());
    let first = snapshot("test", &"a".repeat(64), "plugin-a");
    reconciler.reconcile(&envelope(3, &first.digest), &first);
    let second = snapshot("test", &"b".repeat(64), "plugin-b");

    let receipt = reconciler.reconcile(&envelope(3, &second.digest), &second);

    assert_eq!(receipt.status, PLUGIN_APPLY_STATUS_NACK);
    assert_eq!(reconciler.applied_digest(), Some(first.digest.as_str()));
}

#[test]
fn preparation_failure_is_nack_and_retains_last_good() {
    let mut reconciler = PlatformPluginSnapshotReconciler::new(RecordingActivator::default());
    let bad = snapshot("test", &"c".repeat(64), "broken");

    let receipt = reconciler.reconcile(&envelope(4, &bad.digest), &bad);

    assert_eq!(receipt.status, PLUGIN_APPLY_STATUS_NACK);
    assert_eq!(reconciler.applied_version(), 0);
    assert!(reconciler.last_good().is_none());
}

#[test]
fn same_version_and_digest_is_idempotent_ack() {
    let activator = RecordingActivator::default();
    let mut reconciler = PlatformPluginSnapshotReconciler::new(activator.clone());
    let snapshot = snapshot("test", &"d".repeat(64), "plugin-a");
    reconciler.reconcile(&envelope(5, &snapshot.digest), &snapshot);

    let receipt = reconciler.reconcile(&envelope(5, &snapshot.digest), &snapshot);

    assert_eq!(receipt.status, PLUGIN_APPLY_STATUS_ACK);
    assert!(receipt.activated.is_empty());
    assert_eq!(activator.committed.borrow().len(), 1);
}

#[test]
fn stale_version_is_nacked() {
    let mut reconciler = PlatformPluginSnapshotReconciler::new(RecordingActivator::default());
    let first = snapshot("test", &"e".repeat(64), "plugin-a");
    reconciler.reconcile(&envelope(6, &first.digest), &first);
    let stale = snapshot("test", &"f".repeat(64), "plugin-b");

    let receipt = reconciler.reconcile(&envelope(5, &stale.digest), &stale);

    assert_eq!(receipt.status, PLUGIN_APPLY_STATUS_NACK);
    assert_eq!(receipt.applied_version, 6);
    assert!(receipt
        .error
        .unwrap()
        .contains("stale plugin profile version"));
}

#[test]
fn removing_plugin_deactivates_only_the_missing_owner() {
    let activator = RecordingActivator::default();
    let mut reconciler = PlatformPluginSnapshotReconciler::new(activator.clone());
    let first = snapshot("test", &"a".repeat(64), "plugin-a");
    reconciler.reconcile(&envelope(7, &first.digest), &first);
    let second = snapshot("test", &"b".repeat(64), "plugin-b");

    let receipt = reconciler.reconcile(&envelope(8, &second.digest), &second);

    assert_eq!(receipt.status, PLUGIN_APPLY_STATUS_ACK);
    assert_eq!(
        activator.deactivated.borrow().as_slice(),
        ["plugin-a".to_string()]
    );
    assert_eq!(receipt.activated, vec!["plugin-b".to_string()]);
}
