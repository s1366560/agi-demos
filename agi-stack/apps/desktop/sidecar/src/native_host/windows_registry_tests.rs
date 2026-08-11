use std::collections::BTreeMap;

use super::*;

struct TestDirectory {
    path: PathBuf,
}

impl TestDirectory {
    fn new(label: &str) -> Self {
        let path = std::env::temp_dir().join(format!(
            "agistack-windows-registry-{label}-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&path).expect("create registry test directory");
        Self { path }
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

#[derive(Default)]
struct FakeRegistry {
    values: BTreeMap<String, String>,
    writes: usize,
    fail_write_at: Option<usize>,
}

impl windows_registry::RegistryStore for FakeRegistry {
    fn read(&self, key: &str) -> Result<Option<String>, String> {
        Ok(self.values.get(key).cloned())
    }

    fn write(&mut self, key: &str, value: &str) -> Result<(), String> {
        self.writes += 1;
        if self.fail_write_at == Some(self.writes) {
            return Err("injected registry write failure".to_string());
        }
        self.values.insert(key.to_string(), value.to_string());
        Ok(())
    }

    fn delete(&mut self, key: &str) -> Result<(), String> {
        self.values.remove(key);
        Ok(())
    }
}

#[test]
fn windows_hkcu_targets_cover_chrome_edge_chromium_and_brave() {
    let targets = windows_registry::registry_targets();
    assert_eq!(
        targets
            .iter()
            .map(|target| (target.browser, target.key))
            .collect::<Vec<_>>(),
        vec![
            (
                "Google Chrome",
                r"Software\Google\Chrome\NativeMessagingHosts\com.memstack.browserbridge",
            ),
            (
                "Microsoft Edge",
                r"Software\Microsoft\Edge\NativeMessagingHosts\com.memstack.browserbridge",
            ),
            (
                "Chromium",
                r"Software\Chromium\NativeMessagingHosts\com.memstack.browserbridge",
            ),
            (
                "Brave",
                r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.memstack.browserbridge",
            ),
        ]
    );
    assert!(targets
        .iter()
        .all(|target| !target.key.contains("HKEY_LOCAL_MACHINE")));
}

#[test]
fn second_registry_failure_rolls_back_values_manifest_and_current() {
    let root = TestDirectory::new("windows-registry-rollback");
    let old_source = root.path.join("sidecar-v1.exe");
    let new_source = root.path.join("sidecar-v2.exe");
    std::fs::write(&old_source, b"broker-v1").expect("write old broker");
    std::fs::write(&new_source, b"broker-v2").expect("write new broker");
    let mut registry = FakeRegistry::default();

    windows_registry::install_with_store(
        &mut registry,
        windows_registry::registry_targets(),
        &old_source,
        &root.path,
        "1.0.0",
    )
    .expect("install first version");
    let old_current = std::fs::read(root.path.join("current.json")).expect("read old current");
    let old_manifest =
        std::fs::read(root.path.join(MANIFEST_FILE_NAME)).expect("read old manifest");
    for (index, target) in windows_registry::registry_targets().iter().enumerate() {
        let legacy_manifest = root.path.join(format!("legacy-{index}.json"));
        std::fs::write(&legacy_manifest, &old_manifest).expect("write legacy manifest fixture");
        registry.values.insert(
            target.key.to_string(),
            legacy_manifest.to_string_lossy().into_owned(),
        );
    }
    let old_values = registry.values.clone();

    registry.writes = 0;
    registry.fail_write_at = Some(2);
    windows_registry::install_with_store(
        &mut registry,
        windows_registry::registry_targets(),
        &new_source,
        &root.path,
        "1.1.0",
    )
    .expect_err("second registry write failure must abort the transaction");

    assert_eq!(registry.values, old_values);
    assert_eq!(
        std::fs::read(root.path.join("current.json")).expect("read rolled-back current"),
        old_current
    );
    assert_eq!(
        std::fs::read(root.path.join(MANIFEST_FILE_NAME)).expect("read rolled-back manifest"),
        old_manifest
    );
}

#[test]
fn foreign_registry_collision_is_unchanged_and_owned_uninstall_is_all_or_nothing() {
    let root = TestDirectory::new("windows-owned-uninstall");
    let owned_manifest_path = root.path.join("owned.json");
    let foreign_manifest_path = root.path.join("foreign.json");
    std::fs::write(
        &owned_manifest_path,
        serde_json::to_vec_pretty(&manifest(Path::new("/opt/memstack/versioned-broker")))
            .expect("serialize owned manifest"),
    )
    .expect("write owned manifest fixture");
    std::fs::write(
        &foreign_manifest_path,
        br#"{"name":"org.example.foreign","description":"Foreign","path":"C:\\foreign.exe","type":"stdio","allowed_origins":[]}"#,
    )
    .expect("write foreign manifest");

    let targets = windows_registry::registry_targets();
    let mut registry = FakeRegistry::default();
    registry.values.insert(
        targets[0].key.to_string(),
        owned_manifest_path.to_string_lossy().into_owned(),
    );
    registry.values.insert(
        targets[1].key.to_string(),
        foreign_manifest_path.to_string_lossy().into_owned(),
    );
    let original = registry.values.clone();

    let error = windows_registry::uninstall_with_store(&mut registry, &targets[..2])
        .expect_err("foreign collision must block uninstall");
    assert!(error.contains("collision"));
    assert_eq!(registry.values, original);
}
