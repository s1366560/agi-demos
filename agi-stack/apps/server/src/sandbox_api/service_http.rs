use super::*;

impl ProjectSandboxService {
    pub(super) async fn register_http_service(
        &self,
        project_id: &str,
        tenant_id: &str,
        req: RegisterHttpServiceRequest,
    ) -> SandboxApiResult<HttpServiceProxyInfo> {
        validate_http_service_name(&req.name)?;
        let service_id = normalize_http_service_id(req.service_id.as_deref())?;
        let now = now_ms();
        let updated_at = python_utc_offset_string(now);
        let restart_token = Some(now.to_string());

        let (service_url, preview_url, ws_preview_url, sandbox_id) = match req.source_type {
            HttpServiceSourceType::SandboxInternal => {
                let internal_port = req.internal_port.ok_or_else(|| {
                    SandboxApiError::bad_request(
                        "internal_port is required for sandbox_internal services",
                    )
                })?;
                let internal_scheme = normalize_internal_scheme(&req.internal_scheme)?;
                let info = self.ensure(project_id, tenant_id, None).await?;
                let host = sandbox_internal_service_host(&info);
                let path_prefix = normalize_path_prefix(&req.path_prefix);
                (
                    format!("{internal_scheme}://{host}:{internal_port}{path_prefix}"),
                    build_http_preview_proxy_url(project_id, &service_id),
                    Some(build_http_preview_ws_proxy_url(project_id, &service_id)),
                    Some(info.sandbox_id),
                )
            }
            HttpServiceSourceType::ExternalUrl => {
                let external_url = req.external_url.as_deref().ok_or_else(|| {
                    SandboxApiError::bad_request(
                        "external_url is required for external_url services",
                    )
                })?;
                let service_url = validate_external_http_url(external_url)?;
                (service_url.clone(), service_url, None, None)
            }
        };

        let info = HttpServiceProxyInfo {
            service_id: service_id.clone(),
            name: req.name,
            source_type: req.source_type,
            status: "running".to_string(),
            service_url,
            preview_url,
            ws_preview_url,
            sandbox_id,
            auto_open: req.auto_open,
            restart_token,
            updated_at,
        };
        self.upsert_http_service(project_id, info).await
    }

    pub(super) async fn upsert_http_service(
        &self,
        project_id: &str,
        info: HttpServiceProxyInfo,
    ) -> SandboxApiResult<HttpServiceProxyInfo> {
        self.http_registry.upsert(project_id, info).await
    }

    pub(super) async fn list_http_services(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<Vec<HttpServiceProxyInfo>> {
        self.http_registry.list(project_id).await
    }

    pub(super) async fn get_http_service(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        self.http_registry.get(project_id, service_id).await
    }

    pub(super) async fn remove_http_service(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        self.http_registry.remove(project_id, service_id).await
    }

    pub(super) async fn preview_session(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<HttpServicePreviewSessionResponse> {
        let service = self
            .get_http_service(project_id, service_id)
            .await?
            .ok_or_else(http_service_not_found)?;
        if service.source_type == HttpServiceSourceType::ExternalUrl {
            return Ok(HttpServicePreviewSessionResponse {
                preview_url: service.preview_url,
                expires_in_seconds: 0,
            });
        }
        let token = agistack_adapters_secrets::generate_urlsafe_token(32);
        let expires_in_seconds = preview_session_ttl_seconds();
        self.http_registry
            .create_preview_session(
                &token,
                PreviewSessionRecord {
                    project_id: project_id.to_string(),
                    service_id: service_id.to_string(),
                    expires_at_ms: now_ms() + expires_in_seconds * 1000,
                },
                expires_in_seconds,
            )
            .await?;
        Ok(HttpServicePreviewSessionResponse {
            preview_url: append_query_param(
                &build_http_preview_proxy_url(project_id, service_id),
                PREVIEW_SESSION_QUERY_PARAM,
                &token,
            ),
            expires_in_seconds,
        })
    }

    pub(super) async fn create_terminal_session(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<TerminalSessionRecord> {
        let ttl_seconds = terminal_session_ttl_seconds();
        let now = now_ms();
        let record = TerminalSessionRecord::new(
            project_id.to_string(),
            new_terminal_session_id(),
            TerminalSize::default(),
            false,
            now,
            ttl_seconds,
        );
        self.http_registry
            .upsert_terminal_session(record.clone(), ttl_seconds)
            .await?;
        Ok(record)
    }

    pub(super) async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> SandboxApiResult<Option<TerminalSessionRecord>> {
        let now = now_ms();
        Ok(self
            .http_registry
            .get_terminal_session(project_id, session_id)
            .await?
            .filter(|session| session.project_id == project_id)
            .filter(|session| session.session_id == session_id)
            .filter(|session| session.expires_at_ms > now))
    }

    pub(super) fn terminal_session_recorder(
        &self,
        project_id: String,
        session_id: String,
    ) -> TerminalSessionRecorder {
        TerminalSessionRecorder::new(
            self.http_registry.clone(),
            project_id,
            session_id,
            terminal_session_ttl_seconds(),
        )
    }

    pub(super) async fn create_mcp_upstream_token(
        &self,
        project_id: &str,
        sandbox_id: &str,
    ) -> SandboxApiResult<McpUpstreamTokenRecord> {
        let ttl_seconds = mcp_upstream_token_ttl_seconds();
        let now = now_ms();
        let record = McpUpstreamTokenRecord::new(
            project_id.to_string(),
            sandbox_id.to_string(),
            now,
            ttl_seconds,
        );
        self.http_registry
            .create_mcp_upstream_token(record.clone(), ttl_seconds)
            .await?;
        Ok(record)
    }
}
