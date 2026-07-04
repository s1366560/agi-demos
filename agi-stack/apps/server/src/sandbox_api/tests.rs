use super::*;
use agistack_adapters_mem::InMemoryContainerRuntime;
use agistack_core::ports::CoreResult;
use tokio_tungstenite::tungstenite::handshake::server::{
    ErrorResponse as WsHandshakeErrorResponse, Request as WsHandshakeRequest,
    Response as WsHandshakeResponse,
};

type WsHandshakeResult = Result<WsHandshakeResponse, WsHandshakeErrorResponse>;
type WsOriginRequestSender = std::sync::mpsc::Sender<(String, Option<String>)>;
type WsDesktopRequestSender = std::sync::mpsc::Sender<(String, Option<String>, Option<String>)>;

#[allow(clippy::result_large_err)]
fn capture_ws_origin_request(
    req: &WsHandshakeRequest,
    response: WsHandshakeResponse,
    tx: &WsOriginRequestSender,
) -> WsHandshakeResult {
    let origin = req
        .headers()
        .get("origin")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    tx.send((req.uri().to_string(), origin)).unwrap();
    Ok(response)
}

#[allow(clippy::result_large_err)]
fn capture_desktop_ws_request(
    req: &WsHandshakeRequest,
    mut response: WsHandshakeResponse,
    tx: &WsDesktopRequestSender,
) -> WsHandshakeResult {
    let origin = req
        .headers()
        .get("origin")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let protocol = req
        .headers()
        .get("sec-websocket-protocol")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    response.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static(DESKTOP_WEBSOCKET_SUBPROTOCOL),
    );
    tx.send((req.uri().to_string(), origin, protocol)).unwrap();
    Ok(response)
}

#[allow(clippy::result_large_err)]
fn capture_mcp_ws_request(
    req: &WsHandshakeRequest,
    response: WsHandshakeResponse,
    tx: &std::sync::mpsc::Sender<String>,
) -> WsHandshakeResult {
    tx.send(req.uri().to_string()).unwrap();
    Ok(response)
}

#[derive(Default)]
struct StaticConfigSource {
    configs: Mutex<BTreeMap<String, ProjectSandboxConfig>>,
}

#[async_trait]
impl ProjectSandboxConfigSource for StaticConfigSource {
    async fn get_project_sandbox_config(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<Option<ProjectSandboxConfig>> {
        Ok(self
            .configs
            .lock()
            .map_err(|_| SandboxApiError::internal("config source mutex poisoned"))?
            .get(project_id)
            .cloned())
    }
}

#[derive(Default)]
struct RecordingRuntime {
    calls: Mutex<Vec<String>>,
}

impl RecordingRuntime {
    fn call_count(&self) -> usize {
        self.calls.lock().unwrap().len()
    }
}

#[async_trait]
impl ContainerRuntime for RecordingRuntime {
    async fn create(&self, _spec: &ContainerSpec) -> CoreResult<String> {
        self.calls.lock().unwrap().push("create".to_string());
        Ok("unexpected-container".to_string())
    }

    async fn start(&self, id: &str) -> CoreResult<()> {
        self.calls.lock().unwrap().push(format!("start:{id}"));
        Ok(())
    }

    async fn status(&self, id: &str) -> CoreResult<Option<ContainerStatus>> {
        self.calls.lock().unwrap().push(format!("status:{id}"));
        Ok(None)
    }

    async fn stop(&self, id: &str) -> CoreResult<()> {
        self.calls.lock().unwrap().push(format!("stop:{id}"));
        Ok(())
    }

    async fn remove(&self, id: &str) -> CoreResult<()> {
        self.calls.lock().unwrap().push(format!("remove:{id}"));
        Ok(())
    }

    async fn list(&self, _label: Option<(&str, &str)>) -> CoreResult<Vec<String>> {
        self.calls.lock().unwrap().push("list".to_string());
        Ok(Vec::new())
    }
}

struct RecordingConnector {
    urls: Mutex<Vec<String>>,
    output: String,
}

#[async_trait]
impl SandboxToolConnector for RecordingConnector {
    async fn connect_tool_host(&self, url: &str) -> SandboxApiResult<Arc<dyn ToolHost>> {
        self.urls
            .lock()
            .map_err(|_| SandboxApiError::internal("recording connector mutex poisoned"))?
            .push(url.to_string());
        Ok(Arc::new(StaticToolHost {
            output: self.output.clone(),
        }))
    }
}

struct StaticToolHost {
    output: String,
}

#[async_trait]
impl ToolHost for StaticToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["bash".to_string()]
    }

    async fn call(&self, _tool: &str, _input_json: &str) -> CoreResult<String> {
        Ok(self.output.clone())
    }
}

fn sample_info() -> ProjectSandboxInfo {
    ProjectSandboxInfo {
        sandbox_id: "s1".to_string(),
        project_id: "p1".to_string(),
        tenant_id: "t1".to_string(),
        sandbox_type: "cloud".to_string(),
        profile: SandboxProfile::Standard,
        state: ContainerState::Running,
        exit_code: None,
        created_at_ms: 0,
        started_at_ms: Some(0),
        last_accessed_at_ms: 0,
        metadata_json: json!({ "profile": "standard" }),
        local_config: json!({}),
        endpoint: None,
        websocket_url: None,
        mcp_port: None,
        desktop_port: None,
        terminal_port: None,
        desktop_url: None,
        terminal_url: None,
    }
}

mod proxy;
mod response;
mod service;
mod ws;
