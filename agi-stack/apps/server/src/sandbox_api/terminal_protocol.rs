use serde::Deserialize;
use serde_json::json;
use tokio_tungstenite::tungstenite::protocol::Message as TungsteniteMessage;

use super::{
    now_ms, SandboxApiError, SandboxApiResult, SharedHttpServiceRegistry, TERMINAL_DEFAULT_COLS,
    TERMINAL_DEFAULT_ROWS, TTYD_INPUT_COMMAND, TTYD_PREFERENCES_COMMAND, TTYD_RESIZE_COMMAND,
};

#[derive(Debug, Deserialize)]
pub(super) struct TerminalClientWsMessage {
    #[serde(rename = "type")]
    pub(super) kind: String,
    pub(super) data: Option<String>,
    pub(super) cols: Option<u16>,
    pub(super) rows: Option<u16>,
}

pub(super) fn try_new_terminal_session_id() -> SandboxApiResult<String> {
    Ok(agistack_adapters_secrets::try_generate_uuid_v4()
        .map_err(SandboxApiError::internal)?
        .replace('-', "")
        .chars()
        .take(12)
        .collect())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct TerminalSize {
    pub(super) cols: u16,
    pub(super) rows: u16,
}

impl Default for TerminalSize {
    fn default() -> Self {
        Self {
            cols: TERMINAL_DEFAULT_COLS,
            rows: TERMINAL_DEFAULT_ROWS,
        }
    }
}

impl TerminalSize {
    pub(super) fn update(self, cols: Option<u16>, rows: Option<u16>) -> Self {
        Self {
            cols: cols.unwrap_or(self.cols).max(1),
            rows: rows.unwrap_or(self.rows).max(1),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TerminalSessionRecord {
    pub(super) project_id: String,
    pub(super) session_id: String,
    pub(super) cols: u16,
    pub(super) rows: u16,
    pub(super) connected: bool,
    pub(super) last_seen_at_ms: i64,
    pub(super) expires_at_ms: i64,
}

impl TerminalSessionRecord {
    pub(super) fn new(
        project_id: String,
        session_id: String,
        size: TerminalSize,
        connected: bool,
        now_ms: i64,
        ttl_seconds: i64,
    ) -> Self {
        Self {
            project_id,
            session_id,
            cols: size.cols,
            rows: size.rows,
            connected,
            last_seen_at_ms: now_ms,
            expires_at_ms: now_ms + ttl_seconds.max(1) * 1000,
        }
    }

    pub(super) fn size(&self) -> TerminalSize {
        TerminalSize {
            cols: self.cols.max(1),
            rows: self.rows.max(1),
        }
    }
}

pub(super) fn terminal_connected_message(session_id: &str, size: TerminalSize) -> String {
    json!({
        "type": "connected",
        "session_id": session_id,
        "cols": size.cols,
        "rows": size.rows,
    })
    .to_string()
}

pub(super) fn terminal_output_message(data: &str) -> String {
    json!({
        "type": "output",
        "data": data,
    })
    .to_string()
}

pub(super) fn terminal_error_message() -> String {
    json!({
        "type": "error",
        "message": "Terminal WebSocket proxy failed",
    })
    .to_string()
}

pub(super) fn ttyd_initial_terminal_message(size: TerminalSize) -> TungsteniteMessage {
    TungsteniteMessage::Binary(
        json!({
            "AuthToken": "",
            "columns": size.cols,
            "rows": size.rows,
        })
        .to_string()
        .into_bytes(),
    )
}

pub(super) fn ttyd_input_message(data: &[u8]) -> TungsteniteMessage {
    let mut payload = Vec::with_capacity(data.len() + 1);
    payload.push(TTYD_INPUT_COMMAND);
    payload.extend_from_slice(data);
    TungsteniteMessage::Binary(payload)
}

pub(super) fn ttyd_resize_message(size: TerminalSize) -> TungsteniteMessage {
    let mut payload = Vec::with_capacity(32);
    payload.push(TTYD_RESIZE_COMMAND);
    payload.extend_from_slice(
        json!({
            "columns": size.cols,
            "rows": size.rows,
        })
        .to_string()
        .as_bytes(),
    );
    TungsteniteMessage::Binary(payload)
}

pub(super) fn ttyd_output_payload(data: &[u8]) -> Option<String> {
    let (&command, payload) = data.split_first()?;
    match command {
        TTYD_INPUT_COMMAND => Some(String::from_utf8_lossy(payload).to_string()),
        TTYD_RESIZE_COMMAND | TTYD_PREFERENCES_COMMAND => None,
        _ => Some(String::from_utf8_lossy(data).to_string()),
    }
}

#[derive(Clone)]
pub(super) struct TerminalSessionRecorder {
    registry: SharedHttpServiceRegistry,
    project_id: String,
    session_id: String,
    ttl_seconds: i64,
}

impl TerminalSessionRecorder {
    pub(super) fn new(
        registry: SharedHttpServiceRegistry,
        project_id: String,
        session_id: String,
        ttl_seconds: i64,
    ) -> Self {
        Self {
            registry,
            project_id,
            session_id,
            ttl_seconds,
        }
    }

    pub(super) async fn store(&self, size: TerminalSize, connected: bool) -> SandboxApiResult<()> {
        let now = now_ms();
        let record = TerminalSessionRecord::new(
            self.project_id.clone(),
            self.session_id.clone(),
            size,
            connected,
            now,
            self.ttl_seconds,
        );
        self.registry
            .upsert_terminal_session(record, self.ttl_seconds)
            .await
    }
}
