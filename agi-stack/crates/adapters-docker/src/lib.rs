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
use bollard::image::CreateImageOptions;
use bollard::models::{ContainerStateStatusEnum, HostConfig, PortBinding as DockerPortBinding};
use bollard::Docker;
use futures::StreamExt;

use agistack_core::ports::{
    ContainerRuntime, ContainerSpec, ContainerState, ContainerStatus, CoreError, CoreResult,
    PortBinding,
};

/// Label stamped on every managed container so `list` scopes to this layer's
/// fleet rather than the whole host.
const MANAGED_LABEL: &str = "agistack.managed";
const MANAGED_VALUE: &str = "true";

/// [`ContainerRuntime`] backed by a live Docker daemon via `bollard`.
pub struct DockerContainerRuntime {
    docker: Docker,
    image_pull_policy: ImagePullPolicy,
}

/// Server-only image acquisition policy for the Docker sandbox adapter.
///
/// This stays out of the portable [`ContainerRuntime`] port because browser,
/// device and wasm tiers must not learn Docker daemon semantics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ImagePullPolicy {
    /// Never contact a registry. Container creation fails if the image is absent.
    Never,
    /// Pull only when `inspect_image` says the configured image is missing.
    IfMissing,
    /// Pull before every container create.
    Always,
}

impl ImagePullPolicy {
    /// Parse deployment-friendly values used by env vars and runbooks.
    pub fn parse(raw: &str) -> Option<Self> {
        let normalized = raw.trim().to_ascii_lowercase().replace('_', "-");
        match normalized.as_str() {
            "never" | "false" | "0" | "off" | "no" => Some(Self::Never),
            "missing" | "if-missing" | "true" | "1" | "on" | "yes" => Some(Self::IfMissing),
            "always" => Some(Self::Always),
            _ => None,
        }
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Never => "never",
            Self::IfMissing => "if_missing",
            Self::Always => "always",
        }
    }
}

impl std::fmt::Display for ImagePullPolicy {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
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

fn parse_port_key(key: &str) -> Option<u16> {
    let (port, proto) = key.split_once('/')?;
    if proto != "tcp" {
        return None;
    }
    port.parse::<u16>().ok()
}

impl DockerContainerRuntime {
    /// Connect to the local Docker daemon (honoring `DOCKER_HOST`, else the
    /// default socket) and verify it is reachable with a `ping`.
    pub async fn connect() -> CoreResult<Self> {
        Self::connect_with_image_pull_policy(ImagePullPolicy::Never).await
    }

    /// Connect with an explicit image pull policy. Production server wiring uses
    /// this to make cold hosts self-heal by pulling sandbox images without
    /// changing the core `ContainerRuntime` contract.
    pub async fn connect_with_image_pull_policy(
        image_pull_policy: ImagePullPolicy,
    ) -> CoreResult<Self> {
        let docker = Docker::connect_with_local_defaults().map_err(gerr)?;
        docker.ping().await.map_err(gerr)?;
        Ok(Self {
            docker,
            image_pull_policy,
        })
    }

    /// Probe whether an image is already known to the daemon.
    pub async fn has_image(&self, image: &str) -> CoreResult<bool> {
        match self.docker.inspect_image(image).await {
            Ok(_) => Ok(true),
            Err(e) if is_status(&e, 404) => Ok(false),
            Err(e) => Err(gerr(e)),
        }
    }

    async fn ensure_image(&self, image: &str) -> CoreResult<()> {
        match self.image_pull_policy {
            ImagePullPolicy::Never => Ok(()),
            ImagePullPolicy::IfMissing if self.has_image(image).await? => Ok(()),
            ImagePullPolicy::IfMissing | ImagePullPolicy::Always => self.pull_image(image).await,
        }
    }

    async fn pull_image(&self, image: &str) -> CoreResult<()> {
        let options = CreateImageOptions::<String> {
            from_image: image.to_string(),
            ..Default::default()
        };
        let mut stream = self.docker.create_image(Some(options), None, None);
        while let Some(item) = stream.next().await {
            item.map_err(gerr)?;
        }
        Ok(())
    }
}

#[async_trait]
impl ContainerRuntime for DockerContainerRuntime {
    async fn create(&self, spec: &ContainerSpec) -> CoreResult<String> {
        self.ensure_image(&spec.image).await?;

        let mut labels: HashMap<String, String> = spec
            .labels
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        labels.insert(MANAGED_LABEL.to_string(), MANAGED_VALUE.to_string());

        let env: Vec<String> = spec.env.iter().map(|(k, v)| format!("{k}={v}")).collect();

        let mut exposed_ports: HashMap<String, HashMap<(), ()>> = HashMap::new();
        let mut port_bindings: HashMap<String, Option<Vec<DockerPortBinding>>> = HashMap::new();
        for binding in &spec.ports {
            let key = format!("{}/tcp", binding.container_port);
            exposed_ports.insert(key.clone(), HashMap::new());
            port_bindings.insert(
                key,
                Some(vec![DockerPortBinding {
                    host_ip: Some(
                        binding
                            .host_ip
                            .clone()
                            .unwrap_or_else(|| "0.0.0.0".to_string()),
                    ),
                    host_port: Some(binding.host_port.to_string()),
                }]),
            );
        }

        let config = Config {
            image: Some(spec.image.clone()),
            cmd: spec.cmd.clone(),
            env: if env.is_empty() { None } else { Some(env) },
            labels: Some(labels),
            exposed_ports: if exposed_ports.is_empty() {
                None
            } else {
                Some(exposed_ports)
            },
            host_config: if port_bindings.is_empty() {
                None
            } else {
                Some(HostConfig {
                    port_bindings: Some(port_bindings),
                    ..Default::default()
                })
            },
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
        match self
            .docker
            .inspect_container(id, None::<InspectContainerOptions>)
            .await
        {
            Ok(info) => {
                let state = info.state;
                let running = state.as_ref().and_then(|s| s.running).unwrap_or(false);
                let status_enum = state.as_ref().and_then(|s| s.status);
                let exit_code = state.as_ref().and_then(|s| s.exit_code);
                let mut ports = Vec::new();
                if let Some(network) = info.network_settings {
                    if let Some(port_map) = network.ports {
                        for (key, bindings) in port_map {
                            let Some(container_port) = parse_port_key(&key) else {
                                continue;
                            };
                            let Some(bindings) = bindings else {
                                continue;
                            };
                            for binding in bindings {
                                let Some(host_port) = binding
                                    .host_port
                                    .as_deref()
                                    .and_then(|raw| raw.parse::<u16>().ok())
                                else {
                                    continue;
                                };
                                ports.push(PortBinding {
                                    container_port,
                                    host_port,
                                    host_ip: binding.host_ip,
                                });
                            }
                        }
                    }
                }
                ports.sort_by_key(|binding| (binding.container_port, binding.host_port));
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
                    ports,
                }))
            }
            Err(e) if is_status(&e, 404) => Ok(None),
            Err(e) => Err(gerr(e)),
        }
    }

    async fn stop(&self, id: &str) -> CoreResult<()> {
        match self
            .docker
            .stop_container(id, Some(StopContainerOptions { t: 5 }))
            .await
        {
            Ok(()) => Ok(()),
            // 304 = already stopped, 404 = gone — both a no-op success.
            Err(e) if is_status(&e, 304) || is_status(&e, 404) => Ok(()),
            Err(e) => Err(gerr(e)),
        }
    }

    async fn remove(&self, id: &str) -> CoreResult<()> {
        let opts = RemoveContainerOptions {
            force: true,
            ..Default::default()
        };
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

        let opts = ListContainersOptions::<String> {
            all: true,
            filters,
            ..Default::default()
        };
        let summaries = self
            .docker
            .list_containers(Some(opts))
            .await
            .map_err(gerr)?;
        let mut ids: Vec<String> = summaries.into_iter().filter_map(|c| c.id).collect();
        ids.sort();
        Ok(ids)
    }
}

#[cfg(test)]
mod tests {
    use super::ImagePullPolicy;

    #[test]
    fn image_pull_policy_parses_deployment_values() {
        for raw in ["never", "false", "0", "off", "no"] {
            assert_eq!(ImagePullPolicy::parse(raw), Some(ImagePullPolicy::Never));
        }
        for raw in [
            "missing",
            "if-missing",
            "if_missing",
            "true",
            "1",
            "on",
            "yes",
        ] {
            assert_eq!(
                ImagePullPolicy::parse(raw),
                Some(ImagePullPolicy::IfMissing)
            );
        }
        assert_eq!(
            ImagePullPolicy::parse("ALWAYS"),
            Some(ImagePullPolicy::Always)
        );
    }

    #[test]
    fn image_pull_policy_rejects_unknown_values() {
        assert_eq!(ImagePullPolicy::parse(""), None);
        assert_eq!(ImagePullPolicy::parse("sometimes"), None);
    }
}
