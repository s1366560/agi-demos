//! `agistack-adapters-docker`: the **production sandbox-provisioning** adapter
//! behind the [`ContainerRuntime`] port (F9, `10-production-migration.md` §3).
//!
//! [`DockerContainerRuntime`] drives a real Docker daemon over the local socket
//! (`bollard`) to create/start/stop/remove the isolated containers that host a
//! remote MCP [`ToolHost`](agistack_core::ports::ToolHost). It is the Rust
//! re-expression of the Python `MCPSandboxAdapter` container lifecycle.
//!
//! **Server-only.** `bollard` pulls in the hyper + tokio HTTP stack, so — exactly
//! like `adapters-postgres` / `adapters-redis` / `adapters-s3` — it never enters
//! the core/wasm path (ADR-0001). The core only ever sees `dyn ContainerRuntime`;
//! the in-memory sibling [`InMemoryContainerRuntime`](agistack_adapters_mem) is
//! the browser/device tier and the state-machine conformance oracle.
//!
//! Every container this adapter creates carries a managed label
//! (`agistack.managed=true`) so [`list`](DockerContainerRuntime::list) only ever
//! returns containers this layer owns, never unrelated host containers.

use std::collections::HashMap;

use async_trait::async_trait;
use bollard::container::{
    Config, CreateContainerOptions, InspectContainerOptions, ListContainersOptions,
    RemoveContainerOptions, StartContainerOptions, StopContainerOptions,
};
use bollard::models::ContainerStateStatusEnum;
use bollard::Docker;

use agistack_core::ports::{
    ContainerRuntime, ContainerSpec, ContainerState, ContainerStatus, CoreError, CoreResult,
};

/// Label stamped on every managed container so `list` scopes to this layer's
/// fleet rather than the whole host.
const MANAGED_LABEL: &str = "agistack.managed";
const MANAGED_VALUE: &str = "true";

/// [`ContainerRuntime`] backed by a live Docker daemon via `bollard`.
pub struct DockerContainerRuntime {
    docker: Docker,
}

fn gerr<E: std::fmt::Display>(e: E) -> CoreError {
    CoreError::Container(e.to_string())
}

fn is_status(e: &bollard::errors::Error, code: u16) -> bool {
    matches!(
        e,
        bollard::errors::Error::DockerResponseServerError { status_code, .. } if *status_code == code
    )
}

impl DockerContainerRuntime {
    /// Connect to the local Docker daemon (honoring `DOCKER_HOST`, else the
    /// default socket) and verify it is reachable with a `ping`.
    pub async fn connect() -> CoreResult<Self> {
        let docker = Docker::connect_with_local_defaults().map_err(gerr)?;
        docker.ping().await.map_err(gerr)?;
        Ok(Self { docker })
    }
}

#[async_trait]
impl ContainerRuntime for DockerContainerRuntime {
    async fn create(&self, spec: &ContainerSpec) -> CoreResult<String> {
        let mut labels: HashMap<String, String> =
            spec.labels.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        labels.insert(MANAGED_LABEL.to_string(), MANAGED_VALUE.to_string());

        let env: Vec<String> = spec.env.iter().map(|(k, v)| format!("{k}={v}")).collect();

        let config = Config {
            image: Some(spec.image.clone()),
            cmd: spec.cmd.clone(),
            env: if env.is_empty() { None } else { Some(env) },
            labels: Some(labels),
            ..Default::default()
        };

        let resp = self
            .docker
            .create_container(None::<CreateContainerOptions<String>>, config)
            .await
            .map_err(gerr)?;
        Ok(resp.id)
    }

    async fn start(&self, id: &str) -> CoreResult<()> {
        self.docker
            .start_container(id, None::<StartContainerOptions<String>>)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    async fn status(&self, id: &str) -> CoreResult<Option<ContainerStatus>> {
        match self.docker.inspect_container(id, None::<InspectContainerOptions>).await {
            Ok(info) => {
                let state = info.state;
                let running = state.as_ref().and_then(|s| s.running).unwrap_or(false);
                let status_enum = state.as_ref().and_then(|s| s.status);
                let exit_code = state.as_ref().and_then(|s| s.exit_code);
                let mapped = match status_enum {
                    Some(ContainerStateStatusEnum::CREATED) => ContainerState::Created,
                    Some(ContainerStateStatusEnum::RUNNING) => ContainerState::Running,
                    Some(ContainerStateStatusEnum::EXITED) => ContainerState::Exited,
                    _ if running => ContainerState::Running,
                    _ => ContainerState::Unknown,
                };
                Ok(Some(ContainerStatus {
                    id: info.id.unwrap_or_else(|| id.to_string()),
                    state: mapped,
                    running,
                    exit_code,
                }))
            }
            Err(e) if is_status(&e, 404) => Ok(None),
            Err(e) => Err(gerr(e)),
        }
    }

    async fn stop(&self, id: &str) -> CoreResult<()> {
        match self.docker.stop_container(id, Some(StopContainerOptions { t: 5 })).await {
            Ok(()) => Ok(()),
            // 304 = already stopped, 404 = gone — both a no-op success.
            Err(e) if is_status(&e, 304) || is_status(&e, 404) => Ok(()),
            Err(e) => Err(gerr(e)),
        }
    }

    async fn remove(&self, id: &str) -> CoreResult<()> {
        let opts = RemoveContainerOptions { force: true, ..Default::default() };
        match self.docker.remove_container(id, Some(opts)).await {
            Ok(()) => Ok(()),
            Err(e) if is_status(&e, 404) => Ok(()),
            Err(e) => Err(gerr(e)),
        }
    }

    async fn list(&self, label: Option<(&str, &str)>) -> CoreResult<Vec<String>> {
        let mut label_filters = vec![format!("{MANAGED_LABEL}={MANAGED_VALUE}")];
        if let Some((k, v)) = label {
            label_filters.push(format!("{k}={v}"));
        }
        let mut filters: HashMap<String, Vec<String>> = HashMap::new();
        filters.insert("label".to_string(), label_filters);

        let opts = ListContainersOptions::<String> { all: true, filters, ..Default::default() };
        let summaries = self.docker.list_containers(Some(opts)).await.map_err(gerr)?;
        let mut ids: Vec<String> = summaries.into_iter().filter_map(|c| c.id).collect();
        ids.sort();
        Ok(ids)
    }
}
