use std::time::{Duration, Instant};

use super::*;

impl ProjectSandboxService {
    pub(crate) fn new(runtime: Arc<dyn ContainerRuntime>, image: impl Into<String>) -> Self {
        Self::with_registry(runtime, image, Arc::new(InMemorySandboxRegistry::new()))
    }

    pub(crate) fn with_postgres(
        runtime: Arc<dyn ContainerRuntime>,
        image: impl Into<String>,
        repo: PgProjectSandboxRepository,
    ) -> Self {
        Self::with_registry(runtime, image, Arc::new(PgSandboxRegistry::new(repo)))
    }

    pub(super) fn with_registry(
        runtime: Arc<dyn ContainerRuntime>,
        image: impl Into<String>,
        registry: Arc<dyn SandboxRegistry>,
    ) -> Self {
        Self {
            runtime,
            tool_host: None,
            tool_connector: None,
            image: image.into(),
            registry,
            http_registry: in_memory_http_service_registry(),
            config_source: None,
            runtime_auth: None,
        }
    }

    pub(crate) fn with_runtime_auth_secret(
        mut self,
        secret: impl AsRef<str>,
    ) -> Result<Self, &'static str> {
        self.runtime_auth = Some(SandboxRuntimeAuth::try_new(secret)?);
        Ok(self)
    }

    pub(crate) fn with_http_service_registry(
        mut self,
        registry: SharedHttpServiceRegistry,
    ) -> Self {
        self.http_registry = registry;
        self
    }

    pub(crate) fn with_project_config_source(
        mut self,
        source: Arc<dyn ProjectSandboxConfigSource>,
    ) -> Self {
        self.config_source = Some(source);
        self
    }

    pub(crate) fn with_tool_host(mut self, tool_host: Arc<dyn ToolHost>) -> Self {
        self.tool_host = Some(tool_host);
        self
    }

    pub(crate) fn with_ws_mcp_connector(mut self) -> Self {
        self.tool_connector = Some(Arc::new(CachingToolConnector::new(Arc::new(
            WsMcpToolConnector,
        ))));
        self
    }

    #[cfg(test)]
    pub(super) fn with_tool_connector(mut self, connector: Arc<dyn SandboxToolConnector>) -> Self {
        self.tool_connector = Some(connector);
        self
    }

    pub(super) async fn get(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<Option<ProjectSandboxInfo>> {
        let record = self.registry.get(project_id).await?;
        match record {
            None => Ok(None),
            Some(record) => {
                let status = self.status_or_gone(&record).await?;
                let Some(status) = status else {
                    self.evict_cached_tool_host(
                        record.websocket_url().as_deref(),
                        record.endpoint().as_deref(),
                    )
                    .await;
                    self.registry.delete(project_id).await?;
                    return Ok(None);
                };
                let mut touched = record;
                touched.last_accessed_at_ms = now_ms();
                let info =
                    self.attach_runtime_auth(ProjectSandboxInfo::from_record(touched, status));
                let status = info.status_str();
                let error_message = info.error_message();
                let record = info.to_record();
                self.registry
                    .save(&record, status, error_message.as_deref())
                    .await?;
                Ok(Some(info))
            }
        }
    }

    pub(super) async fn list(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> SandboxApiResult<Vec<ProjectSandboxInfo>> {
        let records = self.registry.list(tenant_id, status, limit, offset).await?;
        let mut out = Vec::with_capacity(records.len());
        for record in records {
            let project_id = record.project_id.clone();
            let Some(status) = self.status_or_gone(&record).await? else {
                self.evict_cached_tool_host(
                    record.websocket_url().as_deref(),
                    record.endpoint().as_deref(),
                )
                .await;
                self.registry.delete(&project_id).await?;
                continue;
            };
            let info = self.attach_runtime_auth(ProjectSandboxInfo::from_record(record, status));
            let computed_status = info.status_str();
            let error_message = info.error_message();
            let record = info.to_record();
            self.registry
                .save(&record, computed_status, error_message.as_deref())
                .await?;
            out.push(info);
        }
        Ok(out)
    }

    pub(super) async fn ensure(
        &self,
        project_id: &str,
        tenant_id: &str,
        profile: Option<SandboxProfile>,
    ) -> SandboxApiResult<ProjectSandboxInfo> {
        let profile = profile.unwrap_or(SandboxProfile::Standard);
        let project_config = self.project_sandbox_config(project_id).await?;
        if project_config.is_local() {
            return self
                .ensure_local(project_id, tenant_id, profile, project_config.local_config)
                .await;
        }
        self.discard_local_record_for_cloud_project(project_id)
            .await?;
        if let Some(info) = self.get(project_id).await? {
            if matches!(info.state, ContainerState::Running) {
                return Ok(info);
            }
            if info.is_local() {
                return self
                    .ensure_local(project_id, tenant_id, profile, info.local_config)
                    .await;
            }
            self.evict_cached_tool_host(info.websocket_url.as_deref(), info.endpoint.as_deref())
                .await;
            self.runtime
                .start(&info.sandbox_id)
                .await
                .map_err(SandboxApiError::internal)?;
            return self
                .get(project_id)
                .await?
                .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND));
        }

        let now = now_ms();
        let runtime_auth_token = self.runtime_auth_token(project_id, tenant_id)?;
        let spec = sandbox_container_spec(
            &self.image,
            project_id,
            tenant_id,
            profile,
            &runtime_auth_token,
        );
        let sandbox_id = self
            .runtime
            .create(&spec)
            .await
            .map_err(SandboxApiError::internal)?;
        let record = SandboxRecord::new(
            sandbox_id.clone(),
            project_id.to_string(),
            tenant_id.to_string(),
            profile,
            now,
        );
        self.registry.save(&record, "creating", None).await?;
        self.runtime
            .start(&sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.get(project_id)
            .await?
            .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))
    }

    async fn project_sandbox_config(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<ProjectSandboxConfig> {
        let Some(source) = self.config_source.as_ref() else {
            return Ok(ProjectSandboxConfig::cloud());
        };
        Ok(source
            .get_project_sandbox_config(project_id)
            .await?
            .unwrap_or_else(ProjectSandboxConfig::cloud))
    }

    fn runtime_auth_token(
        &self,
        project_id: &str,
        tenant_id: &str,
    ) -> SandboxApiResult<SandboxRuntimeToken> {
        self.runtime_auth
            .as_ref()
            .map(|auth| auth.token_for(project_id, tenant_id))
            .ok_or_else(|| {
                SandboxApiError::service_unavailable(
                    "Sandbox runtime authentication is not configured",
                )
            })
    }

    fn attach_runtime_auth(&self, mut info: ProjectSandboxInfo) -> ProjectSandboxInfo {
        if !info.is_local() {
            if let Some(runtime_auth) = self.runtime_auth.as_ref() {
                info.runtime_auth_token =
                    Some(runtime_auth.token_for(&info.project_id, &info.tenant_id));
            }
        }
        info
    }

    async fn ensure_local(
        &self,
        project_id: &str,
        tenant_id: &str,
        profile: SandboxProfile,
        local_config: Value,
    ) -> SandboxApiResult<ProjectSandboxInfo> {
        let now = now_ms();
        let normalized_local_config = normalize_local_config(local_config);
        let existing = self.registry.get(project_id).await?;
        let existing_local = if let Some(existing) = existing {
            if !existing.is_local() {
                self.evict_cached_tool_host(
                    existing.websocket_url().as_deref(),
                    existing.endpoint().as_deref(),
                )
                .await;
                self.runtime
                    .stop(&existing.sandbox_id)
                    .await
                    .map_err(SandboxApiError::internal)?;
                self.runtime
                    .remove(&existing.sandbox_id)
                    .await
                    .map_err(SandboxApiError::internal)?;
                None
            } else {
                Some(existing)
            }
        } else {
            None
        };

        let mut record = existing_local.unwrap_or_else(|| {
            SandboxRecord::new_local(
                format!("local-{project_id}"),
                project_id.to_string(),
                tenant_id.to_string(),
                profile,
                now,
                normalized_local_config.clone(),
            )
        });
        record.sandbox_type = "local".to_string();
        record.tenant_id = tenant_id.to_string();
        record.profile = profile;
        record.status = "running".to_string();
        record.started_at_ms = Some(record.started_at_ms.unwrap_or(now));
        record.last_accessed_at_ms = now;
        record.local_config = normalized_local_config;
        record.metadata_json = local_metadata(record.profile, &record.local_config);
        record.project_local_connection_fields();

        self.registry.save(&record, "running", None).await?;
        Ok(ProjectSandboxInfo::from_record(
            record.clone(),
            record.synthetic_container_status(),
        ))
    }

    async fn discard_local_record_for_cloud_project(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<()> {
        let Some(record) = self.registry.get(project_id).await? else {
            return Ok(());
        };
        if record.is_local() {
            self.evict_cached_tool_host(
                record.websocket_url().as_deref(),
                record.endpoint().as_deref(),
            )
            .await;
            self.registry.delete(project_id).await?;
        }
        Ok(())
    }

    pub(super) async fn restart(&self, project_id: &str) -> SandboxApiResult<ProjectSandboxInfo> {
        let mut record = self
            .registry
            .get(project_id)
            .await?
            .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
        if record.is_local() {
            record.status = "running".to_string();
            record.last_accessed_at_ms = now_ms();
            self.registry.save(&record, "running", None).await?;
            return Ok(ProjectSandboxInfo::from_record(
                record.clone(),
                record.synthetic_container_status(),
            ));
        }
        self.evict_cached_tool_host(
            record.websocket_url().as_deref(),
            record.endpoint().as_deref(),
        )
        .await;
        self.runtime
            .stop(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.runtime
            .start(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.get(project_id)
            .await?
            .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))
    }

    pub(super) async fn terminate(&self, project_id: &str) -> SandboxApiResult<bool> {
        let record = self.registry.get(project_id).await?;
        let Some(record) = record else {
            return Ok(false);
        };
        self.evict_cached_tool_host(
            record.websocket_url().as_deref(),
            record.endpoint().as_deref(),
        )
        .await;
        if record.is_local() {
            self.registry.save(&record, "terminated", None).await?;
            self.registry.delete(project_id).await?;
            return Ok(true);
        }
        self.runtime
            .stop(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.runtime
            .remove(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.registry.save(&record, "terminated", None).await?;
        self.registry.delete(project_id).await?;
        Ok(true)
    }

    async fn execute_tool_with_max_timeout(
        &self,
        project_id: &str,
        tool_name: &str,
        arguments: &Value,
        timeout_seconds: f64,
        max_timeout_seconds: f64,
    ) -> SandboxApiResult<ExecuteToolResponse> {
        if !(1.0..=max_timeout_seconds).contains(&timeout_seconds) || !timeout_seconds.is_finite() {
            return Err(SandboxApiError::bad_request(format!(
                "Execution timeout must be between 1 and {max_timeout_seconds:.0} seconds"
            )));
        }

        let info = self
            .get(project_id)
            .await?
            .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
        if !info.healthy() {
            return Err(SandboxApiError::internal("Execution failed"));
        }
        let host = self.tool_host_for(&info).await?;

        let input_json = arguments.to_string();
        let started = Instant::now();
        let timeout = Duration::from_millis((timeout_seconds * 1_000.0).ceil() as u64);
        let raw = tokio::time::timeout(timeout, host.call(tool_name, &input_json))
            .await
            .map_err(|_| SandboxApiError::internal("Execution failed"))?
            .map_err(|_| SandboxApiError::internal("Execution failed"))?;
        let elapsed = started.elapsed().as_millis().min(i64::MAX as u128) as i64;
        Ok(normalize_tool_result(&raw, elapsed))
    }

    pub(super) async fn execute_tool(
        &self,
        project_id: &str,
        tool_name: &str,
        arguments: &Value,
        timeout_seconds: f64,
    ) -> SandboxApiResult<ExecuteToolResponse> {
        self.execute_tool_with_max_timeout(project_id, tool_name, arguments, timeout_seconds, 300.0)
            .await
    }

    pub(crate) async fn execute_pipeline_tool(
        &self,
        project_id: &str,
        tool_name: &str,
        arguments: &Value,
        timeout_seconds: f64,
    ) -> SandboxApiResult<ExecuteToolResponse> {
        self.execute_tool_with_max_timeout(
            project_id,
            tool_name,
            arguments,
            timeout_seconds,
            3_600.0,
        )
        .await
    }

    pub(super) async fn get_http_service_by_preview_label(
        &self,
        project_id: &str,
        service_label: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        Ok(self
            .list_http_services(project_id)
            .await?
            .into_iter()
            .find(|service| preview_service_host_label(&service.service_id) == service_label))
    }

    pub(super) async fn preview_session_matches_service(
        &self,
        token: Option<&str>,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<PreviewSessionRecord>> {
        let Some(token) = token.filter(|token| !token.is_empty()) else {
            return Ok(None);
        };
        let now = now_ms();
        Ok(self
            .http_registry
            .get_preview_session(token)
            .await?
            .filter(|session| session.project_id == project_id && session.service_id == service_id)
            .filter(|session| session.expires_at_ms > now))
    }

    async fn tool_host_for(
        &self,
        info: &ProjectSandboxInfo,
    ) -> SandboxApiResult<Arc<dyn ToolHost>> {
        let endpoint = info.websocket_url.as_ref().or(info.endpoint.as_ref());
        if let (Some(url), Some(connector)) = (endpoint, self.tool_connector.as_ref()) {
            return connector.connect_tool_host(url).await;
        }
        self.tool_host
            .clone()
            .ok_or_else(|| SandboxApiError::internal("Sandbox tool host is not configured"))
    }

    /// Drop the cached tool-host connection for a sandbox whose runtime state
    /// is about to be torn down (stop/restart/terminate/gone). Mirrors
    /// `tool_host_for`'s endpoint precedence so the evicted key matches the
    /// one the connection was cached under.
    async fn evict_cached_tool_host(&self, websocket_url: Option<&str>, endpoint: Option<&str>) {
        let Some(connector) = self.tool_connector.as_ref() else {
            return;
        };
        if let Some(url) = websocket_url.or(endpoint) {
            connector.evict_tool_host(url).await;
        }
    }

    async fn status_or_gone(
        &self,
        record: &SandboxRecord,
    ) -> SandboxApiResult<Option<ContainerStatus>> {
        if record.is_local() {
            return Ok(Some(record.synthetic_container_status()));
        }
        self.runtime
            .status(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)
    }
}
