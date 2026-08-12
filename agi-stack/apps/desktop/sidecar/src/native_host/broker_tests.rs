use super::*;

struct TestDirectory {
    path: PathBuf,
}

impl TestDirectory {
    fn new(label: &str) -> Self {
        let path =
            std::env::temp_dir().join(format!("agistack-broker-{label}-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&path).expect("create broker test directory");
        Self { path }
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

#[test]
fn atomic_file_update_rollback_restores_existing_bytes_and_removes_new_files() {
    let root = TestDirectory::new("atomic-file-rollback");
    let existing = root.path.join("existing.json");
    std::fs::write(&existing, b"old").expect("write existing fixture");

    let update = broker::AtomicFileUpdate::replace(&existing, b"new", "test-existing")
        .expect("replace existing file");
    assert_eq!(std::fs::read(&existing).expect("read replacement"), b"new");
    update.rollback().expect("restore existing file");
    assert_eq!(std::fs::read(&existing).expect("read restoration"), b"old");

    let created = root.path.join("created.json");
    let update = broker::AtomicFileUpdate::replace(&created, b"new", "test-created")
        .expect("create new file");
    assert!(created.exists());
    update.rollback().expect("remove new file");
    assert!(!created.exists());
}

#[test]
fn versioned_broker_switch_rollback_restores_the_previous_current_record() {
    let root = TestDirectory::new("broker-current-rollback");
    let first_source = root.path.join("sidecar-v1");
    let second_source = root.path.join("sidecar-v2");
    std::fs::write(&first_source, b"signed-broker-v1").expect("write v1 broker");
    std::fs::write(&second_source, b"signed-broker-v2").expect("write v2 broker");

    let first = broker::install_versioned_broker(&first_source, &root.path, "1.0.0")
        .expect("install first broker");
    let first_current = std::fs::read(root.path.join("current.json")).expect("read first current");
    let first_path = first.broker_path().to_path_buf();
    first.commit();

    let second = broker::install_versioned_broker(&second_source, &root.path, "1.1.0")
        .expect("install second broker");
    assert_ne!(second.broker_path(), first_path);
    second.rollback().expect("rollback second broker switch");

    assert_eq!(
        std::fs::read(root.path.join("current.json")).expect("read rolled-back current"),
        first_current
    );
    assert_eq!(
        broker::current_broker_path(&root.path).expect("parse current broker path"),
        first_path
    );
}

#[test]
fn versioned_broker_collision_fails_closed_without_replacing_bytes() {
    let root = TestDirectory::new("broker-collision");
    let source = root.path.join("sidecar");
    std::fs::write(&source, b"expected-broker").expect("write broker source");
    let destination =
        broker::versioned_broker_path(&source, &root.path, "1.0.0").expect("derive broker path");
    std::fs::create_dir_all(destination.parent().expect("version directory"))
        .expect("create version directory");
    std::fs::write(&destination, b"foreign-binary").expect("write collision fixture");

    let error = broker::install_versioned_broker(&source, &root.path, "1.0.0")
        .expect_err("foreign bytes at an owned version path must fail closed");

    assert!(error.contains("collision"));
    assert_eq!(
        std::fs::read(destination).expect("foreign bytes remain"),
        b"foreign-binary"
    );
    assert!(!root.path.join("current.json").exists());
}
