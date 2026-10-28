use super::*;
use crate::local_runtime::{browser_bridge, tests::test_state, LocalRuntimeService};
use serde_json::json;
use std::{path::PathBuf, sync::Arc};

fn patch(value: serde_json::Value) -> LocalRuntimeConfigPatch {
    serde_json::from_value(value).expect("valid runtime config patch")
}

#[test]
fn absent_fields_preserve_current_settings_and_explicit_objects_replace_them() {
    let current = LocalRuntimeConfig {
        workspace_root: "/test/workspace".into(),
        browser_bridge: browser_bridge::BrowserBridgeConfig {
            enabled: true,
            port: 9876,
            full_cdp_access_enabled: true,
            ..Default::default()
        },
    };
    let unchanged = patch(json!({})).apply_to(current.clone());
    assert_eq!(unchanged.workspace_root, current.workspace_root);
    assert_eq!(unchanged.browser_bridge, current.browser_bridge);
    let disabled = patch(json!({"browser_bridge": {"enabled": false}})).apply_to(current);
    assert_eq!(disabled.workspace_root, "/test/workspace");
    assert_eq!(disabled.browser_bridge, Default::default());
    for value in [
        json!(null),
        json!({"workspace_root": null}),
        json!({"browser_bridge": null}),
        json!({"workspace_root": 1}),
        json!({"browser_bridge": false}),
        json!({"unknown": true}),
        json!({"browser_bridge": {"unknown": true}}),
    ] {
        assert!(serde_json::from_value::<LocalRuntimeConfigPatch>(value).is_err());
    }
}

struct Fixture {
    root: PathBuf,
    runtime: LocalRuntimeService,
}

impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "cp-{}",
            &uuid::Uuid::new_v4().simple().to_string()[..8]
        ));
        std::fs::create_dir_all(&root).unwrap();
        let state = test_state("runtime-config-patch-test");
        let runtime = LocalRuntimeService {
            state,
            api_base_url: "http://127.0.0.1:1".into(),
        };
        Self { root, runtime }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.runtime.state.stop_browser_bridge();
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[tokio::test]
async fn workspace_only_sync_preserves_the_live_bridge_and_explicit_false_stops_it() {
    let fixture = Fixture::new();
    let registry = fixture.root.join(".memstack/browser-bridge/registry.json");
    let config = browser_bridge::BrowserBridgeConfig {
        enabled: true,
        port: 0,
        full_cdp_access_enabled: true,
        ..Default::default()
    };
    let bridge = browser_bridge::BrowserBridgeRuntime::start_with_registry_path(
        &config,
        registry.clone(),
        None,
    )
    .unwrap();
    let server = bridge.server();
    let port = bridge.port();
    let original_registry = std::fs::read(&registry).unwrap();
    *fixture.runtime.state.browser_bridge.lock().unwrap() = Some(bridge);
    *fixture.runtime.state.config.lock().unwrap() = LocalRuntimeConfig {
        workspace_root: fixture.root.join("original").to_string_lossy().into_owned(),
        browser_bridge: config.clone(),
    };

    let workspace = fixture.root.join("selected-workspace");
    let status = fixture
        .runtime
        .configure(patch(json!({"workspace_root": workspace})))
        .unwrap();
    assert_eq!(status.config.browser_bridge, config);
    assert!(status.browser_bridge.enabled);
    assert_eq!(status.browser_bridge.port, port);
    assert_eq!(std::fs::read(&registry).unwrap(), original_registry);
    assert!(Arc::ptr_eq(
        &server,
        &fixture
            .runtime
            .state
            .browser_bridge
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .server()
    ));
    tokio::net::TcpStream::connect((std::net::Ipv4Addr::LOCALHOST, port))
        .await
        .expect("existing bridge listener survives workspace sync");

    let replacement = browser_bridge::BrowserBridgeConfig {
        enabled: false,
        port: 9877,
        full_cdp_access_enabled: false,
        extension_ids: vec!["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into()],
    };
    let status = fixture
        .runtime
        .configure(patch(json!({"browser_bridge": replacement})))
        .unwrap();
    assert_eq!(status.config.browser_bridge, replacement);
    assert_eq!(
        status.workspace_root,
        workspace.canonicalize().unwrap().to_string_lossy()
    );
    assert!(!status.browser_bridge.enabled);
    assert!(fixture
        .runtime
        .state
        .browser_bridge
        .lock()
        .unwrap()
        .is_none());
    assert!(!registry.exists());
}

#[test]
fn concurrent_partial_updates_keep_both_workspace_and_explicit_bridge_changes() {
    let fixture = Fixture::new();
    let workspace = fixture.root.join("concurrent-workspace");
    let barrier = Arc::new(std::sync::Barrier::new(2));
    std::thread::scope(|scope| {
        let runtime = &fixture.runtime;
        let gate = Arc::clone(&barrier);
        let target = workspace.clone();
        scope.spawn(move || {
            gate.wait();
            runtime
                .configure(patch(json!({"workspace_root": target})))
                .unwrap();
        });
        scope.spawn(|| {
            barrier.wait();
            fixture
                .runtime
                .configure(patch(json!({"browser_bridge": {
                    "enabled": false, "port": 9988, "full_cdp_access_enabled": true
                }})))
                .unwrap();
        });
    });
    let status = fixture.runtime.status();
    assert_eq!(
        status.config.workspace_root,
        workspace.canonicalize().unwrap().to_string_lossy()
    );
    assert_eq!(status.config.browser_bridge.port, 9988);
    assert!(status.config.browser_bridge.full_cdp_access_enabled);
    assert!(!status.config.browser_bridge.enabled);
}
