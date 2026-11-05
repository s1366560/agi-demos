//! One owned browser WebSocket; close rejects every pending command.
use super::endpoint;
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc, Mutex,
};
use std::time::Duration;
use tokio::sync::{broadcast, mpsc, oneshot, watch, Notify};
use tokio_tungstenite::tungstenite::{protocol::WebSocketConfig, Message};

type Reply = Result<Value, String>;

struct State {
    next: AtomicU64,
    closed: AtomicBool,
    on_close: Notify,
    waiters: Mutex<HashMap<u64, oneshot::Sender<Reply>>>,
    events: broadcast::Sender<Value>,
}

pub(super) struct Connection {
    state: Arc<State>,
    outgoing: mpsc::Sender<Outbound>,
    shutdown: watch::Sender<bool>,
}

struct Outbound {
    id: u64,
    message: Message,
}

struct Waiter {
    state: Arc<State>,
    id: u64,
}
impl Drop for Waiter {
    fn drop(&mut self) {
        self.state
            .waiters
            .lock()
            .expect("cdp waiters")
            .remove(&self.id);
    }
}

impl State {
    fn close(&self) {
        self.closed.store(true, Ordering::SeqCst);
        for (_, waiter) in self.waiters.lock().expect("cdp waiters").drain() {
            let _ = waiter.send(Err("cdp_connection_closed".into()));
        }
        self.on_close.notify_waiters();
    }
}

impl Connection {
    pub(super) async fn connect(endpoint: &str) -> Result<Arc<Self>, String> {
        let url = endpoint::discover(endpoint).await?;
        let mut connected = None;
        for address in endpoint::addresses(&url).await? {
            if let Ok(stream) = tokio::time::timeout(
                Duration::from_secs(5),
                tokio::net::TcpStream::connect(address),
            )
            .await
            {
                if let Ok(stream) = stream {
                    if stream.peer_addr().is_ok_and(|peer| peer.ip().is_loopback()) {
                        connected = Some(stream);
                        break;
                    }
                }
            }
        }
        let stream = connected.ok_or("cdp_connection_failed")?;
        let config = WebSocketConfig {
            max_message_size: Some(16 * 1024 * 1024),
            max_frame_size: Some(16 * 1024 * 1024),
            ..Default::default()
        };
        // The TCP peer is pinned above. The WebSocket client never follows redirects.
        let (socket, _) = tokio::time::timeout(
            Duration::from_secs(5),
            tokio_tungstenite::client_async_tls_with_config(
                url.as_str(),
                stream,
                Some(config),
                None,
            ),
        )
        .await
        .map_err(|_| "cdp_websocket_timeout")?
        .map_err(|_| "cdp_websocket_failed")?;
        let (events, _) = broadcast::channel(1024);
        let state = Arc::new(State {
            next: AtomicU64::new(1),
            closed: AtomicBool::new(false),
            on_close: Notify::new(),
            waiters: Mutex::new(HashMap::new()),
            events,
        });
        let (outgoing, mut receiver) = mpsc::channel::<Outbound>(64);
        let (shutdown, mut stopped) = watch::channel(false);
        let connection = Arc::new(Self {
            state: state.clone(),
            outgoing,
            shutdown,
        });
        tokio::spawn(async move {
            let (mut sink, mut source) = socket.split();
            loop {
                tokio::select! {
                    _ = stopped.changed() => break,
                    outbound = receiver.recv() => match outbound {
                        Some(outbound) => {
                            if !state.waiters.lock().expect("cdp waiters").contains_key(&outbound.id) { continue; }
                            match tokio::time::timeout(Duration::from_secs(5), sink.send(outbound.message)).await {
                                Ok(Ok(())) => {},
                                _ => break,
                            }
                        },
                        None => break,
                    },
                    inbound = source.next() => match inbound {
                        Some(Ok(Message::Text(text))) => {
                            let Ok(value) = serde_json::from_str::<Value>(&text) else { break; };
                            if let Some(id) = value["id"].as_u64() {
                                if let Some(waiter) = state.waiters.lock().expect("cdp waiters").remove(&id) {
                                    let result = if value.get("error").is_some() { Err("cdp_command_failed".into()) } else { Ok(value["result"].clone()) };
                                    let _ = waiter.send(result);
                                }
                            } else if value["method"].is_string() { let _ = state.events.send(value); }
                        },
                        Some(Ok(Message::Ping(payload))) => if sink.send(Message::Pong(payload)).await.is_err() { break; },
                        Some(Ok(Message::Pong(_))) => {},
                        _ => break,
                    },
                }
            }
            state.close();
            let _ = tokio::time::timeout(Duration::from_millis(200), sink.close()).await;
        });
        Ok(connection)
    }

    pub(super) async fn request(
        &self,
        method: &str,
        params: Value,
        session: Option<&str>,
    ) -> Reply {
        if self.is_closed() {
            return Err("cdp_connection_closed".into());
        }
        let id = self.state.next.fetch_add(1, Ordering::Relaxed);
        let (send, receive) = oneshot::channel();
        {
            let mut waiters = self.state.waiters.lock().expect("cdp waiters");
            if self.is_closed() {
                return Err("cdp_connection_closed".into());
            }
            waiters.insert(id, send);
        }
        let _guard = Waiter {
            state: self.state.clone(),
            id,
        };
        let mut message = json!({"id":id,"method":method,"params":params});
        if let Some(session) = session {
            message["sessionId"] = json!(session);
        }
        let encoded = message.to_string();
        if encoded.len() > 16 * 1024 * 1024 {
            return Err("cdp_command_too_large".into());
        }
        let action = async {
            self.outgoing
                .send(Outbound {
                    id,
                    message: Message::Text(encoded),
                })
                .await
                .map_err(|_| "cdp_connection_closed")?;
            receive
                .await
                .map_err(|_| "cdp_connection_closed".to_string())?
        };
        match tokio::time::timeout(Duration::from_secs(30), action).await {
            Ok(result) => result,
            Err(_) => {
                self.close();
                Err("cdp_command_timeout".into())
            }
        }
    }

    pub(super) fn events(&self) -> broadcast::Receiver<Value> {
        self.state.events.subscribe()
    }
    pub(super) fn is_closed(&self) -> bool {
        self.state.closed.load(Ordering::SeqCst)
    }
    pub(super) async fn closed(&self) {
        loop {
            let wait = self.state.on_close.notified();
            tokio::pin!(wait);
            wait.as_mut().enable();
            if self.is_closed() {
                return;
            }
            wait.await;
        }
    }
    pub(super) fn close(&self) {
        self.state.close();
        let _ = self.shutdown.send(true);
    }
}
impl Drop for Connection {
    fn drop(&mut self) {
        self.close();
    }
}
