use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Weak};
use std::time::Duration;

use axum::extract::ws::{CloseFrame, Message, WebSocket};
use axum::http::HeaderValue;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::{broadcast, mpsc, watch, Mutex, RwLock};
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

#[derive(Debug)]
struct ReplayWindow {
    entries: Vec<ReplayEntry>,
    oldest_sequence: u64,
    latest_sequence: u64,
}

#[derive(Debug)]
struct ReplayGap {
    after_sequence: u64,
    oldest_sequence: u64,
    latest_sequence: u64,
}

#[derive(Clone)]
struct TerminalHubCleanup {
    registry: SharedHttpServiceRegistry,
    project_id: String,
    manager: Weak<TerminalHubManager>,
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
    sequence: AtomicU64,
    attached: AtomicUsize,
    last_detached_at_ms: AtomicI64,
    alive: AtomicBool,
    cancellation: watch::Sender<Option<&'static str>>,
    cleanup: Mutex<Option<TerminalHubCleanup>>,
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
        let (cancellation, cancellation_rx) = watch::channel(None);
        let hub = Arc::new(Self {
            session_id: input.session_id,
            input: input_tx,
            events,
            replay: Mutex::new(VecDeque::new()),
            replay_bytes: AtomicUsize::new(0),
            sequence: AtomicU64::new(0),
            attached: AtomicUsize::new(0),
            last_detached_at_ms: AtomicI64::new(now_ms()),
            alive: AtomicBool::new(true),
            cancellation,
            cleanup: Mutex::new(None),
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
                    cancellation_rx,
                )
                .await;
        });
        Ok(hub)
    }

    fn is_alive(&self) -> bool {
        self.alive.load(Ordering::Acquire) && self.expires_at_ms > now_ms()
    }

    #[cfg(test)]
    fn for_test(
        input: mpsc::Sender<UpstreamMessage>,
        environment: TerminalEnvironmentAuthority,
    ) -> Arc<Self> {
        let (events, _) = broadcast::channel(OUTPUT_BUFFER_MESSAGES);
        let (cancellation, _) = watch::channel(None);
        Arc::new(Self {
            session_id: "test-session".to_string(),
            input,
            events,
            replay: Mutex::new(VecDeque::new()),
            replay_bytes: AtomicUsize::new(0),
            sequence: AtomicU64::new(0),
            attached: AtomicUsize::new(0),
            last_detached_at_ms: AtomicI64::new(now_ms()),
            alive: AtomicBool::new(true),
            cancellation,
            cleanup: Mutex::new(None),
            expires_at_ms: now_ms() + 60_000,
            environment,
        })
    }

    async fn record_output(&self, data: String) {
        let sequence =
            match self
                .sequence
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                    current.checked_add(1)
                }) {
                Ok(previous) => previous.saturating_add(1),
                Err(_) => {
                    self.mark_lost("terminal_output_gap");
                    return;
                }
            };
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

    async fn replay_after(&self, after_sequence: u64) -> Result<ReplayWindow, ReplayGap> {
        let replay = self.replay.lock().await;
        let latest_sequence = self.sequence.load(Ordering::Acquire);
        let oldest_sequence = replay
            .front()
            .map(|entry| entry.sequence)
            .unwrap_or_else(|| latest_sequence.saturating_add(1));
        let earliest_valid_cursor = oldest_sequence.saturating_sub(1);
        if after_sequence > latest_sequence || after_sequence < earliest_valid_cursor {
            return Err(ReplayGap {
                after_sequence,
                oldest_sequence,
                latest_sequence,
            });
        }
        Ok(ReplayWindow {
            entries: replay
                .iter()
                .filter(|entry| entry.sequence > after_sequence)
                .cloned()
                .collect(),
            oldest_sequence,
            latest_sequence,
        })
    }

    pub(super) fn mark_lost(&self, code: &'static str) {
        if self.alive.swap(false, Ordering::AcqRel) {
            let _ = self.events.send(HubEvent::Lost { code });
            let _ = self.cancellation.send(Some(code));
        }
    }

    pub(super) async fn install_cleanup(
        &self,
        registry: SharedHttpServiceRegistry,
        project_id: String,
        manager: Weak<TerminalHubManager>,
    ) {
        {
            let mut cleanup = self.cleanup.lock().await;
            *cleanup = Some(TerminalHubCleanup {
                registry,
                project_id,
                manager,
            });
        }
        if !self.is_alive() {
            self.cleanup_durable_state().await;
        }
    }

    pub(super) async fn finalize_lost(&self, code: &'static str) {
        self.mark_lost(code);
        self.cleanup_durable_state().await;
    }

    async fn cleanup_durable_state(&self) {
        let cleanup = self.cleanup.lock().await.take();
        let Some(cleanup) = cleanup else {
            return;
        };
        if cleanup
            .registry
            .remove_terminal_session_v2(&cleanup.project_id, &self.session_id)
            .await
            .is_err()
        {
            eprintln!("[agistack] terminal-v2 durable session cleanup failed");
        }
        if let Some(manager) = cleanup.manager.upgrade() {
            manager.remove(&self.session_id).await;
        }
    }

    async fn pump_upstream<S>(
        self: Arc<Self>,
        upstream: tokio_tungstenite::WebSocketStream<S>,
        mut input_rx: mpsc::Receiver<UpstreamMessage>,
        authority_pool: agistack_adapters_postgres::PgPool,
        authority: TerminalRunAuthority,
        cwd: String,
        mut cancellation: watch::Receiver<Option<&'static str>>,
    ) where
        S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send + 'static,
    {
        let (mut upstream_tx, mut upstream_rx) = upstream.split();
        if upstream_tx
            .send(ttyd_initial_terminal_message(TerminalSize::default()))
            .await
            .is_err()
        {
            self.finalize_lost("terminal_session_lost").await;
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
            self.finalize_lost("terminal_session_lost").await;
            return;
        }
        let mut interval = tokio::time::interval(Duration::from_secs(1));
        let mut authority_ticks = 0_u64;
        let mut lost_code = "terminal_session_lost";
        loop {
            tokio::select! {
                changed = cancellation.changed() => {
                    if changed.is_ok() {
                        lost_code = cancellation
                            .borrow()
                            .unwrap_or("terminal_session_lost");
                    }
                    break;
                }
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
                                if output.len() > TERMINAL_FRAME_BYTES {
                                    lost_code = "terminal_output_gap";
                                    break;
                                }
                                self.record_output(output).await;
                            }
                        }
                        Some(Ok(UpstreamMessage::Text(data))) => {
                            if data.len() > TERMINAL_FRAME_BYTES {
                                lost_code = "terminal_output_gap";
                                break;
                            }
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
                            lost_code = "terminal_authority_revoked";
                            break;
                        }
                    }
                }
            }
        }
        let _ = upstream_tx.close().await;
        self.finalize_lost(lost_code).await;
    }

    pub(super) async fn attach(self: Arc<Self>, socket: WebSocket, after_sequence: u64) {
        self.attached.fetch_add(1, Ordering::AcqRel);
        let mut events = self.events.subscribe();
        let replay = self.replay_after(after_sequence).await;
        let (mut client_tx, mut client_rx) = socket.split();
        let mut last_sequence = after_sequence;
        let connected = json!({
            "type": "connected",
            "contract_version": CONTRACT_VERSION,
            "session_id": self.session_id,
            "resumed": after_sequence > 0,
        })
        .to_string();
        if client_tx.send(Message::Text(connected)).await.is_ok() {
            let replay = match replay {
                Ok(replay) => replay,
                Err(gap) => {
                    let _ = send_output_gap(&mut client_tx, &gap).await;
                    let _ = client_tx
                        .send(Message::Close(Some(CloseFrame {
                            code: 1013,
                            reason: "Terminal output retention gap".into(),
                        })))
                        .await;
                    self.attached.fetch_sub(1, Ordering::AcqRel);
                    self.last_detached_at_ms.store(now_ms(), Ordering::Release);
                    return;
                }
            };
            let ack = json!({
                "type": "ack",
                "after_sequence": after_sequence,
                "oldest_sequence": replay.oldest_sequence,
                "latest_sequence": replay.latest_sequence,
            })
            .to_string();
            if client_tx.send(Message::Text(ack)).await.is_err() {
                self.attached.fetch_sub(1, Ordering::AcqRel);
                self.last_detached_at_ms.store(now_ms(), Ordering::Release);
                return;
            }
            for entry in replay.entries {
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
                            Message::Text(text) if text.len() > TERMINAL_FRAME_BYTES => {
                                let _ = client_tx.send(Message::Text(json!({
                                    "type": "terminal_frame_too_large",
                                    "refetch": false,
                                }).to_string())).await;
                                let _ = client_tx.send(Message::Close(Some(CloseFrame {
                                    code: 1009,
                                    reason: "Terminal input frame too large".into(),
                                }))).await;
                                break;
                            }
                            Message::Binary(data) if data.len() > TERMINAL_FRAME_BYTES => {
                                let _ = client_tx.send(Message::Text(json!({
                                    "type": "terminal_frame_too_large",
                                    "refetch": false,
                                }).to_string())).await;
                                let _ = client_tx.send(Message::Close(Some(CloseFrame {
                                    code: 1009,
                                    reason: "Terminal input frame too large".into(),
                                }))).await;
                                break;
                            }
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
                        match tokio::time::timeout(
                            Duration::from_millis(INPUT_SEND_TIMEOUT_MILLIS),
                            self.input.send(upstream),
                        ).await {
                            Ok(Ok(())) => {}
                            Ok(Err(_)) => {
                                let _ = client_tx.send(Message::Text(json!({
                                    "type": "terminal_session_lost",
                                    "refetch": true,
                                }).to_string())).await;
                                break;
                            }
                            Err(_) => {
                                let _ = client_tx.send(Message::Text(json!({
                                    "type": "terminal_input_overload",
                                    "refetch": false,
                                }).to_string())).await;
                                let _ = client_tx.send(Message::Close(Some(CloseFrame {
                                    code: 1013,
                                    reason: "Terminal input overload".into(),
                                }))).await;
                                break;
                            }
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
                                let gap = self.replay_after(last_sequence).await.err().unwrap_or(
                                    ReplayGap {
                                        after_sequence: last_sequence,
                                        oldest_sequence: self.sequence.load(Ordering::Acquire),
                                        latest_sequence: self.sequence.load(Ordering::Acquire),
                                    },
                                );
                                let _ = send_output_gap(&mut client_tx, &gap).await;
                                let _ = client_tx.send(Message::Close(Some(CloseFrame {
                                    code: 1013,
                                    reason: "Terminal output gap".into(),
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

async fn send_output_gap<S>(client_tx: &mut S, gap: &ReplayGap) -> Result<(), axum::Error>
where
    S: futures_util::Sink<Message, Error = axum::Error> + Unpin,
{
    client_tx
        .send(Message::Text(
            json!({
                "type": "terminal_output_gap",
                "after_sequence": gap.after_sequence,
                "oldest_sequence": gap.oldest_sequence,
                "latest_sequence": gap.latest_sequence,
                "refetch": true,
            })
            .to_string(),
        ))
        .await
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

    async fn remove(&self, session_id: &str) {
        self.hubs.write().await.remove(session_id);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::routing::get;
    use axum::Router;
    use serde_json::Value;

    fn test_authority() -> TerminalRunAuthority {
        TerminalRunAuthority {
            tenant_id: "tenant-1".to_string(),
            user_id: "user-1".to_string(),
            project_id: "project-1".to_string(),
            conversation_id: "conversation-1".to_string(),
            run_id: "run-1".to_string(),
            run_revision: 7,
            environment_kind: "worktree".to_string(),
            environment_id: "sandbox-1".to_string(),
            workspace_path: "/workspace".to_string(),
        }
    }

    fn test_environment() -> TerminalEnvironmentAuthority {
        TerminalEnvironmentAuthority {
            environment_id: "sandbox-1".to_string(),
            cwd: "/workspace".to_string(),
            environment_source: "agent_plan_runs.authorization_snapshot.environment.id".to_string(),
            cwd_source: "agent_plan_runs.authorization_snapshot.environment.workspace_path"
                .to_string(),
        }
    }

    fn lazy_test_pool() -> agistack_adapters_postgres::PgPool {
        sqlx::postgres::PgPoolOptions::new()
            .connect_lazy("postgres://postgres:postgres@127.0.0.1:1/memstack")
            .expect("test postgres URL is valid")
    }

    async fn spawn_hub_ws(hub: Arc<TerminalHub>, after_sequence: u64) -> String {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .expect("bind hub websocket");
        let addr = listener.local_addr().expect("hub websocket address");
        let app = Router::new().route(
            "/ws",
            get(move |ws: WebSocketUpgrade| {
                let hub = Arc::clone(&hub);
                async move { ws.on_upgrade(move |socket| hub.attach(socket, after_sequence)) }
            }),
        );
        tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("serve hub websocket");
        });
        format!("ws://{addr}/ws")
    }

    async fn next_json<S>(client: &mut tokio_tungstenite::WebSocketStream<S>) -> Value
    where
        S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    {
        let frame = tokio::time::timeout(Duration::from_secs(2), client.next())
            .await
            .expect("terminal frame timeout")
            .expect("terminal websocket open")
            .expect("terminal websocket frame");
        let UpstreamMessage::Text(text) = frame else {
            panic!("expected terminal JSON text frame");
        };
        serde_json::from_str(&text).expect("valid terminal JSON frame")
    }

    #[tokio::test]
    async fn attach_acknowledges_cursor_and_replays_only_newer_output() {
        let (input, _input_rx) = mpsc::channel(1);
        let hub = TerminalHub::for_test(input, test_environment());
        hub.record_output("first".to_string()).await;
        hub.record_output("second".to_string()).await;
        let url = spawn_hub_ws(Arc::clone(&hub), 1).await;

        let (mut client, _) = tokio_tungstenite::connect_async(url)
            .await
            .expect("connect hub websocket");
        let connected = next_json(&mut client).await;
        assert_eq!(connected["type"], "connected");
        assert_eq!(connected["resumed"], true);
        let ack = next_json(&mut client).await;
        assert_eq!(ack["type"], "ack");
        assert_eq!(ack["after_sequence"], 1);
        assert_eq!(ack["latest_sequence"], 2);
        let output = next_json(&mut client).await;
        assert_eq!(output["type"], "output");
        assert_eq!(output["sequence"], 2);
        assert_eq!(output["data"], "second");
    }

    #[tokio::test]
    async fn reconnect_replays_only_output_after_the_acknowledged_cursor() {
        let (input, _input_rx) = mpsc::channel(1);
        let hub = TerminalHub::for_test(input, test_environment());
        let first_url = spawn_hub_ws(Arc::clone(&hub), 0).await;
        let (mut first_client, _) = tokio_tungstenite::connect_async(first_url)
            .await
            .expect("connect first hub websocket");
        assert_eq!(next_json(&mut first_client).await["type"], "connected");
        assert_eq!(next_json(&mut first_client).await["after_sequence"], 0);
        hub.record_output("first".to_string()).await;
        assert_eq!(next_json(&mut first_client).await["sequence"], 1);
        first_client
            .close(None)
            .await
            .expect("close first hub websocket");

        hub.record_output("second".to_string()).await;
        let resumed_url = spawn_hub_ws(Arc::clone(&hub), 1).await;
        let (mut resumed_client, _) = tokio_tungstenite::connect_async(resumed_url)
            .await
            .expect("connect resumed hub websocket");
        assert_eq!(next_json(&mut resumed_client).await["type"], "connected");
        let ack = next_json(&mut resumed_client).await;
        assert_eq!(ack["after_sequence"], 1);
        assert_eq!(ack["latest_sequence"], 2);
        let replayed = next_json(&mut resumed_client).await;
        assert_eq!(replayed["sequence"], 2);
        assert_eq!(replayed["data"], "second");
    }

    #[tokio::test]
    async fn attach_reports_structured_retention_gap_instead_of_partial_replay() {
        let (input, _input_rx) = mpsc::channel(1);
        let hub = TerminalHub::for_test(input, test_environment());
        for index in 0..9 {
            hub.record_output(format!("{index}{}", "x".repeat(65_535)))
                .await;
        }
        let url = spawn_hub_ws(Arc::clone(&hub), 0).await;

        let (mut client, _) = tokio_tungstenite::connect_async(url)
            .await
            .expect("connect hub websocket");
        let connected = next_json(&mut client).await;
        assert_eq!(connected["type"], "connected");
        let gap = next_json(&mut client).await;
        assert_eq!(gap["type"], "terminal_output_gap");
        assert_eq!(gap["after_sequence"], 0);
        assert_eq!(gap["oldest_sequence"], 2);
        assert_eq!(gap["latest_sequence"], 9);
        assert_eq!(gap["refetch"], true);
    }

    #[tokio::test]
    async fn attach_times_out_saturated_input_without_silently_dropping_it() {
        let (input, _input_rx) = mpsc::channel(1);
        input
            .send(UpstreamMessage::Text("occupied".to_string()))
            .await
            .expect("pre-fill input channel");
        let hub = TerminalHub::for_test(input, test_environment());
        let url = spawn_hub_ws(Arc::clone(&hub), 0).await;

        let (mut client, _) = tokio_tungstenite::connect_async(url)
            .await
            .expect("connect hub websocket");
        assert_eq!(next_json(&mut client).await["type"], "connected");
        assert_eq!(next_json(&mut client).await["type"], "ack");
        client
            .send(UpstreamMessage::Text(
                json!({"type": "input", "data": "pwd\n"}).to_string(),
            ))
            .await
            .expect("send terminal input");
        let overload = next_json(&mut client).await;
        assert_eq!(overload["type"], "terminal_input_overload");
        assert_eq!(overload["refetch"], false);
    }

    #[tokio::test]
    async fn attach_rejects_an_oversized_client_frame_before_the_input_queue() {
        let (input, _input_rx) = mpsc::channel(1);
        let hub = TerminalHub::for_test(input, test_environment());
        let url = spawn_hub_ws(Arc::clone(&hub), 0).await;

        let (mut client, _) = tokio_tungstenite::connect_async(url)
            .await
            .expect("connect hub websocket");
        assert_eq!(next_json(&mut client).await["type"], "connected");
        assert_eq!(next_json(&mut client).await["type"], "ack");
        client
            .send(UpstreamMessage::Text("x".repeat(TERMINAL_FRAME_BYTES + 1)))
            .await
            .expect("send oversized input frame");
        let rejected = next_json(&mut client).await;
        assert_eq!(rejected["type"], "terminal_frame_too_large");
        assert_eq!(rejected["refetch"], false);
    }

    #[tokio::test]
    async fn lost_hub_cancels_the_worker_and_removes_it_from_the_manager() {
        let (input, _input_rx) = mpsc::channel(1);
        let hub = TerminalHub::for_test(input, test_environment());
        let manager = Arc::new(TerminalHubManager::default());
        manager
            .insert("test-session".to_string(), Arc::clone(&hub))
            .await;
        hub.install_cleanup(
            in_memory_http_service_registry(),
            "project-1".to_string(),
            Arc::downgrade(&manager),
        )
        .await;
        let cancellation = hub.cancellation.subscribe();

        hub.finalize_lost("terminal_authority_revoked").await;

        assert_eq!(*cancellation.borrow(), Some("terminal_authority_revoked"));
        assert!(!hub.is_alive());
        assert!(!manager.hubs.read().await.contains_key("test-session"));
    }

    #[tokio::test]
    async fn mock_ttyd_output_flows_through_hub_with_a_monotonic_sequence() {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .expect("bind mock ttyd");
        let addr = listener.local_addr().expect("mock ttyd address");
        let (frames_tx, mut frames_rx) = mpsc::channel::<Vec<u8>>(4);
        tokio::spawn(async move {
            let (stream, _) = listener.accept().await.expect("accept mock ttyd");
            let mut ttyd = tokio_tungstenite::accept_async(stream)
                .await
                .expect("upgrade mock ttyd");
            for _ in 0..2 {
                let frame = ttyd
                    .next()
                    .await
                    .expect("mock ttyd input")
                    .expect("valid mock ttyd frame")
                    .into_data();
                frames_tx.send(frame).await.expect("record ttyd frame");
            }
            ttyd.send(UpstreamMessage::Binary(b"0ready\n".to_vec()))
                .await
                .expect("send mock ttyd output");
            while ttyd.next().await.is_some() {}
        });
        let hub = TerminalHub::connect(TerminalHubConnect {
            session_id: "session-1".to_string(),
            ws_target: format!("ws://{addr}/"),
            origin: format!("http://{addr}"),
            auth_header: HeaderValue::from_static("Basic dGVzdA=="),
            authority_pool: lazy_test_pool(),
            authority: test_authority(),
            environment: test_environment(),
            expires_at_ms: now_ms() + 60_000,
        })
        .await
        .expect("connect terminal hub to mock ttyd");
        let url = spawn_hub_ws(Arc::clone(&hub), 0).await;
        let (mut client, _) = tokio_tungstenite::connect_async(url)
            .await
            .expect("connect hub websocket");

        assert_eq!(next_json(&mut client).await["type"], "connected");
        assert_eq!(next_json(&mut client).await["type"], "ack");
        let output = next_json(&mut client).await;
        assert_eq!(output["sequence"], 1);
        assert_eq!(output["data"], "ready\n");
        let initial = frames_rx.recv().await.expect("ttyd initial frame");
        assert!(initial.starts_with(b"{"));
        let cwd = frames_rx.recv().await.expect("ttyd cwd frame");
        assert_eq!(cwd.first().copied(), Some(TTYD_INPUT_COMMAND));
        assert!(String::from_utf8_lossy(&cwd[1..]).starts_with("cd -- '/workspace'"));
    }
}
