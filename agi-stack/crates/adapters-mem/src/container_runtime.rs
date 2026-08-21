//! In-memory [`ContainerRuntime`] — the test/device tier of the sandbox
//! provisioning port (F9). Models the observable **lifecycle state machine** of
//! the `bollard`/Docker adapter (create → start → stop → remove) without any
//! I/O, so it backs unit tests and the wasm build and serves as the conformance
//! oracle for the Docker tier.
//!
//! Unlike the storage ports (F5/F6/F8) this is a *lifecycle* surface, so the
//! equivalence the Docker integration test asserts is **state-machine
//! conformance** — both tiers walk `Created → Running → Exited → (absent)` — not
//! byte parity.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use async_trait::async_trait;

use agistack_core::ports::{
    ContainerRuntime, ContainerSpec, ContainerState, ContainerStatus, CoreError, CoreResult,
    PortBinding,
};

/// Process-local container runtime: `id -> record`. Ids are `mem-{n}` so tests
/// get stable, sorted handles.
#[derive(Default)]
pub struct InMemoryContainerRuntime {
    inner: Mutex<BTreeMap<String, Record>>,
    volumes: Mutex<BTreeMap<String, Vec<(String, String)>>>,
    seq: AtomicU64,
}

#[derive(Clone)]
struct Record {
    state: ContainerState,
    exit_code: Option<i64>,
    labels: Vec<(String, String)>,
    ports: Vec<PortBinding>,
    named_volumes: Vec<String>,
}

impl InMemoryContainerRuntime {
    pub fn new() -> Self {
        Self::default()
    }
}

fn poisoned() -> CoreError {
    CoreError::Container("poisoned container runtime lock".into())
}

#[async_trait]
impl ContainerRuntime for InMemoryContainerRuntime {
    async fn create(&self, spec: &ContainerSpec) -> CoreResult<String> {
        {
            let mut volumes = self.volumes.lock().map_err(|_| poisoned())?;
            for mount in &spec.named_volumes {
                match volumes.get(&mount.name) {
                    Some(labels)
                        if mount
                            .labels
                            .iter()
                            .all(|required| labels.contains(required)) => {}
                    Some(_) => {
                        return Err(CoreError::Container(format!(
                            "named volume {} has mismatched ownership labels",
                            mount.name
                        )));
                    }
                    None => {
                        volumes.insert(mount.name.clone(), mount.labels.clone());
                    }
                }
            }
        }
        let n = self.seq.fetch_add(1, Ordering::SeqCst);
        let id = format!("mem-{n:06}");
        let mut inner = self.inner.lock().map_err(|_| poisoned())?;
        inner.insert(
            id.clone(),
            Record {
                state: ContainerState::Created,
                exit_code: None,
                labels: spec.labels.clone(),
                ports: spec.ports.clone(),
                named_volumes: spec
                    .named_volumes
                    .iter()
                    .map(|mount| mount.name.clone())
                    .collect(),
            },
        );
        Ok(id)
    }

    async fn start(&self, id: &str) -> CoreResult<()> {
        let mut inner = self.inner.lock().map_err(|_| poisoned())?;
        if let Some(r) = inner.get_mut(id) {
            r.state = ContainerState::Running;
            r.exit_code = None;
        }
        Ok(())
    }

    async fn status(&self, id: &str) -> CoreResult<Option<ContainerStatus>> {
        let inner = self.inner.lock().map_err(|_| poisoned())?;
        Ok(inner.get(id).map(|r| ContainerStatus {
            id: id.to_string(),
            state: r.state,
            running: matches!(r.state, ContainerState::Running),
            exit_code: r.exit_code,
            ports: r.ports.clone(),
        }))
    }

    async fn stop(&self, id: &str) -> CoreResult<()> {
        let mut inner = self.inner.lock().map_err(|_| poisoned())?;
        if let Some(r) = inner.get_mut(id) {
            // Stopping is a no-op unless it was running.
            if matches!(r.state, ContainerState::Running | ContainerState::Created) {
                r.state = ContainerState::Exited;
                r.exit_code = Some(0);
            }
        }
        Ok(())
    }

    async fn remove(&self, id: &str) -> CoreResult<()> {
        let mut inner = self.inner.lock().map_err(|_| poisoned())?;
        inner.remove(id); // absent id: no-op success
        Ok(())
    }

    async fn list(&self, label: Option<(&str, &str)>) -> CoreResult<Vec<String>> {
        let inner = self.inner.lock().map_err(|_| poisoned())?;
        // BTreeMap iterates ascending already.
        Ok(inner
            .iter()
            .filter(|(_, r)| match label {
                None => true,
                Some((k, v)) => r.labels.iter().any(|(lk, lv)| lk == k && lv == v),
            })
            .map(|(id, _)| id.clone())
            .collect())
    }

    async fn remove_volume(
        &self,
        name: &str,
        required_labels: &[(String, String)],
    ) -> CoreResult<()> {
        let inner = self.inner.lock().map_err(|_| poisoned())?;
        if inner
            .values()
            .any(|record| record.named_volumes.iter().any(|volume| volume == name))
        {
            return Err(CoreError::Container(format!(
                "named volume {name} is still attached"
            )));
        }
        drop(inner);

        let mut volumes = self.volumes.lock().map_err(|_| poisoned())?;
        let Some(labels) = volumes.get(name) else {
            return Ok(());
        };
        if !required_labels
            .iter()
            .all(|required| labels.contains(required))
        {
            return Err(CoreError::Container(format!(
                "named volume {name} has mismatched ownership labels"
            )));
        }
        volumes.remove(name);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_core::ports::NamedVolumeMount;
    use futures::executor::block_on;

    static PANIC_HOOK_LOCK: Mutex<()> = Mutex::new(());

    fn spec(labels: &[(&str, &str)]) -> ContainerSpec {
        ContainerSpec {
            image: "redis:7-alpine".to_string(),
            cmd: None,
            env: vec![],
            labels: labels
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
            ports: vec![],
            shm_size_bytes: None,
            seccomp_profile: None,
            named_volumes: vec![],
        }
    }

    #[test]
    fn lifecycle_walks_created_running_exited_absent() {
        let rt = InMemoryContainerRuntime::new();
        let id = block_on(rt.create(&spec(&[]))).unwrap();

        let st = block_on(rt.status(&id)).unwrap().unwrap();
        assert_eq!(st.state, ContainerState::Created);
        assert!(!st.running);
        assert!(st.ports.is_empty());

        block_on(rt.start(&id)).unwrap();
        let st = block_on(rt.status(&id)).unwrap().unwrap();
        assert_eq!(st.state, ContainerState::Running);
        assert!(st.running);

        block_on(rt.stop(&id)).unwrap();
        let st = block_on(rt.status(&id)).unwrap().unwrap();
        assert_eq!(st.state, ContainerState::Exited);
        assert!(!st.running);
        assert_eq!(st.exit_code, Some(0));

        block_on(rt.remove(&id)).unwrap();
        assert_eq!(block_on(rt.status(&id)).unwrap(), None);
    }

    #[test]
    fn remove_absent_is_noop_success() {
        let rt = InMemoryContainerRuntime::new();
        block_on(rt.remove("nope")).unwrap();
        assert_eq!(block_on(rt.status("nope")).unwrap(), None);
    }

    #[test]
    fn list_filters_by_label_and_is_sorted() {
        let rt = InMemoryContainerRuntime::new();
        let a = block_on(rt.create(&spec(&[("project", "p1")]))).unwrap();
        let b = block_on(rt.create(&spec(&[("project", "p2")]))).unwrap();
        let c = block_on(rt.create(&spec(&[("project", "p1")]))).unwrap();

        let mut all = block_on(rt.list(None)).unwrap();
        all.sort();
        assert_eq!(all, vec![a.clone(), b.clone(), c.clone()]);

        let p1 = block_on(rt.list(Some(("project", "p1")))).unwrap();
        assert_eq!(p1, vec![a, c]);
        let p2 = block_on(rt.list(Some(("project", "p2")))).unwrap();
        assert_eq!(p2, vec![b]);
        assert!(block_on(rt.list(Some(("project", "none"))))
            .unwrap()
            .is_empty());
    }

    #[test]
    fn create_records_port_bindings_for_state_machine_oracles() {
        let rt = InMemoryContainerRuntime::new();
        let mut spec = spec(&[]);
        spec.ports = vec![PortBinding {
            container_port: 8765,
            host_port: 18765,
            host_ip: Some("127.0.0.1".to_string()),
        }];
        let id = block_on(rt.create(&spec)).unwrap();
        let status = block_on(rt.status(&id)).unwrap().unwrap();
        assert_eq!(status.ports, spec.ports);
    }

    #[test]
    fn stop_before_start_still_exits() {
        let rt = InMemoryContainerRuntime::new();
        let id = block_on(rt.create(&spec(&[]))).unwrap();
        block_on(rt.stop(&id)).unwrap();
        let st = block_on(rt.status(&id)).unwrap().unwrap();
        assert_eq!(st.state, ContainerState::Exited);
    }

    #[test]
    fn named_volume_survives_container_removal_and_requires_matching_labels() {
        let rt = InMemoryContainerRuntime::new();
        let labels = vec![("memstack.project_id".to_string(), "p1".to_string())];
        let mut container_spec = spec(&[]);
        container_spec.shm_size_bytes = Some(1_073_741_824);
        container_spec.named_volumes = vec![NamedVolumeMount {
            name: "profile-p1".to_string(),
            container_path: "/home/sandbox/.config/chromium".to_string(),
            read_only: false,
            labels: labels.clone(),
        }];

        let id = block_on(rt.create(&container_spec)).unwrap();
        assert!(block_on(rt.remove_volume("profile-p1", &labels)).is_err());
        block_on(rt.remove(&id)).unwrap();
        assert!(block_on(rt.remove_volume(
            "profile-p1",
            &[("memstack.project_id".to_string(), "forged".to_string())]
        ))
        .is_err());
        block_on(rt.remove_volume("profile-p1", &labels)).unwrap();
        block_on(rt.remove_volume("profile-p1", &labels)).unwrap();
    }

    #[test]
    fn create_rejects_existing_named_volume_with_mismatched_labels() {
        let rt = InMemoryContainerRuntime::new();
        let mut first = spec(&[]);
        first.named_volumes = vec![NamedVolumeMount {
            name: "shared-name".to_string(),
            container_path: "/profile".to_string(),
            read_only: false,
            labels: vec![("owner".to_string(), "p1".to_string())],
        }];
        let first_id = block_on(rt.create(&first)).unwrap();
        block_on(rt.remove(&first_id)).unwrap();

        let mut forged = first;
        forged.named_volumes[0].labels = vec![("owner".to_string(), "p2".to_string())];
        assert!(block_on(rt.create(&forged)).is_err());
    }

    #[test]
    fn poisoned_lock_returns_container_error() {
        let rt = InMemoryContainerRuntime::new();
        let _panic_hook_guard = PANIC_HOOK_LOCK.lock().unwrap();
        let old_hook = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = rt.inner.lock().unwrap();
            panic!("poison container runtime mutex");
        }));
        std::panic::set_hook(old_hook);
        assert!(result.is_err());

        let err = block_on(rt.status("mem-000000")).unwrap_err();
        assert!(matches!(
            err,
            CoreError::Container(message) if message == "poisoned container runtime lock"
        ));
    }
}
