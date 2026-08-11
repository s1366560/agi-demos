use super::*;

struct TestDirectory {
    path: PathBuf,
}

impl TestDirectory {
    fn new(label: &str) -> Self {
        let path = std::env::temp_dir().join(format!(
            "agistack-native-host-{label}-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&path).expect("create native-host test directory");
        Self { path }
    }

    fn target(&self, browser: &'static str) -> ManifestTarget {
        let profile = self.path.join(browser.replace(' ', "-"));
        std::fs::create_dir_all(&profile).expect("create browser profile fixture");
        ManifestTarget {
            browser,
            hosts_dir: profile.join("NativeMessagingHosts"),
        }
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn write_manifest(target: &ManifestTarget, value: &NativeMessagingManifest) {
    std::fs::create_dir_all(&target.hosts_dir).expect("create manifest directory");
    let bytes = serde_json::to_vec_pretty(value).expect("serialize manifest fixture");
    std::fs::write(target.manifest_path(), bytes).expect("write manifest fixture");
}

#[test]
fn unavailable_response_echoes_the_request_id() {
    let response = sidecar_unavailable_response(
        br#"{"jsonrpc":"2.0","id":42,"method":"getTabs","params":{}}"#,
    )
    .expect("a request gets an error response");
    let value: Value = serde_json::from_str(&response).expect("decode response");
    assert_eq!(value["id"], 42);
    assert_eq!(value["error"]["code"], 1);
    assert_eq!(value["error"]["message"], "sidecar unavailable");
}

#[test]
fn notifications_and_garbage_get_no_error_response() {
    assert!(sidecar_unavailable_response(
        br#"{"jsonrpc":"2.0","method":"onCDPEvent","params":{}}"#
    )
    .is_none());
    assert!(sidecar_unavailable_response(b"not json").is_none());
}

#[test]
fn manifest_matches_the_frozen_contract() {
    let value = serde_json::to_value(manifest(Path::new("/opt/memstack/sidecar")))
        .expect("serialize manifest");
    assert_eq!(value["name"], HOST_NAME);
    assert_eq!(
        value["description"],
        "MemStack browser bridge native messaging host"
    );
    assert_eq!(value["path"], "/opt/memstack/sidecar");
    assert_eq!(value["type"], "stdio");
    assert_eq!(
        value["allowed_origins"],
        json!([format!("chrome-extension://{DEFAULT_EXTENSION_ID}/")])
    );
}

#[test]
fn qa_manifest_override_accepts_only_an_absolute_isolated_directory() {
    let root = TestDirectory::new("qa-target");
    let hosts_dir = root.path.join("profile/NativeMessagingHosts");
    let targets = manifest_targets_from_override(Some(hosts_dir.as_os_str()))
        .expect("absolute QA target must be accepted");
    assert_eq!(targets.len(), 1);
    assert_eq!(targets[0].browser, "QA Chromium");
    assert_eq!(targets[0].hosts_dir, hosts_dir);

    let error = manifest_targets_from_override(Some(std::ffi::OsStr::new("relative/hosts")))
        .expect_err("relative QA target must fail closed");
    assert!(error.contains("absolute"));
}

#[test]
fn install_rejects_a_foreign_collision_without_changing_its_bytes() {
    let root = TestDirectory::new("foreign-collision");
    let target = root.target("Chromium");
    std::fs::create_dir_all(&target.hosts_dir).expect("create hosts directory");
    let foreign = br#"{"name":"org.example.foreign","description":"Foreign host","path":"/opt/foreign","type":"stdio","allowed_origins":[]}"#;
    std::fs::write(target.manifest_path(), foreign).expect("write foreign manifest");

    let mut commit = |source: &Path, destination: &Path| std::fs::rename(source, destination);
    let error = install_manifests_for_targets(
        Path::new("/opt/memstack/current-sidecar"),
        vec![target.clone()],
        &mut commit,
    )
    .expect_err("foreign manifest must block installation");
    assert!(error.contains("collision"));
    assert_eq!(
        std::fs::read(target.manifest_path()).expect("foreign manifest remains"),
        foreign
    );
}

#[test]
fn install_atomically_upgrades_an_owned_manifest_with_an_old_absolute_path() {
    let root = TestDirectory::new("owned-upgrade");
    let target = root.target("Chromium");
    write_manifest(&target, &manifest(Path::new("/opt/memstack/old-sidecar")));

    let mut commit = |source: &Path, destination: &Path| std::fs::rename(source, destination);
    install_manifests_for_targets(
        Path::new("/opt/memstack/current-sidecar"),
        vec![target.clone()],
        &mut commit,
    )
    .expect("owned manifest should be upgraded");

    let installed: NativeMessagingManifest = serde_json::from_slice(
        &std::fs::read(target.manifest_path()).expect("read upgraded manifest"),
    )
    .expect("parse upgraded manifest");
    assert_eq!(
        installed,
        manifest(Path::new("/opt/memstack/current-sidecar"))
    );
}

#[test]
fn install_rolls_back_an_earlier_target_when_a_later_commit_fails() {
    let root = TestDirectory::new("install-rollback");
    let first = root.target("Chromium");
    let second = root.target("Google Chrome");
    let mut commit_count = 0usize;
    let mut commit = |source: &Path, destination: &Path| {
        commit_count += 1;
        if commit_count == 2 {
            return Err(std::io::Error::other("injected second commit failure"));
        }
        std::fs::rename(source, destination)
    };

    install_manifests_for_targets(
        Path::new("/opt/memstack/current-sidecar"),
        vec![first.clone(), second.clone()],
        &mut commit,
    )
    .expect_err("second commit failure must abort installation");

    assert!(
        !first.manifest_path().exists(),
        "first target must be rolled back"
    );
    assert!(
        !second.manifest_path().exists(),
        "second target must remain absent"
    );
}

#[test]
fn uninstall_never_deletes_a_foreign_manifest() {
    let root = TestDirectory::new("foreign-uninstall");
    let target = root.target("Chromium");
    std::fs::create_dir_all(&target.hosts_dir).expect("create hosts directory");
    let foreign = br#"{"name":"org.example.foreign","description":"Foreign host","path":"/opt/foreign","type":"stdio","allowed_origins":[]}"#;
    std::fs::write(target.manifest_path(), foreign).expect("write foreign manifest");

    let error = uninstall_manifests_for_targets(vec![target.clone()])
        .expect_err("foreign manifest must block uninstall");
    assert!(error.contains("collision"));
    assert_eq!(
        std::fs::read(target.manifest_path()).expect("foreign manifest remains"),
        foreign
    );
}

#[test]
fn manifest_status_distinguishes_all_ownership_states() {
    let root = TestDirectory::new("status");
    let valid = root.target("Chromium");
    let owned_stale = root.target("Owned old Chromium");
    let collision = root.target("Google Chrome");
    let invalid = root.target("Brave");
    let missing = root.target("Microsoft Edge");
    let host_path = root.path.join("current-sidecar");
    std::fs::write(&host_path, b"current-broker").expect("write current broker fixture");
    write_manifest(&valid, &manifest(&host_path));
    let stale_host_path = root.path.join("old-sidecar");
    std::fs::write(&stale_host_path, b"stale-broker").expect("write stale broker fixture");
    write_manifest(&owned_stale, &manifest(&stale_host_path));
    std::fs::create_dir_all(&collision.hosts_dir).expect("create collision directory");
    std::fs::write(
        collision.manifest_path(),
        br#"{"name":"org.example.foreign","description":"Foreign host","path":"/opt/foreign","type":"stdio","allowed_origins":[]}"#,
    )
    .expect("write collision fixture");
    std::fs::create_dir_all(&invalid.hosts_dir).expect("create invalid directory");
    std::fs::write(invalid.manifest_path(), b"not-json").expect("write invalid fixture");

    let statuses = manifest_statuses_for_targets(
        vec![valid, owned_stale, collision, invalid, missing],
        &host_path,
    );
    let states: Vec<_> = statuses.iter().map(|status| status.state).collect();
    assert_eq!(
        states,
        vec![
            ManifestState::Valid,
            ManifestState::OwnedStale,
            ManifestState::Collision,
            ManifestState::Invalid,
            ManifestState::Missing,
        ]
    );
    assert_eq!(statuses[0].reason_code, "registration_valid");
    assert_eq!(
        statuses[0].allowed_actions,
        vec![RegistrationAction::Uninstall]
    );
    assert!(statuses[0].broker_digest.is_some());
    assert_eq!(statuses[1].reason_code, "owned_registration_stale");
    assert_eq!(
        statuses[1].allowed_actions,
        vec![RegistrationAction::Repair, RegistrationAction::Uninstall]
    );
    assert!(statuses[1].broker_digest.is_some());
    assert_eq!(statuses[2].reason_code, "foreign_registration_collision");
    assert!(statuses[2].allowed_actions.is_empty());
    assert_eq!(statuses[3].reason_code, "registration_invalid");
    assert!(statuses[3].allowed_actions.is_empty());
    assert_eq!(statuses[4].reason_code, "registration_missing");
    assert_eq!(
        statuses[4].allowed_actions,
        vec![RegistrationAction::Install]
    );
    assert!(statuses
        .iter()
        .all(|status| !status.registration_location.is_empty()));
    let serialized = serde_json::to_value(&statuses[1]).expect("serialize status");
    assert_eq!(serialized["state"], "owned_stale");
    assert_eq!(serialized["allowedActions"], json!(["repair", "uninstall"]));
}

#[cfg(unix)]
#[test]
fn manifest_symlink_is_invalid_and_never_replaced() {
    use std::os::unix::fs::symlink;
    let root = TestDirectory::new("symlink");
    let target = root.target("Chromium");
    std::fs::create_dir_all(&target.hosts_dir).expect("create hosts directory");
    let symlink_target = root.path.join("foreign.json");
    std::fs::write(&symlink_target, b"foreign").expect("write symlink target");
    symlink(&symlink_target, target.manifest_path()).expect("create manifest symlink");

    let statuses = manifest_statuses_for_targets(
        vec![target.clone()],
        Path::new("/opt/memstack/current-sidecar"),
    );
    assert_eq!(statuses[0].state, ManifestState::Invalid);
    let mut commit = |source: &Path, destination: &Path| std::fs::rename(source, destination);
    install_manifests_for_targets(
        Path::new("/opt/memstack/current-sidecar"),
        vec![target],
        &mut commit,
    )
    .expect_err("symlink manifest must block installation");
    assert_eq!(
        std::fs::read(&symlink_target).expect("foreign target remains"),
        b"foreign"
    );
}
