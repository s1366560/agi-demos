use super::*;
use crate::{
    application_vault::ApplicationCredentialVault,
    local_runtime::{tests::test_state, LocalRuntimeConfigPatch, LocalRuntimeService},
};
use serde_json::json;
use std::sync::Arc;

struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let root =
            std::env::temp_dir().join(format!("browser-preferences-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        Self(root)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn preferences() -> BrowserBridgeConfig {
    BrowserBridgeConfig {
        cdp_endpoints: vec![super::super::browser_cdp::CdpEndpointConfig {
            id: "23344bba-c174-42a5-a14d-0534978df6c2".into(),
            name: "Owned fixture".into(),
            endpoint: "http://127.0.0.1:58608".into(),
            enabled: true,
        }],
        default_browser_id: "cdp:23344bba-c174-42a5-a14d-0534978df6c2".into(),
        ..Default::default()
    }
}
#[test]
fn validated_private_preferences_round_trip_and_uncommitted_values_do_not_replace_them() {
    let directory = Directory::new();
    assert_eq!(load(&directory.0).unwrap(), BrowserBridgeConfig::default());
    let mut expected = preferences();
    expected.enabled = true;
    expected.full_cdp_access_enabled = true;
    Prepared::new(&directory.0, &expected)
        .unwrap()
        .commit()
        .unwrap();
    let restored = durable_preferences(&expected);
    assert_eq!(load(&directory.0).unwrap(), restored);
    drop(Prepared::new(&directory.0, &BrowserBridgeConfig::default()).unwrap());
    assert_eq!(load(&directory.0).unwrap(), restored);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(directory.0.join(FILE))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }
    let mut invalid = expected.clone();
    invalid.cdp_endpoints[0].endpoint = "http://remote.example.test".into();
    assert!(Prepared::new(&directory.0, &invalid).is_err());
    assert_eq!(load(&directory.0).unwrap(), restored);
}
#[test]
fn malformed_or_invalid_saved_preferences_are_never_silently_enabled() {
    let directory = Directory::new();
    for raw in ["{".to_string(), json!({"version":2,"browser_bridge":preferences()}).to_string(),
        json!({"version":1,"browser_bridge":{"enabled":true,"default_browser_id":"old:generation"}}).to_string()] {
        fs::write(directory.0.join(FILE), raw).unwrap();
        assert!(load(&directory.0).is_err());
    }
}
#[tokio::test]
async fn configured_endpoints_and_default_survive_a_fresh_application_runtime() {
    const CHILD_ROOT: &str = "AGISTACK_BROWSER_PREFERENCES_TEST_CHILD_ROOT";
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        let root = PathBuf::from(root);
        let app_data = root.join("application");
        let vault = ApplicationCredentialVault::open(&app_data).unwrap();
        let first = LocalRuntimeService::start(app_data, root.join("workspace"), vault, None)
            .await
            .unwrap();
        let expected = preferences();
        let patch: LocalRuntimeConfigPatch =
            serde_json::from_value(json!({"browser_bridge":expected})).unwrap();
        assert_eq!(
            first.configure(patch).unwrap().config.browser_bridge,
            expected
        );
        first.shutdown().await;
        return;
    }
    let directory = Directory::new();
    let app_data = directory.0.join("application");
    // The database deliberately admits one runtime owner per process. A new
    // test process models full application exit and releases that owner lease.
    let saved = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "local_runtime::browser_preferences::tests::configured_endpoints_and_default_survive_a_fresh_application_runtime", "--nocapture"])
        .env(CHILD_ROOT, &directory.0).output().unwrap();
    assert!(
        saved.status.success(),
        "{}",
        String::from_utf8_lossy(&saved.stderr)
    );
    let expected = preferences();
    let second_workspace = directory.0.join("next-workspace");
    let reopened_vault = ApplicationCredentialVault::open(&app_data).unwrap();
    let second =
        LocalRuntimeService::start(app_data, second_workspace.clone(), reopened_vault, None)
            .await
            .unwrap();
    let status = second.status();
    assert_eq!(status.config.browser_bridge, expected);
    assert_eq!(status.workspace_root, second_workspace.to_string_lossy());
    assert!(
        status.browser_bridge.browser_instances.is_empty(),
        "no connection identity or lease is persisted"
    );
    second.shutdown().await;
}
#[test]
fn failed_preference_save_does_not_acknowledge_or_apply_a_configuration_change() {
    let directory = Directory::new();
    let mut state = test_state("browser-preferences-write-failure");
    let blocked = directory.0.join("not-a-directory");
    fs::write(&blocked, b"fixture").unwrap();
    Arc::get_mut(&mut state).unwrap().app_data_dir = Some(blocked);
    let runtime = LocalRuntimeService {
        state,
        api_base_url: "http://127.0.0.1:1".into(),
    };
    let workspace = directory.0.join("must-not-be-created");
    let patch: LocalRuntimeConfigPatch =
        serde_json::from_value(json!({"workspace_root":workspace,"browser_bridge":preferences()}))
            .unwrap();
    assert!(runtime.configure(patch).is_err());
    assert_eq!(
        runtime.status().config.browser_bridge,
        BrowserBridgeConfig::default()
    );
    assert!(!workspace.exists());
}
