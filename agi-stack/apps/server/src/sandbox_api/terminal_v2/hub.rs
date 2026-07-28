use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use axum::extract::ws::{CloseFrame, Message, WebSocket};
use axum::http::HeaderValue;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::{broadcast, mpsc, Mutex, RwLock};
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::protocol::Message as UpstreamMessage;

use super::*;
use crate::sandbox_api::terminal_protocol::{
    ttyd_initial_terminal_message, ttyd_input_message, ttyd_output_payload, ttyd_resize_message,
    TerminalClientWsMessage,
};

#[derive(Debug, Clone)]
enum HubEvent {
    Output { sequence: u64, data: String },
    Lost { code: &'static str },
}

#[derive(Debug, Clone)]
struct ReplayEntry {
    sequence: u64,
    data: String,
}

pub(super) struct TerminalHubConnect {
    pub(super) session_id: String,
    pub(super) ws_target: String,
    pub(super) origin: String,
    pub(super) auth_header: HeaderValue,
    pub(super) authority_pool: agistack_adapters_postgres::PgPool,
    pub(super) authority: TerminalRunAuthority,
    pub(super) environment: TerminalEnvironmentAuthority,
    pub(super) expires_at_ms: i64,
}

pub(super) struct TerminalHub {
    session_id: String,
    input: mpsc::Sender<UpstreamMessage>,
    events: broadcast::Sender<HubEvent>,
    replay: Mutex<VecDeque<ReplayEntry>>,
    replay_bytes: AtomicUsize,
    sequence: AtomicUsize,
    attached: AtomicUsize,
    last_detached_at_ms: AtomicI64,
    alive: AtomicBool,
    expires_at_ms: i64,
    pub(super) environment: TerminalEnvironmentAuthority,
}

impl TerminalHub {
    pub(super) async fn connect(input: TerminalHubConnect) -> Result<Arc<Self>, TerminalV2Error> {
        let mut request = input
            .ws_target
            .into_client_request()
            .map_err(|_| TerminalV2Error::internal())?;
        request.headers_mut().insert(
            "origin",
            HeaderValue::from_str(&input.origin).map_err(|_| TerminalV2Error::internal())?,
        );
        request
            .headers_mut()
            .insert(AUTHORIZATION, input.auth_header);
        let (upstream, _) = tokio::time::timeout(Duration::from_secs(10), connect_async(request))
            .await
            .map_err(|_| TerminalV2Error::internal())?
            .map_err(|_| TerminalV2Error::internal())?;
        let (input_tx, input_rx) = mpsc::channel(INPUT_BUFFER_MESSAGES);
        let (events, _) = broadcast::channel(OUTPUT_BUFFER_MESSAGES);
        let hub = Arc::new(Self {
            session_id: input.session_id,
            input: input_tx,
            events,
            replay: Mutex::new(VecDeque::new()),
            replay_bytes: AtomicUsize::new(0),
            sequence: AtomicUsize::new(0),
            attached: AtomicUsize::new(0),
            last_detached_at_ms: AtomicI64::new(now_ms()),
            alive: AtomicBool::new(true),
            expires_at_ms: input.expires_at_ms,
            environment: input.environment.clone(),
        });
        let worker = Arc::clone(&hub);
        tokio::spawn(async move {
            worker
                .pump_upstream(
                    upstream,
                    input_rx,
                    input.authority_pool,
                    input.authority,
                    input.environment.cwd,
                )
                .await;
        });
        Ok(hub)
    }

    fn is_alive(&self) -> bool {
        self.alive.load(Ordering::Acquire) && self.expires_at_ms > now_ms()
    }

    async fn record_output(&self, data: String) {
        let sequence = self.sequence.fetch_add(1, Ordering::AcqRel) as u64 + 1;
        let bytes = data.len();
        let mut replay = self.replay.lock().await;
        replay.push_back(ReplayEntry {
            sequence,
            data: data.clone(),
        });
        self.replay_bytes.fetch_add(bytes, Ordering::AcqRel);
        while self.replay_bytes.load(Ordering::Acquire) > REPLAY_BUFFER_BYTES {
            let Some(removed) = replay.pop_front() else {
                break;
            };
            self.replay_bytes
                .fetch_sub(removed.data.len(), Ordering::AcqRel);
        }
        drop(replay);
        let _ = self.events.send(HubEvent::Output { sequence, data });
    }

    pub(super) fn mark_lost(&self, code: &'static str) {
        if self.alive.swap(false, Ordering::AcqRel) {
            let _ = self.events.send(HubEvent::Lost { code });
        }
    }

    async fn pump_upstream<S>(
        self: Arc<Self>,
        upstream: tokio_tungstenite::WebSocketStream<S>,
        mut input_rx: mpsc::Receiver<UpstreamMessage>,
        authority_pool: agistack_adapters_postgres::PgPool,
        authority: TerminalRunAuthority,
        cwd: String,
    ) where
        S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send + 'static,
    {
        let (mut upstream_tx, mut upstream_rx) = upstream.split();
        if upstream_tx
            .send(ttyd_initial_terminal_message(TerminalSize::default()))
            .await
            .is_err()
        {
            self.mark_lost("terminal_session_lost");
            return;
        }
        let enter_cwd = format!(
            "cd -- {} && printf '\\033[2J\\033[H'\r",
            shell_single_quote(&cwd)
        );
        if upstream_tx
            .send(ttyd_input_message(enter_cwd.as_bytes()))
            .await
            .is_err()
        {
            self.mark_lost("terminal_session_lost");
            return;
        }
        let mut interval = tokio::time::interval(Duration::from_secs(1));
        let mut authority_ticks = 0_u64;
        loop {
            tokio::select! {
                input = input_rx.recv() => {
                    let Some(input) = input else { break };
                    if upstream_tx.send(input).await.is_err() {
                        break;
                    }
                }
                upstream = upstream_rx.next() => {
                    match upstream {
                        Some(Ok(UpstreamMessage::Binary(data))) => {
                            if let Some(output) = ttyd_output_payload(&data) {
                                self.record_output(output).await;
                            }
                        }
                        Some(Ok(UpstreamMessage::Text(data))) => {
                            self.record_output(data).await;
                        }
                        Some(Ok(UpstreamMessage::Ping(data))) => {
                            if upstream_tx.send(UpstreamMessage::Pong(data)).await.is_err() {
                                break;
                            }
                        }
                        Some(Ok(_)) => {}
                        Some(Err(_)) | None => break,
                    }
                }
                _ = interval.tick() => {
                    let now = now_ms();
                    if now >= self.expires_at_ms {
                        break;
                    }
                    if self.attached.load(Ordering::Acquire) == 0
                        && now - self.last_detached_at_ms.load(Ordering::Acquire)
                            >= disconnect_grace_seconds() * 1_000
                    {
                        break;
                    }
                    authority_ticks += 1;
                    if authority_ticks >= AUTHORITY_RECHECK_SECONDS {
                        authority_ticks = 0;
                        if load_terminal_authority(
                            &authority_pool,
                            &authority.tenant_id,
                            &authority.project_id,
                            &authority.run_id,
                            authority.run_revision,
                            &authority.user_id,
                        )
                        .await
                        .as_ref()
                            != Some(&authority)
                        {
                            self.mark_lost("terminal_authority_revoked");
                            let _ = upstream_tx.close().await;
                            return;
                        }
                    }
                }
            }
        }
        let _ = upstream_tx.close().await;
        self.mark_lost("terminal_session_lost");
    }

    pub(super) async fn attach(self: Arc<Self>, socket: WebSocket) {
        self.attached.fetch_add(1, Ordering::AcqRel);
        let mut events = self.events.subscribe();
        let replay = self.replay.lock().await.iter().cloned().collect::<Vec<_>>();
        let (mut client_tx, mut client_rx) = socket.split();
        let mut last_sequence = 0_u64;
        let connected = json!({
            "type": "connected",
            "contract_version": CONTRACT_VERSION,
            "session_id": self.session_id,
            "resumed": !replay.is_empty(),
        })
        .to_string();
        if client_tx.send(Message::Text(connected)).await.is_ok() {
            for entry in replay {
                last_sequence = entry.sequence;
                if client_tx
                    .send(Message::Text(terminal_v2_output_message(
                        entry.sequence,
                        &entry.data,
                    )))
                    .await
                    .is_err()
                {
                    break;
                }
            }
            loop {
                tokio::select! {
                    incoming = client_rx.next() => {
                        let Some(Ok(incoming)) = incoming else { break };
                        let upstream = match incoming {
                            Message::Text(text) => match serde_json::from_str::<TerminalClientWsMessage>(&text) {
                                Ok(message) if message.kind == "input" => {
                                    ttyd_input_message(message.data.unwrap_or_default().as_bytes())
                                }
                                Ok(message) if message.kind == "resize" => {
                                    ttyd_resize_message(TerminalSize::default().update(message.cols, message.rows))
                                }
                                Ok(message) if message.kind == "ping" => {
                                    if client_tx.send(Message::Text(json!({"type":"pong"}).to_string())).await.is_err() {
                                        break;
                                    }
                                    continue;
                                }
                                _ => break,
                            },
                            Message::Binary(data) => ttyd_input_message(&data),
                            Message::Ping(data) => {
                                if client_tx.send(Message::Pong(data)).await.is_err() {
                                    break;
                                }
                                continue;
                            }
                            Message::Close(_) => break,
                            _ => continue,
                        };
                        if self.input.try_send(upstream).is_err() {
                            let _ = client_tx.send(Message::Text(json!({
                                "type": "terminal_backpressure",
                                "refetch": false,
                            }).to_string())).await;
                            let _ = client_tx.send(Message::Close(Some(CloseFrame {
                                code: 1013,
                                reason: "Terminal input backpressure".into(),
                            }))).await;
                            break;
                        }
                    }
                    event = events.recv() => {
                        match event {
                            Ok(HubEvent::Output { sequence, data }) if sequence > last_sequence => {
                                last_sequence = sequence;
                                if client_tx.send(Message::Text(terminal_v2_output_message(sequence, &data))).await.is_err() {
                                    break;
                                }
                            }
                            Ok(HubEvent::Output { .. }) => {}
                            Ok(HubEvent::Lost { code }) => {
                                let _ = client_tx.send(Message::Text(json!({
                                    "type": code,
                                    "refetch": true,
                                }).to_string())).await;
                                let _ = client_tx.send(Message::Close(Some(CloseFrame {
                                    code: 1012,
                                    reason: code.into(),
                                }))).await;
                                break;
                            }
                            Err(broadcast::error::RecvError::Lagged(_)) => {
                                let _ = client_tx.send(Message::Text(json!({
                                    "type": "terminal_backpressure",
                                    "refetch": true,
                                }).to_string())).await;
                                let _ = client_tx.send(Message::Close(Some(CloseFrame {
                                    code: 1013,
                                    reason: "Terminal output backpressure".into(),
                                }))).await;
                                break;
                            }
                            Err(broadcast::error::RecvError::Closed) => break,
                        }
                    }
                }
            }
        }
        self.attached.fetch_sub(1, Ordering::AcqRel);
        self.last_detached_at_ms.store(now_ms(), Ordering::Release);
    }
}

#[derive(Default)]
pub(super) struct TerminalHubManager {
    hubs: RwLock<HashMap<String, Arc<TerminalHub>>>,
}

impl TerminalHubManager {
    pub(super) async fn insert(&self, session_id: String, hub: Arc<TerminalHub>) {
        let mut hubs = self.hubs.write().await;
        hubs.retain(|_, existing| existing.is_alive());
        hubs.insert(session_id, hub);
    }

    pub(super) async fn get(&self, session_id: &str) -> Option<Arc<TerminalHub>> {
        let mut hubs = self.hubs.write().await;
        hubs.retain(|_, existing| existing.is_alive());
        hubs.get(session_id).cloned()
    }
}
