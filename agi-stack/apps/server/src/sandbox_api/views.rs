use super::*;

#[derive(Debug, Deserialize)]
pub(super) struct EnsureSandboxRequest {
    pub(super) profile: Option<String>,
    #[serde(default = "default_auto_create")]
    _auto_create: bool,
}

fn default_auto_create() -> bool {
    true
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct ProjectSandboxResponse {
    pub(super) sandbox_id: String,
    pub(super) project_id: String,
    pub(super) tenant_id: String,
    pub(super) status: String,
    pub(super) endpoint: Option<String>,
    pub(super) websocket_url: Option<String>,
    pub(super) mcp_port: Option<u16>,
    pub(super) desktop_port: Option<u16>,
    pub(super) terminal_port: Option<u16>,
    pub(super) desktop_url: Option<String>,
    pub(super) terminal_url: Option<String>,
    pub(super) created_at: Option<String>,
    pub(super) last_accessed_at: Option<String>,
    pub(super) is_healthy: bool,
    pub(super) error_message: Option<String>,
}

impl From<ProjectSandboxInfo> for ProjectSandboxResponse {
    fn from(info: ProjectSandboxInfo) -> Self {
        let status = info.status_str().to_string();
        let is_healthy = info.healthy();
        let error_message = info.error_message();
        Self {
            sandbox_id: info.sandbox_id,
            project_id: info.project_id,
            tenant_id: info.tenant_id,
            status,
            endpoint: info.endpoint,
            websocket_url: info.websocket_url,
            mcp_port: info.mcp_port,
            desktop_port: info.desktop_port,
            terminal_port: info.terminal_port,
            desktop_url: info.desktop_url,
            terminal_url: info.terminal_url,
            created_at: Some(rfc3339(info.created_at_ms)),
            last_accessed_at: Some(rfc3339(info.last_accessed_at_ms)),
            is_healthy,
            error_message,
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct HealthCheckResponse {
    pub(super) project_id: String,
    pub(super) sandbox_id: String,
    pub(super) healthy: bool,
    pub(super) status: String,
    pub(super) checked_at: String,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct SandboxStatsResponse {
    pub(super) project_id: String,
    pub(super) sandbox_id: String,
    pub(super) status: String,
    pub(super) cpu_percent: f64,
    pub(super) memory_usage: u64,
    pub(super) memory_limit: u64,
    pub(super) memory_percent: f64,
    pub(super) disk_usage: Option<u64>,
    pub(super) disk_limit: Option<u64>,
    pub(super) disk_percent: Option<f64>,
    pub(super) network_rx_bytes: Option<u64>,
    pub(super) network_tx_bytes: Option<u64>,
    pub(super) pids: u64,
    pub(super) uptime_seconds: Option<i64>,
    pub(super) created_at: Option<String>,
    pub(super) collected_at: String,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct SandboxActionResponse {
    pub(super) success: bool,
    pub(super) message: String,
    pub(super) sandbox: Option<ProjectSandboxResponse>,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct ListProjectSandboxesResponse {
    pub(super) sandboxes: Vec<ProjectSandboxResponse>,
    pub(super) total: usize,
}

#[derive(Debug, Deserialize)]
pub(super) struct ExecuteToolRequest {
    pub(super) tool_name: String,
    #[serde(default)]
    pub(super) arguments: Value,
    #[serde(default = "default_tool_timeout")]
    pub(super) timeout: f64,
}

fn default_tool_timeout() -> f64 {
    30.0
}

#[derive(Debug, Serialize, PartialEq)]
pub(crate) struct ExecuteToolResponse {
    pub(crate) success: bool,
    pub(crate) content: Vec<Value>,
    pub(crate) is_error: bool,
    pub(crate) execution_time_ms: Option<i64>,
}

#[derive(Debug, Deserialize)]
pub(super) struct StartDesktopQuery {
    pub(super) resolution: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct TerminalWsQuery {
    pub(super) session_id: Option<String>,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct DesktopServiceResponse {
    pub(super) success: bool,
    pub(super) url: Option<String>,
    pub(super) display: String,
    pub(super) resolution: String,
    pub(super) port: u16,
    pub(super) audio_enabled: bool,
    pub(super) dynamic_resize: bool,
    pub(super) encoding: String,
}

impl DesktopServiceResponse {
    pub(super) fn from_info(info: &ProjectSandboxInfo, resolution: String) -> Self {
        Self {
            success: info.desktop_url.is_some(),
            url: info.desktop_url.clone(),
            display: DESKTOP_DEFAULT_DISPLAY.to_string(),
            resolution,
            port: info.desktop_port.unwrap_or(0),
            audio_enabled: false,
            dynamic_resize: true,
            encoding: DESKTOP_DEFAULT_ENCODING.to_string(),
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct TerminalServiceResponse {
    pub(super) success: bool,
    pub(super) url: Option<String>,
    pub(super) port: u16,
    pub(super) session_id: Option<String>,
}

impl TerminalServiceResponse {
    #[cfg(test)]
    pub(super) fn from_info(info: &ProjectSandboxInfo) -> Self {
        Self::from_info_with_session(info, None)
    }

    pub(super) fn from_info_with_session(
        info: &ProjectSandboxInfo,
        session_id: Option<String>,
    ) -> Self {
        Self {
            success: info.terminal_url.is_some(),
            url: info.terminal_url.clone(),
            port: info.terminal_port.unwrap_or(0),
            session_id,
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct SandboxServiceStopResponse {
    pub(super) success: bool,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct HttpServiceResponse {
    pub(super) service_id: String,
    pub(super) name: String,
    pub(super) source_type: HttpServiceSourceType,
    pub(super) status: String,
    pub(super) service_url: String,
    pub(super) preview_url: String,
    pub(super) ws_preview_url: Option<String>,
    pub(super) sandbox_id: Option<String>,
    pub(super) auto_open: bool,
    pub(super) restart_token: Option<String>,
    pub(super) updated_at: String,
}

impl From<HttpServiceProxyInfo> for HttpServiceResponse {
    fn from(info: HttpServiceProxyInfo) -> Self {
        Self {
            service_id: info.service_id,
            name: info.name,
            source_type: info.source_type,
            status: info.status,
            service_url: info.service_url,
            preview_url: info.preview_url,
            ws_preview_url: info.ws_preview_url,
            sandbox_id: info.sandbox_id,
            auto_open: info.auto_open,
            restart_token: info.restart_token,
            updated_at: info.updated_at,
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct ListHttpServicesResponse {
    pub(super) services: Vec<HttpServiceResponse>,
    pub(super) total: usize,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct HttpServiceActionResponse {
    pub(super) success: bool,
    pub(super) message: String,
    pub(super) service: Option<HttpServiceResponse>,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct HttpServicePreviewSessionResponse {
    pub(super) preview_url: String,
    pub(super) expires_in_seconds: i64,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct SandboxProxyAuthCookieResponse {
    pub(super) success: bool,
    pub(super) expires_in_seconds: i64,
}

#[derive(Debug, Deserialize)]
pub(super) struct ListProjectSandboxesQuery {
    pub(super) status: Option<String>,
    pub(super) limit: Option<i64>,
    pub(super) offset: Option<i64>,
}
