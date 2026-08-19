use agistack_plugin_host::PlatformPluginSnapshot;

const SNAPSHOT: &str = r#"{
  "schema_version": 1,
  "profile_id": "memstack-default",
  "plugins": [
    {
      "schema_version": 1,
      "id": "workspace-runtime",
      "version": "1.0.0",
      "runtime": "python-trusted",
      "trust": "builtin",
      "requires": [],
      "provides": [
        {
          "kind": "hook",
          "id": "before_response",
          "contract": "hook:before_response",
          "config_schema": {},
          "permissions": []
        }
      ],
      "activation": {
        "default_scope": "tenant",
        "restart_policy": "process-boundary"
      },
      "config": {},
      "layer_id": "memstack.kernel-base"
    }
  ],
  "digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}"#;

#[test]
fn parses_python_profile_snapshot() {
    let snapshot = PlatformPluginSnapshot::parse(SNAPSHOT).unwrap();
    assert_eq!(snapshot.profile_id, "memstack-default");
    assert_eq!(snapshot.plugins.len(), 1);
    assert_eq!(
        snapshot.plugins[0].provides[0].contract,
        "hook:before_response"
    );
}

#[test]
fn rejects_untrusted_in_process_plugin() {
    let raw = SNAPSHOT.replace("\"trust\": \"builtin\"", "\"trust\": \"untrusted\"");
    let error = PlatformPluginSnapshot::parse(&raw).unwrap_err();
    assert!(error.to_string().contains("python-trusted"));
}

#[test]
fn parses_shared_python_golden_fixture() {
    // Cross-runtime contract: this file is emitted by the Python control plane
    // (`uv run python scripts/dump_plugin_profile.py --format json`) and guarded
    // on the Python side by test_platform_plugin_profile_contract.py.
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../shared/fixtures/platform-plugin-profile.v1.json"
    );
    let raw = std::fs::read_to_string(path).expect("shared golden fixture must exist");
    let snapshot = PlatformPluginSnapshot::parse(&raw).unwrap();
    assert_eq!(snapshot.schema_version, 1);
    assert_eq!(snapshot.profile_id, "memstack-default");
    assert!(snapshot.plugins.len() >= 2);
    assert!(snapshot
        .plugins
        .iter()
        .any(|plugin| plugin.id == "workspace-runtime"));
    assert!(snapshot
        .plugins
        .iter()
        .any(|plugin| plugin.id == "sisyphus-runtime"));
    assert!(snapshot
        .plugins
        .iter()
        .all(|plugin| plugin.layer_id == "memstack.kernel-base"));
}
