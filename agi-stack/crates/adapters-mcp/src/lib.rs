//! MCP-over-WebSocket adapter for the [`ToolHost`] port — a **remote tool
//! provider** (F9 · P5).
//!
//! This is the third backend of the one `ToolHost` port, alongside the native
//! registry (`agistack-plugin-host`) and the wasm sandbox
//! (`agistack-adapters-wasmtime`). Where those host *local* tools, this one
//! dispatches to a **remote** [Model Context Protocol] server over a WebSocket
//! (JSON-RPC 2.0) — the same `sandbox-mcp-server` the Python backend drives (file
//! ops, code intel, terminal, git, MCP-server management, ...). The agent loop is
//! unchanged: it still calls one `dyn ToolHost`, so the strangler can move MCP
//! tool dispatch from Python to Rust with zero protocol change.
//!
//! ## Protocol
//! On [`connect`] the client performs the MCP handshake once:
//! `initialize` → `notifications/initialized` → `tools/list`, and **caches** the
//! advertised tool names (the server declares `tools.listChanged = false`, so a
//! one-shot cache is correct). Thereafter:
//! - [`list_tools`](WsMcpToolHost::list_tools) returns the cached names (sync, no
//!   I/O — matching the port's synchronous signature).
//! - [`call`](WsMcpToolHost::call) issues `tools/call { name, arguments }`,
//!   correlates the reply by JSON-RPC `id`, and returns the `result` object as a
//!   JSON string. A tool-level failure (`result.isError == true`) or a
//!   JSON-RPC-level `error` maps to [`CoreError::Tool`].
//!
//! Everything here is `tokio`-bound and lives strictly outside the core
//! (ADR-0001); `tokio-tungstenite` never appears in a port signature.
//!
//! [Model Context Protocol]: https://modelcontextprotocol.io

use std::sync::atomic::{AtomicI64, Ordering};

use async_trait::async_trait;
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::net::TcpStream;
use tokio::sync::{mpsc, oneshot};
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{connect_async, MaybeTlsStream, WebSocketStream};

use agistack_core::ports::{CoreError, CoreResult, ToolHost};

type Ws = WebSocketStream<MaybeTlsStream<TcpStream>>;

/// The MCP protocol revision this client negotiates.
const PROTOCOL_VERSION: &str = "2024-11-05";
const REQUEST_BUFFER: usize = 32;

/// Map any transport / protocol failure to the port-level [`CoreError::Tool`],
/// keeping the concrete `tungstenite` types out of the core contract.
fn gerr<E: std::fmt::Debug>(e: E) -> CoreError {
    CoreError::Tool(format!("{e:?}"))
}

/// Concatenate the `text` fields of an MCP result `content` array (the
/// human-readable payload of a `tools/call` reply).
fn extract_text(result: &Value) -> String {
    result
        .get("content")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|c| c.get("text").and_then(Value::as_str))
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default()
}

/// Read frames from `ws` until a JSON-RPC message whose `id` equals `want_id`
/// arrives, returning the parsed value. Notifications (no `id`) and unrelated
/// ids are skipped. Ping/close/other frames are handled or surfaced as errors.
async fn read_response(ws: &mut Ws, want_id: i64) -> CoreResult<Value> {
    while let Some(frame) = ws.next().await {
        let msg = frame.map_err(gerr)?;
        let text = match msg {
            Message::Text(t) => t.to_string(),
            Message::Binary(b) => String::from_utf8_lossy(&b).to_string(),
            Message::Close(_) => {
                return Err(CoreError::Tool("mcp connection closed".into()));
            }
            // Ping/Pong/Frame carry no JSON-RPC payload: keep waiting.
            _ => continue,
        };
        let value: Value =
            serde_json::from_str(&text).map_err(|e| CoreError::Tool(format!("bad json: {e}")))?;
        match value.get("id").and_then(Value::as_i64) {
            Some(id) if id == want_id => return Ok(value),
            _ => continue,
        }
    }
    Err(CoreError::Tool("mcp stream ended before response".into()))
}

/// A [`ToolHost`] backed by a remote MCP server over WebSocket.
pub struct WsMcpToolHost {
    requests: mpsc::Sender<McpRequest>,
    tools: Vec<String>,
    next_id: AtomicI64,
    server_name: String,
}

struct McpRequest {
    id: i64,
    tool: String,
    arguments: Value,
    reply: oneshot::Sender<CoreResult<Value>>,
}

/// Connect to an MCP server at `url` (e.g. `ws://localhost:8765`), perform the
/// handshake, and cache its advertised tools.
pub async fn connect(url: &str) -> CoreResult<WsMcpToolHost> {
    let (mut ws, _resp) = connect_async(url).await.map_err(gerr)?;

    // 1. initialize
    let init = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": { "name": "agistack", "version": env!("CARGO_PKG_VERSION") }
        }
    });
    ws.send(Message::Text(init.to_string()))
        .await
        .map_err(gerr)?;
    let init_resp = read_response(&mut ws, 1).await?;
    let server_name = init_resp
        .pointer("/result/serverInfo/name")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();

    // 2. notifications/initialized (no id — a notification)
    ws.send(Message::Text(
        json!({ "jsonrpc": "2.0", "method": "notifications/initialized" }).to_string(),
    ))
    .await
    .map_err(gerr)?;

    // 3. tools/list → cache names
    ws.send(Message::Text(
        json!({ "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {} }).to_string(),
    ))
    .await
    .map_err(gerr)?;
    let tools_resp = read_response(&mut ws, 2).await?;
    let tools = tools_resp
        .pointer("/result/tools")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(|t| t.get("name").and_then(Value::as_str).map(String::from))
                .collect()
        })
        .unwrap_or_default();

    let (requests, worker_rx) = mpsc::channel(REQUEST_BUFFER);
    tokio::spawn(run_mcp_connection(ws, worker_rx));

    Ok(WsMcpToolHost {
        requests,
        tools,
        next_id: AtomicI64::new(3),
        server_name,
    })
}

async fn run_mcp_connection(mut ws: Ws, mut requests: mpsc::Receiver<McpRequest>) {
    while let Some(request) = requests.recv().await {
        let result = send_mcp_call(&mut ws, &request).await;
        let should_stop = result.is_err();
        let _ = request.reply.send(result);
        if should_stop {
            break;
        }
    }
}

async fn send_mcp_call(ws: &mut Ws, request: &McpRequest) -> CoreResult<Value> {
    let req = json!({
        "jsonrpc": "2.0",
        "id": request.id,
        "method": "tools/call",
        "params": { "name": request.tool, "arguments": request.arguments }
    });
    ws.send(Message::Text(req.to_string()))
        .await
        .map_err(gerr)?;
    read_response(ws, request.id).await
}

impl WsMcpToolHost {
    /// The `name` the server reported in `initialize`'s `serverInfo`.
    pub fn server_name(&self) -> &str {
        &self.server_name
    }
}

#[async_trait]
impl ToolHost for WsMcpToolHost {
    fn list_tools(&self) -> Vec<String> {
        self.tools.clone()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let arguments: Value = if input_json.trim().is_empty() {
            json!({})
        } else {
            serde_json::from_str(input_json)
                .map_err(|e| CoreError::Tool(format!("invalid tool input json: {e}")))?
        };

        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (reply, response) = oneshot::channel();
        self.requests
            .send(McpRequest {
                id,
                tool: tool.to_string(),
                arguments,
                reply,
            })
            .await
            .map_err(|_| CoreError::Tool("mcp connection task is closed".into()))?;
        let resp = response
            .await
            .map_err(|_| CoreError::Tool("mcp connection task dropped response".into()))??;

        // JSON-RPC-level error (malformed request, method not found, ...).
        if let Some(err) = resp.get("error").filter(|e| !e.is_null()) {
            return Err(CoreError::Tool(format!("mcp error: {err}")));
        }
        let result = resp.get("result").cloned().unwrap_or(Value::Null);
        // Tool-level error (e.g. unknown tool, sandbox policy violation).
        if result
            .get("isError")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            return Err(CoreError::Tool(extract_text(&result)));
        }
        Ok(result.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::extract_text;
    use serde_json::json;

    #[test]
    fn extract_text_joins_content_items() {
        let result = json!({
            "content": [{ "type": "text", "text": "line-a" }, { "type": "text", "text": "line-b" }],
            "isError": false
        });
        assert_eq!(extract_text(&result), "line-a\nline-b");
    }

    #[test]
    fn extract_text_skips_non_text_and_handles_empty() {
        let result = json!({ "content": [{ "type": "image", "data": "..." }] });
        assert_eq!(extract_text(&result), "");
        assert_eq!(extract_text(&json!({})), "");
    }

    #[test]
    fn extract_text_reads_error_payload() {
        // The `isError: true` text is what `call` surfaces as CoreError::Tool.
        let result =
            json!({ "content": [{ "type": "text", "text": "Unknown tool: x" }], "isError": true });
        assert_eq!(extract_text(&result), "Unknown tool: x");
    }
}
