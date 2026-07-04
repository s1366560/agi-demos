use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use serde_json::{json, Map, Value};

use agistack_adapters_postgres::{
    PgProjectReadRepository, PgProjectSandboxRepository, ProjectSandboxRecord,
};
use agistack_core::ports::{ContainerState, ContainerStatus, PortBinding, ToolHost};

use super::{
    connection_url, datetime_from_ms, initial_metadata, local_config_websocket_url, local_metadata,
    normalize_sandbox_type, now_ms, port_field, profile_from_metadata,
    project_sandbox_config_from_record, sandbox_public_host, string_field, SandboxApiError,
    SandboxApiResult, SandboxProfile, DESKTOP_CONTAINER_PORT, MCP_CONTAINER_PORT,
    TERMINAL_CONTAINER_PORT,
};

#[derive(Debug, Clone)]
pub(super) struct SandboxRecord {
    pub(super) association_id: String,
    pub(super) sandbox_id: String,
    pub(super) project_id: String,
    pub(super) tenant_id: String,
    pub(super) sandbox_type: String,
    pub(super) profile: SandboxProfile,
    pub(super) status: String,
    pub(super) created_at_ms: i64,
    pub(super) started_at_ms: Option<i64>,
    pub(super) last_accessed_at_ms: i64,
    pub(super) metadata_json: Value,
    pub(super) local_config: Value,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct ProjectSandboxConfig {
    pub(super) sandbox_type: String,
    pub(super) local_config: Value,
}

impl ProjectSandboxConfig {
    pub(super) fn cloud() -> Self {
        Self {
            sandbox_type: "cloud".to_string(),
            local_config: json!({}),
        }
    }

    pub(super) fn is_local(&self) -> bool {
        self.sandbox_type.eq_ignore_ascii_case("local")
    }
}

#[async_trait]
pub(crate) trait ProjectSandboxConfigSource: Send + Sync {
    async fn get_project_sandbox_config(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<Option<ProjectSandboxConfig>>;
}

pub(crate) struct PgProjectSandboxConfigSource {
    projects: PgProjectReadRepository,
}

impl PgProjectSandboxConfigSource {
    pub(crate) fn new(projects: PgProjectReadRepository) -> Self {
        Self { projects }
    }
}

#[async_trait]
impl ProjectSandboxConfigSource for PgProjectSandboxConfigSource {
    async fn get_project_sandbox_config(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<Option<ProjectSandboxConfig>> {
        self.projects
            .get_by_id(project_id)
            .await
            .map_err(SandboxApiError::internal)
            .map(|record| record.map(project_sandbox_config_from_record))
    }
}

#[async_trait]
pub(super) trait SandboxToolConnector: Send + Sync {
    async fn connect_tool_host(&self, url: &str) -> SandboxApiResult<Arc<dyn ToolHost>>;
}

pub(super) struct WsMcpToolConnector;

#[async_trait]
impl SandboxToolConnector for WsMcpToolConnector {
    async fn connect_tool_host(&self, url: &str) -> SandboxApiResult<Arc<dyn ToolHost>> {
        let host = agistack_adapters_mcp::connect(url)
            .await
            .map_err(|_| SandboxApiError::internal("Execution failed"))?;
        Ok(Arc::new(host))
    }
}

#[async_trait]
pub(super) trait SandboxRegistry: Send + Sync {
    async fn get(&self, project_id: &str) -> SandboxApiResult<Option<SandboxRecord>>;
    async fn list(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> SandboxApiResult<Vec<SandboxRecord>>;
    async fn save(
        &self,
        record: &SandboxRecord,
        status: &str,
        error_message: Option<&str>,
    ) -> SandboxApiResult<()>;
    async fn delete(&self, project_id: &str) -> SandboxApiResult<bool>;
}

pub(super) struct InMemorySandboxRegistry {
    records: Mutex<BTreeMap<String, SandboxRecord>>,
}

impl InMemorySandboxRegistry {
    pub(super) fn new() -> Self {
        Self {
            records: Mutex::new(BTreeMap::new()),
        }
    }
}

#[async_trait]
impl SandboxRegistry for InMemorySandboxRegistry {
    async fn get(&self, project_id: &str) -> SandboxApiResult<Option<SandboxRecord>> {
        Ok(self
            .records
            .lock()
            .map_err(|_| SandboxApiError::internal("sandbox registry mutex poisoned"))?
            .get(project_id)
            .cloned())
    }

    async fn list(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> SandboxApiResult<Vec<SandboxRecord>> {
        let rows = self
            .records
            .lock()
            .map_err(|_| SandboxApiError::internal("sandbox registry mutex poisoned"))?
            .values()
            .filter(|record| record.tenant_id == tenant_id)
            .filter(|record| status.map(|s| record.status == s).unwrap_or(true))
            .cloned()
            .collect::<Vec<_>>();
        Ok(rows
            .into_iter()
            .skip(offset.max(0) as usize)
            .take(limit.max(0) as usize)
            .collect())
    }

    async fn save(
        &self,
        record: &SandboxRecord,
        status: &str,
        _error_message: Option<&str>,
    ) -> SandboxApiResult<()> {
        let mut record = record.clone();
        record.status = status.to_string();
        self.records
            .lock()
            .map_err(|_| SandboxApiError::internal("sandbox registry mutex poisoned"))?
            .insert(record.project_id.clone(), record);
        Ok(())
    }

    async fn delete(&self, project_id: &str) -> SandboxApiResult<bool> {
        Ok(self
            .records
            .lock()
            .map_err(|_| SandboxApiError::internal("sandbox registry mutex poisoned"))?
            .remove(project_id)
            .is_some())
    }
}

pub(super) struct PgSandboxRegistry {
    repo: PgProjectSandboxRepository,
}

impl PgSandboxRegistry {
    pub(super) fn new(repo: PgProjectSandboxRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl SandboxRegistry for PgSandboxRegistry {
    async fn get(&self, project_id: &str) -> SandboxApiResult<Option<SandboxRecord>> {
        self.repo
            .find_by_project(project_id)
            .await
            .map_err(SandboxApiError::internal)?
            .map(SandboxRecord::from_pg_record)
            .transpose()
    }

    async fn list(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> SandboxApiResult<Vec<SandboxRecord>> {
        self.repo
            .list_by_tenant(tenant_id, status, limit, offset)
            .await
            .map_err(SandboxApiError::internal)?
            .into_iter()
            .map(SandboxRecord::from_pg_record)
            .collect()
    }

    async fn save(
        &self,
        record: &SandboxRecord,
        status: &str,
        error_message: Option<&str>,
    ) -> SandboxApiResult<()> {
        let started_at = if status == "running" {
            Some(datetime_from_ms(
                record.started_at_ms.unwrap_or(record.last_accessed_at_ms),
            ))
        } else {
            record.started_at_ms.map(datetime_from_ms)
        };
        let db_record = ProjectSandboxRecord {
            id: record.association_id.clone(),
            project_id: record.project_id.clone(),
            tenant_id: record.tenant_id.clone(),
            sandbox_id: record.sandbox_id.clone(),
            sandbox_type: record.sandbox_type.clone(),
            status: status.to_string(),
            created_at: datetime_from_ms(record.created_at_ms),
            started_at,
            last_accessed_at: datetime_from_ms(record.last_accessed_at_ms),
            health_checked_at: Some(datetime_from_ms(now_ms())),
            error_message: error_message.map(str::to_string),
            metadata_json: record.metadata_with_profile(),
            local_config: record.local_config.clone(),
        };
        self.repo
            .upsert(db_record)
            .await
            .map_err(SandboxApiError::internal)?;
        Ok(())
    }

    async fn delete(&self, project_id: &str) -> SandboxApiResult<bool> {
        self.repo
            .delete_by_project(project_id)
            .await
            .map_err(SandboxApiError::internal)
    }
}

impl SandboxRecord {
    pub(super) fn new(
        sandbox_id: String,
        project_id: String,
        tenant_id: String,
        profile: SandboxProfile,
        now: i64,
    ) -> Self {
        Self {
            association_id: format!("agistack_sandbox_{project_id}"),
            sandbox_id,
            project_id,
            tenant_id,
            sandbox_type: "cloud".to_string(),
            profile,
            status: "creating".to_string(),
            created_at_ms: now,
            started_at_ms: None,
            last_accessed_at_ms: now,
            metadata_json: initial_metadata(profile),
            local_config: json!({}),
        }
    }

    fn from_pg_record(record: ProjectSandboxRecord) -> SandboxApiResult<Self> {
        let profile = profile_from_metadata(&record.metadata_json);
        Ok(Self {
            association_id: record.id,
            sandbox_id: record.sandbox_id,
            project_id: record.project_id,
            tenant_id: record.tenant_id,
            sandbox_type: normalize_sandbox_type(&record.sandbox_type),
            profile,
            status: record.status,
            created_at_ms: record.created_at.timestamp_millis(),
            started_at_ms: record.started_at.map(|value| value.timestamp_millis()),
            last_accessed_at_ms: record.last_accessed_at.timestamp_millis(),
            metadata_json: record.metadata_json,
            local_config: record.local_config,
        })
    }

    fn metadata_with_profile(&self) -> Value {
        let mut metadata = match self.metadata_json.clone() {
            Value::Object(map) => Value::Object(map),
            _ => Value::Object(Map::new()),
        };
        if let Value::Object(map) = &mut metadata {
            map.insert(
                "profile".to_string(),
                Value::String(self.profile.as_str().to_string()),
            );
            map.insert(
                "sandbox_type".to_string(),
                Value::String(self.sandbox_type.clone()),
            );
        }
        metadata
    }

    pub(super) fn new_local(
        sandbox_id: String,
        project_id: String,
        tenant_id: String,
        profile: SandboxProfile,
        now: i64,
        local_config: Value,
    ) -> Self {
        let mut record = Self {
            association_id: format!("agistack_sandbox_{project_id}"),
            sandbox_id,
            project_id,
            tenant_id,
            sandbox_type: "local".to_string(),
            profile,
            status: "running".to_string(),
            created_at_ms: now,
            started_at_ms: Some(now),
            last_accessed_at_ms: now,
            metadata_json: local_metadata(profile, &local_config),
            local_config,
        };
        record.project_local_connection_fields();
        record
    }

    pub(super) fn apply_runtime_ports(&mut self, ports: &[PortBinding]) {
        let host = sandbox_public_host();
        for binding in ports {
            if binding.host_port == 0 {
                continue;
            }
            match binding.container_port {
                MCP_CONTAINER_PORT => self.set_mcp_port(binding.host_port, &host),
                DESKTOP_CONTAINER_PORT => self.set_desktop_port(binding.host_port, &host),
                TERMINAL_CONTAINER_PORT => self.set_terminal_port(binding.host_port, &host),
                _ => {}
            }
        }
    }

    fn metadata_object_mut(&mut self) -> &mut Map<String, Value> {
        if !matches!(self.metadata_json, Value::Object(_)) {
            self.metadata_json = Value::Object(Map::new());
        }
        match &mut self.metadata_json {
            Value::Object(map) => map,
            _ => unreachable!("metadata_json normalized to object"),
        }
    }

    fn set_mcp_port(&mut self, port: u16, host: &str) {
        let url = format!("ws://{host}:{port}");
        let map = self.metadata_object_mut();
        map.insert("mcp_port".to_string(), Value::from(port));
        map.insert("endpoint".to_string(), Value::String(url.clone()));
        map.insert("websocket_url".to_string(), Value::String(url.clone()));
        map.insert("mcp_url".to_string(), Value::String(url));
    }

    pub(super) fn project_local_connection_fields(&mut self) {
        if !self.is_local() {
            return;
        }
        let Some(url) = local_config_websocket_url(&self.local_config) else {
            return;
        };
        let port = port_field(&self.local_config, "port");
        let map = self.metadata_object_mut();
        map.insert("endpoint".to_string(), Value::String(url.clone()));
        map.insert("websocket_url".to_string(), Value::String(url.clone()));
        map.insert("mcp_url".to_string(), Value::String(url));
        if let Some(port) = port {
            map.insert("mcp_port".to_string(), Value::from(port));
        }
    }

    fn set_desktop_port(&mut self, port: u16, host: &str) {
        let map = self.metadata_object_mut();
        map.insert("desktop_port".to_string(), Value::from(port));
        map.insert(
            "desktop_url".to_string(),
            Value::String(format!("https://{host}:{port}")),
        );
    }

    fn set_terminal_port(&mut self, port: u16, host: &str) {
        let map = self.metadata_object_mut();
        map.insert("terminal_port".to_string(), Value::from(port));
        map.insert(
            "terminal_url".to_string(),
            Value::String(format!("ws://{host}:{port}")),
        );
    }

    pub(super) fn endpoint(&self) -> Option<String> {
        connection_url(&self.metadata_json, &self.local_config)
    }

    pub(super) fn websocket_url(&self) -> Option<String> {
        string_field(&self.metadata_json, "websocket_url")
            .or_else(|| string_field(&self.metadata_json, "endpoint"))
            .or_else(|| string_field(&self.metadata_json, "mcp_url"))
            .or_else(|| local_config_websocket_url(&self.local_config))
    }

    pub(super) fn mcp_port(&self) -> Option<u16> {
        port_field(&self.metadata_json, "mcp_port")
            .or_else(|| port_field(&self.local_config, "port"))
    }

    pub(super) fn desktop_port(&self) -> Option<u16> {
        port_field(&self.metadata_json, "desktop_port")
    }

    pub(super) fn terminal_port(&self) -> Option<u16> {
        port_field(&self.metadata_json, "terminal_port")
    }

    pub(super) fn desktop_url(&self) -> Option<String> {
        string_field(&self.metadata_json, "desktop_url")
    }

    pub(super) fn terminal_url(&self) -> Option<String> {
        string_field(&self.metadata_json, "terminal_url")
    }

    pub(super) fn is_local(&self) -> bool {
        self.sandbox_type.eq_ignore_ascii_case("local")
    }

    pub(super) fn synthetic_container_status(&self) -> ContainerStatus {
        let state = match self.status.as_str() {
            "running" => ContainerState::Running,
            "creating" | "pending" | "connecting" => ContainerState::Created,
            "stopped" | "terminated" | "orphan" => ContainerState::Exited,
            _ => ContainerState::Unknown,
        };
        ContainerStatus {
            id: self.sandbox_id.clone(),
            running: matches!(state, ContainerState::Running),
            state,
            exit_code: None,
            ports: Vec::new(),
        }
    }
}
