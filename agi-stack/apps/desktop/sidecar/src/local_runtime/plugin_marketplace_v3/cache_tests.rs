use super::*;
#[test]
fn snapshot_collection_waits_for_last_os_lease_and_never_scans_unregistered_roots() {
    let (_, _, directory) = tests::fixture();
    let root = directory.join("scope");
    let snapshot = root
        .join("snapshots")
        .join(uuid::Uuid::new_v4().to_string());
    std::fs::create_dir_all(&snapshot).unwrap();
    std::fs::write(snapshot.join("payload"), b"owned").unwrap();
    let unrelated = root.join("snapshots/unregistered");
    std::fs::create_dir_all(&unrelated).unwrap();
    std::fs::write(unrelated.join("keep"), b"user").unwrap();
    let mut data = Database::default();
    cache::register(&mut data, &snapshot);
    let one = cache::lease(&snapshot).unwrap();
    let two = cache::lease(&snapshot).unwrap();
    let stats = cache::collect(&root, &mut data, true).unwrap();
    assert_eq!(stats["removed_bytes"], 0);
    assert!(snapshot.exists());
    drop(one);
    assert!(snapshot.exists());
    drop(two);
    assert!(!snapshot.exists());
    assert!(unrelated.join("keep").exists());
    let _ = std::fs::remove_dir_all(directory);
}
#[cfg(unix)]
#[test]
fn snapshot_recovery_observes_live_process_locks_and_reclaims_after_process_death() {
    use std::process::{Command, Stdio};
    let (_, _, directory) = tests::fixture();
    let root = directory.join("scope");
    let id = uuid::Uuid::new_v4().to_string();
    let snapshot = root.join("snapshots").join(&id);
    std::fs::create_dir_all(&snapshot).unwrap();
    std::fs::write(snapshot.join("payload"), b"owned").unwrap();
    let leases = root.join("leases").join(id);
    std::fs::create_dir_all(&leases).unwrap();
    let marker = root.join("ready");
    let mut child=Command::new("python3").args(["-c","import fcntl,sys,time; f=open(sys.argv[1],'w'); fcntl.flock(f,fcntl.LOCK_EX); open(sys.argv[2],'w').close(); time.sleep(30)"]).arg(leases.join("foreign-process")).arg(&marker).stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
    for _ in 0..100 {
        if marker.exists() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    assert!(marker.exists());
    let mut data = Database::default();
    cache::register(&mut data, &snapshot);
    assert_eq!(
        cache::collect(&root, &mut data, true).unwrap()["removed_bytes"],
        0
    );
    assert!(snapshot.exists());
    child.kill().unwrap();
    child.wait().unwrap();
    assert_eq!(
        cache::collect(&root, &mut data, true).unwrap()["removed_bytes"],
        5
    );
    assert!(!snapshot.exists());
    let _ = std::fs::remove_dir_all(directory);
}
#[test]
fn preflight_snapshots_expire_after_twenty_four_hours() {
    let (_, _, directory) = tests::fixture();
    let root = directory.join("scope");
    let id = uuid::Uuid::new_v4().to_string();
    let snapshot = root.join("snapshots").join(&id);
    package::snapshot(
        &tests::example().join("plugins/marketplace-demo"),
        &snapshot,
    )
    .unwrap();
    let mut data = Database::default();
    data.preflights.insert(
        id.clone(),
        Preflight {
            id: id.clone(),
            package: package::parse(&snapshot, "test").unwrap(),
            digest: package::digest(&snapshot).unwrap(),
            created_at: chrono::Utc::now().timestamp(),
        },
    );
    assert_eq!(
        cache::collect(&root, &mut data, true).unwrap()["removed_entries"],
        0
    );
    assert!(snapshot.exists());
    data.preflights.get_mut(&id).unwrap().created_at -= 86401;
    assert_eq!(
        cache::collect(&root, &mut data, true).unwrap()["removed_entries"],
        1
    );
    assert!(!snapshot.exists());
    assert!(data.preflights.is_empty());
    let _ = std::fs::remove_dir_all(directory);
}
