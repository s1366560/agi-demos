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
//! environment) so no image pull is triggered.

use std::time::{SystemTime, UNIX_EPOCH};

use agistack_adapters_mem::InMemoryContainerRuntime;
use agistack_adapters_docker::DockerContainerRuntime;
use agistack_core::ports::{ContainerRuntime, ContainerSpec, ContainerState};

const TEST_IMAGE: &str = "redis:7-alpine";

fn unique_label() -> String {
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    format!("it-{nanos}")
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
    };

    let id = rt.create(&spec).await.expect("create");
    let mut states = Vec::new();

    states.push(rt.status(&id).await.expect("status after create").expect("present").state);

    // `list` must find our container by its unique test label while it exists.
    let listed = rt.list(Some(("agistack.test", label_val))).await.expect("list");

    rt.start(&id).await.expect("start");
    // Docker flips `running` as soon as the process starts; a short settle
    // avoids inspecting in the sub-millisecond window before that propagates.
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    states.push(rt.status(&id).await.expect("status after start").expect("present").state);

    rt.stop(&id).await.expect("stop");
    states.push(rt.status(&id).await.expect("status after stop").expect("present").state);

    rt.remove(&id).await.expect("remove");
    let absent = rt.status(&id).await.expect("status after remove").is_none();

    (states, absent, listed)
}

#[tokio::test(flavor = "multi_thread")]
async fn docker_matches_in_memory_lifecycle_state_machine() {
    let docker = match DockerContainerRuntime::connect().await {
        Ok(d) => d,
        Err(e) => {
            println!("[skip] Docker daemon unreachable ({e}); skipping live container test");
            return;
        }
    };

    let label = unique_label();
    let (docker_states, docker_absent, docker_listed) = walk_lifecycle(&docker, &label).await;

    // The live daemon must walk Created -> Running -> Exited, then be gone.
    assert_eq!(
        docker_states,
        vec![ContainerState::Created, ContainerState::Running, ContainerState::Exited],
        "live Docker lifecycle state sequence"
    );
    assert!(docker_absent, "container must be absent after remove");
    assert_eq!(docker_listed.len(), 1, "list should report exactly the one managed container");

    // The in-memory oracle must produce the IDENTICAL state sequence — this is
    // the cross-adapter conformance claim (state machine, not byte parity).
    let mem = InMemoryContainerRuntime::new();
    let (mem_states, mem_absent, mem_listed) = walk_lifecycle(&mem, &label).await;
    assert_eq!(mem_states, docker_states, "in-memory sequence must match live Docker");
    assert_eq!(mem_absent, docker_absent);
    assert_eq!(mem_listed.len(), docker_listed.len());

    // `&dyn ContainerRuntime` is usable behind the port from the core's view.
    let via_port: &dyn ContainerRuntime = &docker;
    let _ = via_port.list(None).await.expect("list(None) via dyn port");
}
