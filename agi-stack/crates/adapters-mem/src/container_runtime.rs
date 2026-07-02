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
    ContainerRuntime, ContainerSpec, ContainerState, ContainerStatus, CoreResult, PortBinding,
};

/// Process-local container runtime: `id -> record`. Ids are `mem-{n}` so tests
/// get stable, sorted handles.
#[derive(Default)]
pub struct InMemoryContainerRuntime {
    inner: Mutex<BTreeMap<String, Record>>,
    seq: AtomicU64,
}

#[derive(Clone)]
struct Record {
    state: ContainerState,
    exit_code: Option<i64>,
    labels: Vec<(String, String)>,
    ports: Vec<PortBinding>,
}

impl InMemoryContainerRuntime {
    pub fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl ContainerRuntime for InMemoryContainerRuntime {
    async fn create(&self, spec: &ContainerSpec) -> CoreResult<String> {
        let n = self.seq.fetch_add(1, Ordering::SeqCst);
        let id = format!("mem-{n:06}");
        let mut inner = self.inner.lock().expect("container runtime mutex");
        inner.insert(
            id.clone(),
            Record {
                state: ContainerState::Created,
                exit_code: None,
                labels: spec.labels.clone(),
                ports: spec.ports.clone(),
            },
        );
        Ok(id)
    }

    async fn start(&self, id: &str) -> CoreResult<()> {
        let mut inner = self.inner.lock().expect("container runtime mutex");
        if let Some(r) = inner.get_mut(id) {
            r.state = ContainerState::Running;
            r.exit_code = None;
        }
        Ok(())
    }

    async fn status(&self, id: &str) -> CoreResult<Option<ContainerStatus>> {
        let inner = self.inner.lock().expect("container runtime mutex");
        Ok(inner.get(id).map(|r| ContainerStatus {
            id: id.to_string(),
            state: r.state,
            running: matches!(r.state, ContainerState::Running),
            exit_code: r.exit_code,
            ports: r.ports.clone(),
        }))
    }

    async fn stop(&self, id: &str) -> CoreResult<()> {
        let mut inner = self.inner.lock().expect("container runtime mutex");
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
        let mut inner = self.inner.lock().expect("container runtime mutex");
        inner.remove(id); // absent id: no-op success
        Ok(())
    }

    async fn list(&self, label: Option<(&str, &str)>) -> CoreResult<Vec<String>> {
        let inner = self.inner.lock().expect("container runtime mutex");
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

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
}
