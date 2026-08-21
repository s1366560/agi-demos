//! Live conformance test for [`DockerContainerRuntime`] against a real Docker
//! daemon, cross-checked against the in-memory state-machine oracle.
//!
//! Gated: if the Docker socket is unreachable the test prints `[skip]` and
//! passes, so an offline `cargo test --workspace` stays green. When Docker is
//! live it is a REAL verification — it creates, starts, inspects, stops and
//! removes an actual container.
//!
//! Hermetic: every container carries a unique per-run test label and is force
//! removed at the end. Uses `redis:7-alpine` (already present in the dev
//! environment) for the default tests so no registry network is required.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use agistack_adapters_docker::{DockerContainerRuntime, ImagePullPolicy};
use agistack_adapters_mem::InMemoryContainerRuntime;
use agistack_core::ports::{
    ContainerRuntime, ContainerSpec, ContainerState, NamedVolumeMount, PortBinding,
};
use bollard::container::InspectContainerOptions;
use bollard::Docker;

const TEST_IMAGE: &str = "redis:7-alpine";
static LABEL_SEQ: AtomicU64 = AtomicU64::new(0);

fn unique_label() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let seq = LABEL_SEQ.fetch_add(1, Ordering::SeqCst);
    format!("it-{}-{nanos}-{seq}", std::process::id())
}

/// Walk one runtime through the full lifecycle, returning the observed
/// [`ContainerState`] after create / start / stop, plus whether it is absent
/// after remove, plus the id `list` reported while it existed.
async fn walk_lifecycle(
    rt: &dyn ContainerRuntime,
    label_val: &str,
) -> (Vec<ContainerState>, bool, Vec<String>) {
    let spec = ContainerSpec {
        image: TEST_IMAGE.to_string(),
        cmd: None, // default redis-server stays running
        env: vec![],
        labels: vec![("agistack.test".to_string(), label_val.to_string())],
        ports: vec![],
        shm_size_bytes: None,
        seccomp_profile: None,
        named_volumes: vec![],
    };

    let id = rt.create(&spec).await.expect("create");
    let mut states = Vec::new();

    states.push(
        rt.status(&id)
            .await
            .expect("status after create")
            .expect("present")
            .state,
    );

    // `list` must find our container by its unique test label while it exists.
    let listed = rt
        .list(Some(("agistack.test", label_val)))
        .await
        .expect("list");

    rt.start(&id).await.expect("start");
    // Docker flips `running` as soon as the process starts; a short settle
    // avoids inspecting in the sub-millisecond window before that propagates.
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    states.push(
        rt.status(&id)
            .await
            .expect("status after start")
            .expect("present")
            .state,
    );

    rt.stop(&id).await.expect("stop");
    states.push(
        rt.status(&id)
            .await
            .expect("status after stop")
            .expect("present")
            .state,
    );

    rt.remove(&id).await.expect("remove");
    let absent = rt.status(&id).await.expect("status after remove").is_none();

    (states, absent, listed)
}

#[tokio::test(flavor = "multi_thread")]
async fn docker_matches_in_memory_lifecycle_state_machine() {
    let docker = match DockerContainerRuntime::connect_with_image_pull_policy(
        ImagePullPolicy::Never,
    )
    .await
    {
        Ok(d) => d,
        Err(e) => {
            println!("[skip] Docker daemon unreachable ({e}); skipping live container test");
            return;
        }
    };

    if !docker.has_image(TEST_IMAGE).await.unwrap_or(false) {
        println!("[skip] {TEST_IMAGE} is not present; skipping no-pull live container test");
        return;
    }

    let label = unique_label();
    let (docker_states, docker_absent, docker_listed) = walk_lifecycle(&docker, &label).await;

    // The live daemon must walk Created -> Running -> Exited, then be gone.
    assert_eq!(
        docker_states,
        vec![
            ContainerState::Created,
            ContainerState::Running,
            ContainerState::Exited
        ],
        "live Docker lifecycle state sequence"
    );
    assert!(docker_absent, "container must be absent after remove");
    assert_eq!(
        docker_listed.len(),
        1,
        "list should report exactly the one managed container"
    );

    // The in-memory oracle must produce the IDENTICAL state sequence — this is
    // the cross-adapter conformance claim (state machine, not byte parity).
    let mem = InMemoryContainerRuntime::new();
    let (mem_states, mem_absent, mem_listed) = walk_lifecycle(&mem, &label).await;
    assert_eq!(
        mem_states, docker_states,
        "in-memory sequence must match live Docker"
    );
    assert_eq!(mem_absent, docker_absent);
    assert_eq!(mem_listed.len(), docker_listed.len());

    // `&dyn ContainerRuntime` is usable behind the port from the core's view.
    let via_port: &dyn ContainerRuntime = &docker;
    let _ = via_port.list(None).await.expect("list(None) via dyn port");
}

#[tokio::test(flavor = "multi_thread")]
async fn docker_if_missing_policy_accepts_existing_image_without_pull() {
    let docker =
        match DockerContainerRuntime::connect_with_image_pull_policy(ImagePullPolicy::IfMissing)
            .await
        {
            Ok(d) => d,
            Err(e) => {
                println!("[skip] Docker daemon unreachable ({e}); skipping if-missing policy test");
                return;
            }
        };

    if !docker.has_image(TEST_IMAGE).await.unwrap_or(false) {
        println!("[skip] {TEST_IMAGE} is not present; skipping if-missing no-network test");
        return;
    }

    let label = unique_label();
    let (docker_states, docker_absent, docker_listed) = walk_lifecycle(&docker, &label).await;

    assert_eq!(
        docker_states,
        vec![
            ContainerState::Created,
            ContainerState::Running,
            ContainerState::Exited
        ],
        "live Docker lifecycle state sequence"
    );
    assert!(docker_absent, "container must be absent after remove");
    assert_eq!(
        docker_listed.len(),
        1,
        "if-missing create should list the managed container"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn docker_can_pull_configured_image_when_enabled() {
    let image = match std::env::var("AGISTACK_TEST_DOCKER_PULL_IMAGE") {
        Ok(image) if !image.trim().is_empty() => image,
        _ => {
            println!("[skip] AGISTACK_TEST_DOCKER_PULL_IMAGE not set; skipping registry pull test");
            return;
        }
    };

    let docker =
        match DockerContainerRuntime::connect_with_image_pull_policy(ImagePullPolicy::Always).await
        {
            Ok(d) => d,
            Err(e) => {
                println!("[skip] Docker daemon unreachable ({e}); skipping registry pull test");
                return;
            }
        };

    let spec = ContainerSpec {
        image,
        cmd: None,
        env: vec![],
        labels: vec![("agistack.test".to_string(), unique_label())],
        ports: vec![],
        shm_size_bytes: None,
        seccomp_profile: None,
        named_volumes: vec![],
    };
    let id = docker.create(&spec).await.expect("create after image pull");
    docker.remove(&id).await.expect("cleanup");
}

#[tokio::test(flavor = "multi_thread")]
async fn docker_accepts_runtime_neutral_port_bindings() {
    let docker = match DockerContainerRuntime::connect_with_image_pull_policy(
        ImagePullPolicy::Never,
    )
    .await
    {
        Ok(d) => d,
        Err(e) => {
            println!("[skip] Docker daemon unreachable ({e}); skipping live port binding test");
            return;
        }
    };

    if !docker.has_image(TEST_IMAGE).await.unwrap_or(false) {
        println!("[skip] {TEST_IMAGE} is not present; skipping live port binding test");
        return;
    }

    let label = unique_label();
    let spec = ContainerSpec {
        image: TEST_IMAGE.to_string(),
        cmd: None,
        env: vec![],
        labels: vec![("agistack.test".to_string(), label.clone())],
        ports: vec![PortBinding {
            container_port: 6379,
            host_port: 0,
            host_ip: Some("127.0.0.1".to_string()),
        }],
        shm_size_bytes: None,
        seccomp_profile: None,
        named_volumes: vec![],
    };

    let id = docker
        .create(&spec)
        .await
        .expect("create with port binding");
    let listed = docker
        .list(Some(("agistack.test", &label)))
        .await
        .expect("list");
    docker.remove(&id).await.expect("cleanup");

    assert_eq!(listed.len(), 1);
}

#[tokio::test(flavor = "multi_thread")]
async fn docker_applies_shm_and_preserves_labeled_named_volume() {
    let runtime = match DockerContainerRuntime::connect_with_image_pull_policy(
        ImagePullPolicy::Never,
    )
    .await
    {
        Ok(runtime) => runtime,
        Err(error) => {
            println!("[skip] Docker daemon unreachable ({error}); skipping mount/shm test");
            return;
        }
    };

    if !runtime.has_image(TEST_IMAGE).await.unwrap_or(false) {
        println!("[skip] {TEST_IMAGE} is not present; skipping live mount/shm test");
        return;
    }

    let docker = Docker::connect_with_local_defaults().expect("connect inspect client");
    let label = unique_label();
    let volume_name = format!("agistack-sky-cua-{label}");
    let volume_labels = vec![
        ("memstack.managed".to_string(), "true".to_string()),
        (
            "memstack.resource.type".to_string(),
            "sky-cua-chromium-profile".to_string(),
        ),
        ("agistack.test".to_string(), label.clone()),
    ];
    let spec = ContainerSpec {
        image: TEST_IMAGE.to_string(),
        cmd: None,
        env: vec![],
        labels: vec![("agistack.test".to_string(), label)],
        ports: vec![],
        shm_size_bytes: Some(1_073_741_824),
        seccomp_profile: Some(r#"{"defaultAction":"SCMP_ACT_ALLOW"}"#.to_string()),
        named_volumes: vec![NamedVolumeMount {
            name: volume_name.clone(),
            container_path: "/tmp/chromium-profile".to_string(),
            read_only: false,
            labels: volume_labels.clone(),
        }],
    };

    let id = runtime
        .create(&spec)
        .await
        .expect("create with mount and shm");
    let inspected = docker
        .inspect_container(&id, None::<InspectContainerOptions>)
        .await
        .expect("inspect created container");
    let host_config = inspected.host_config.expect("host config");
    assert_eq!(host_config.shm_size, Some(1_073_741_824));
    assert_eq!(
        host_config.security_opt,
        Some(vec![
            "seccomp={\"defaultAction\":\"SCMP_ACT_ALLOW\"}".to_string()
        ])
    );
    assert!(inspected.mounts.unwrap_or_default().iter().any(|mount| {
        mount.name.as_deref() == Some(volume_name.as_str())
            && mount.destination.as_deref() == Some("/tmp/chromium-profile")
    }));

    let volume = docker
        .inspect_volume(&volume_name)
        .await
        .expect("inspect managed volume");
    assert!(volume_labels
        .iter()
        .all(|(key, value)| volume.labels.get(key) == Some(value)));

    runtime.remove(&id).await.expect("remove container only");
    docker
        .inspect_volume(&volume_name)
        .await
        .expect("volume must survive container removal");

    let wrong_labels = vec![("agistack.test".to_string(), "forged".to_string())];
    assert!(runtime
        .remove_volume(&volume_name, &wrong_labels)
        .await
        .is_err());
    docker
        .inspect_volume(&volume_name)
        .await
        .expect("mismatched labels must not delete volume");

    runtime
        .remove_volume(&volume_name, &volume_labels)
        .await
        .expect("remove volume with matching labels");
    assert!(docker.inspect_volume(&volume_name).await.is_err());
}
