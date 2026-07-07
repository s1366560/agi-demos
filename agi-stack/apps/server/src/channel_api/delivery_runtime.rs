use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::task::JoinHandle;
use tokio::time::sleep;

use agistack_adapters_postgres::{ChannelOutboxRecord, PgChannelRepository};

use super::error::ChannelApiError;

const CHANNEL_OUTBOX_DELIVERY_AUTOSTART_ENV: &str = "AGISTACK_CHANNEL_OUTBOX_DELIVERY_AUTOSTART";
const CHANNEL_OUTBOX_DELIVERY_PRODUCTION_READY_ENV: &str =
    "AGISTACK_CHANNEL_OUTBOX_DELIVERY_PRODUCTION_READY";

pub(crate) type SharedChannelOutboxDeliveryWorker =
    Arc<ChannelOutboxDeliveryWorker<PgChannelRepository, FeishuWebhookDeliverer>>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ChannelOutboxDeliveryConfig {
    pub(crate) worker_id: String,
    pub(crate) lease_seconds: i64,
    pub(crate) batch_limit: i64,
    pub(crate) default_retry_after_seconds: i64,
}

impl ChannelOutboxDeliveryConfig {
    pub(crate) fn new(worker_id: impl Into<String>) -> Self {
        Self {
            worker_id: worker_id.into(),
            lease_seconds: 60,
            batch_limit: 25,
            default_retry_after_seconds: 60,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ChannelOutboxDeliveryWorkerConfig {
    pub(crate) delivery: ChannelOutboxDeliveryConfig,
    pub(crate) poll_interval_millis: u64,
    pub(crate) autostart: bool,
    pub(crate) production_ready: bool,
}

impl ChannelOutboxDeliveryWorkerConfig {
    pub(crate) fn from_env() -> Self {
        Self {
            delivery: ChannelOutboxDeliveryConfig {
                worker_id: std::env::var("AGISTACK_CHANNEL_OUTBOX_DELIVERY_WORKER_ID")
                    .ok()
                    .filter(|value| !value.trim().is_empty())
                    .unwrap_or_else(|| "agistack-rust-channel-outbox-delivery".to_string()),
                lease_seconds: positive_i64_env(
                    "AGISTACK_CHANNEL_OUTBOX_DELIVERY_LEASE_SECONDS",
                    60,
                ),
                batch_limit: positive_i64_env("AGISTACK_CHANNEL_OUTBOX_DELIVERY_BATCH_LIMIT", 25),
                default_retry_after_seconds: positive_i64_env(
                    "AGISTACK_CHANNEL_OUTBOX_DELIVERY_DEFAULT_RETRY_AFTER_SECONDS",
                    60,
                ),
            },
            poll_interval_millis: positive_millis_env(
                "AGISTACK_CHANNEL_OUTBOX_DELIVERY_POLL_SECONDS",
                2000,
            ),
            autostart: bool_env(CHANNEL_OUTBOX_DELIVERY_AUTOSTART_ENV, false),
            production_ready: bool_env(CHANNEL_OUTBOX_DELIVERY_PRODUCTION_READY_ENV, false),
        }
    }
}

impl Default for ChannelOutboxDeliveryWorkerConfig {
    fn default() -> Self {
        Self {
            delivery: ChannelOutboxDeliveryConfig::new("agistack-rust-channel-outbox-delivery"),
            poll_interval_millis: 2000,
            autostart: false,
            production_ready: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ChannelDeliveryRequest {
    pub(crate) outbox_id: String,
    pub(crate) project_id: String,
    pub(crate) channel_config_id: String,
    pub(crate) channel_type: Option<String>,
    pub(crate) webhook_url: Option<String>,
    pub(crate) domain: Option<String>,
    pub(crate) conversation_id: String,
    pub(crate) chat_id: String,
    pub(crate) content_text: String,
    pub(crate) attempt_count: i32,
}

impl ChannelDeliveryRequest {
    fn from_outbox(row: &ChannelOutboxRecord) -> Self {
        Self {
            outbox_id: row.id.clone(),
            project_id: row.project_id.clone(),
            channel_config_id: row.channel_config_id.clone(),
            channel_type: row.channel_type.clone(),
            webhook_url: row.webhook_url.clone(),
            domain: row.domain.clone(),
            conversation_id: row.conversation_id.clone(),
            chat_id: row.chat_id.clone(),
            content_text: row.content_text.clone(),
            attempt_count: row.attempt_count,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ChannelDeliveryOutcome {
    Sent {
        channel_message_id: String,
    },
    Failed {
        error: String,
        retry_after_seconds: Option<i64>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ChannelDeliveryError {
    message: String,
}

impl ChannelDeliveryError {
    pub(crate) fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct ChannelOutboxDeliverySummary {
    pub(crate) claimed: usize,
    pub(crate) sent: usize,
    pub(crate) failed: usize,
    pub(crate) lost_lease: usize,
    pub(crate) delivery_errors: usize,
}

#[async_trait]
pub(crate) trait ChannelOutboxDeliveryStore: Send + Sync {
    async fn claim_due_outbox(
        &self,
        worker_id: &str,
        lease_seconds: i64,
        limit: i64,
    ) -> Result<Vec<ChannelOutboxRecord>, ChannelApiError>;

    async fn mark_outbox_sent(
        &self,
        outbox_id: &str,
        worker_id: &str,
        sent_channel_message_id: &str,
    ) -> Result<Option<ChannelOutboxRecord>, ChannelApiError>;

    async fn mark_outbox_failed(
        &self,
        outbox_id: &str,
        worker_id: &str,
        error: &str,
        retry_after_seconds: i64,
    ) -> Result<Option<ChannelOutboxRecord>, ChannelApiError>;
}

#[async_trait]
impl ChannelOutboxDeliveryStore for PgChannelRepository {
    async fn claim_due_outbox(
        &self,
        worker_id: &str,
        lease_seconds: i64,
        limit: i64,
    ) -> Result<Vec<ChannelOutboxRecord>, ChannelApiError> {
        PgChannelRepository::claim_due_outbox(self, worker_id, lease_seconds, limit)
            .await
            .map_err(ChannelApiError::internal)
    }

    async fn mark_outbox_sent(
        &self,
        outbox_id: &str,
        worker_id: &str,
        sent_channel_message_id: &str,
    ) -> Result<Option<ChannelOutboxRecord>, ChannelApiError> {
        PgChannelRepository::mark_outbox_sent(self, outbox_id, worker_id, sent_channel_message_id)
            .await
            .map_err(ChannelApiError::internal)
    }

    async fn mark_outbox_failed(
        &self,
        outbox_id: &str,
        worker_id: &str,
        error: &str,
        retry_after_seconds: i64,
    ) -> Result<Option<ChannelOutboxRecord>, ChannelApiError> {
        PgChannelRepository::mark_outbox_failed(
            self,
            outbox_id,
            worker_id,
            error,
            retry_after_seconds,
        )
        .await
        .map_err(ChannelApiError::internal)
    }
}

#[async_trait]
pub(crate) trait ChannelMessageDeliverer: Send + Sync {
    async fn deliver(
        &self,
        request: &ChannelDeliveryRequest,
    ) -> Result<ChannelDeliveryOutcome, ChannelDeliveryError>;
}

#[derive(Debug, Clone)]
pub(crate) struct FeishuWebhookDeliverer {
    client: reqwest::Client,
}

impl Default for FeishuWebhookDeliverer {
    fn default() -> Self {
        Self::new(reqwest::Client::new())
    }
}

impl FeishuWebhookDeliverer {
    pub(crate) fn new(client: reqwest::Client) -> Self {
        Self { client }
    }
}

#[async_trait]
impl ChannelMessageDeliverer for FeishuWebhookDeliverer {
    async fn deliver(
        &self,
        request: &ChannelDeliveryRequest,
    ) -> Result<ChannelDeliveryOutcome, ChannelDeliveryError> {
        if !is_feishu_delivery(request) {
            return Ok(ChannelDeliveryOutcome::Failed {
                error: "unsupported channel provider for Feishu webhook delivery".to_string(),
                retry_after_seconds: None,
            });
        }
        let Some(webhook_url) = request
            .webhook_url
            .as_deref()
            .filter(|url| !url.trim().is_empty())
        else {
            return Ok(ChannelDeliveryOutcome::Failed {
                error: "missing Feishu webhook_url for channel delivery".to_string(),
                retry_after_seconds: None,
            });
        };

        let response = self
            .client
            .post(webhook_url)
            .json(&feishu_webhook_payload(request))
            .send()
            .await
            .map_err(|error| {
                ChannelDeliveryError::new(format!("Feishu webhook request failed: {error}"))
            })?;
        let retry_after_seconds = retry_after_seconds(response.headers());
        let status = response.status();
        let body = response.text().await.map_err(|error| {
            ChannelDeliveryError::new(format!("Feishu webhook response read failed: {error}"))
        })?;

        if status.is_success() && feishu_webhook_response_succeeded(&body) {
            Ok(ChannelDeliveryOutcome::Sent {
                channel_message_id: feishu_channel_message_id(request, &body),
            })
        } else {
            Ok(ChannelDeliveryOutcome::Failed {
                error: feishu_provider_error(status, &body),
                retry_after_seconds,
            })
        }
    }
}

fn is_feishu_delivery(request: &ChannelDeliveryRequest) -> bool {
    request
        .channel_type
        .as_deref()
        .map(|value| value.eq_ignore_ascii_case("feishu") || value.eq_ignore_ascii_case("lark"))
        .unwrap_or(false)
        || request
            .domain
            .as_deref()
            .map(|value| value.eq_ignore_ascii_case("feishu") || value.eq_ignore_ascii_case("lark"))
            .unwrap_or(false)
}

fn feishu_webhook_payload(request: &ChannelDeliveryRequest) -> Value {
    json!({
        "msg_type": "text",
        "content": {
            "text": request.content_text.as_str()
        }
    })
}

fn retry_after_seconds(headers: &reqwest::header::HeaderMap) -> Option<i64> {
    headers
        .get(reqwest::header::RETRY_AFTER)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.trim().parse::<i64>().ok())
        .filter(|seconds| *seconds > 0)
}

fn feishu_webhook_response_succeeded(body: &str) -> bool {
    let trimmed = body.trim();
    if trimmed.is_empty() {
        return true;
    }
    let Ok(value) = serde_json::from_str::<Value>(trimmed) else {
        return true;
    };
    let Some(object) = value.as_object() else {
        return true;
    };
    for key in ["code", "StatusCode", "status_code"] {
        if let Some(code) = object.get(key).and_then(Value::as_i64) {
            return code == 0;
        }
    }
    true
}

fn feishu_channel_message_id(request: &ChannelDeliveryRequest, body: &str) -> String {
    serde_json::from_str::<Value>(body)
        .ok()
        .and_then(|value| {
            value
                .pointer("/data/message_id")
                .or_else(|| value.pointer("/data/messageId"))
                .or_else(|| value.get("message_id"))
                .and_then(Value::as_str)
                .map(ToOwned::to_owned)
        })
        .unwrap_or_else(|| format!("feishu_webhook:{}", request.outbox_id))
}

fn feishu_provider_error(status: reqwest::StatusCode, body: &str) -> String {
    let trimmed = body.trim();
    if trimmed.is_empty() {
        return format!("Feishu webhook returned HTTP {status}");
    }
    let snippet: String = trimmed.chars().take(500).collect();
    format!("Feishu webhook returned HTTP {status}: {snippet}")
}

pub(crate) struct ChannelOutboxDeliveryRuntime<S, D> {
    store: S,
    deliverer: D,
    config: ChannelOutboxDeliveryConfig,
}

impl<S, D> ChannelOutboxDeliveryRuntime<S, D>
where
    S: ChannelOutboxDeliveryStore,
    D: ChannelMessageDeliverer,
{
    pub(crate) fn new(store: S, deliverer: D, config: ChannelOutboxDeliveryConfig) -> Self {
        Self {
            store,
            deliverer,
            config,
        }
    }

    pub(crate) async fn run_once(&self) -> Result<ChannelOutboxDeliverySummary, ChannelApiError> {
        let rows = self
            .store
            .claim_due_outbox(
                &self.config.worker_id,
                self.config.lease_seconds,
                self.config.batch_limit,
            )
            .await?;
        let mut summary = ChannelOutboxDeliverySummary {
            claimed: rows.len(),
            ..ChannelOutboxDeliverySummary::default()
        };

        for row in rows {
            let request = ChannelDeliveryRequest::from_outbox(&row);
            match self.deliverer.deliver(&request).await {
                Ok(ChannelDeliveryOutcome::Sent { channel_message_id }) => {
                    if self
                        .store
                        .mark_outbox_sent(&row.id, &self.config.worker_id, &channel_message_id)
                        .await?
                        .is_some()
                    {
                        summary.sent += 1;
                    } else {
                        summary.lost_lease += 1;
                    }
                }
                Ok(ChannelDeliveryOutcome::Failed {
                    error,
                    retry_after_seconds,
                }) => {
                    let retry_after =
                        retry_after_seconds.unwrap_or(self.config.default_retry_after_seconds);
                    if self
                        .store
                        .mark_outbox_failed(&row.id, &self.config.worker_id, &error, retry_after)
                        .await?
                        .is_some()
                    {
                        summary.failed += 1;
                    } else {
                        summary.lost_lease += 1;
                    }
                }
                Err(error) => {
                    summary.delivery_errors += 1;
                    if self
                        .store
                        .mark_outbox_failed(
                            &row.id,
                            &self.config.worker_id,
                            &error.message,
                            self.config.default_retry_after_seconds,
                        )
                        .await?
                        .is_some()
                    {
                        summary.failed += 1;
                    } else {
                        summary.lost_lease += 1;
                    }
                }
            }
        }

        Ok(summary)
    }
}

pub(crate) struct ChannelOutboxDeliveryWorker<S, D> {
    runtime: ChannelOutboxDeliveryRuntime<S, D>,
    config: ChannelOutboxDeliveryWorkerConfig,
}

impl<S, D> ChannelOutboxDeliveryWorker<S, D>
where
    S: ChannelOutboxDeliveryStore + Send + Sync + 'static,
    D: ChannelMessageDeliverer + Send + Sync + 'static,
{
    pub(crate) fn new(store: S, deliverer: D, config: ChannelOutboxDeliveryWorkerConfig) -> Self {
        Self {
            runtime: ChannelOutboxDeliveryRuntime::new(store, deliverer, config.delivery.clone()),
            config,
        }
    }

    pub(crate) fn spawn_if_enabled(self: Arc<Self>) -> Option<ChannelOutboxDeliveryWorkerRuntime> {
        if !self.config.autostart {
            return None;
        }
        if !self.config.production_ready {
            eprintln!(
                "[agistack] channel outbox delivery worker: autostart requested but production readiness gate is disabled (set {CHANNEL_OUTBOX_DELIVERY_PRODUCTION_READY_ENV}=true after provider parity); not consuming queue"
            );
            return None;
        }
        let worker = Arc::clone(&self);
        let join = tokio::spawn(async move {
            worker.run_loop().await;
        });
        Some(ChannelOutboxDeliveryWorkerRuntime { join: Some(join) })
    }

    pub(crate) async fn run_once(&self) -> Result<ChannelOutboxDeliverySummary, ChannelApiError> {
        self.runtime.run_once().await
    }

    async fn run_loop(self: Arc<Self>) {
        loop {
            if let Err(err) = self.run_once().await {
                eprintln!("[agistack] channel outbox delivery worker poll failed: {err:?}");
            }
            sleep(Duration::from_millis(
                self.config.poll_interval_millis.max(1),
            ))
            .await;
        }
    }
}

pub(crate) struct ChannelOutboxDeliveryWorkerRuntime {
    join: Option<JoinHandle<()>>,
}

impl ChannelOutboxDeliveryWorkerRuntime {
    #[cfg(test)]
    async fn shutdown(mut self) {
        if let Some(join) = self.join.take() {
            join.abort();
            let _ = join.await;
        }
    }
}

impl Drop for ChannelOutboxDeliveryWorkerRuntime {
    fn drop(&mut self) {
        if let Some(join) = &self.join {
            join.abort();
        }
    }
}

fn positive_i64_env(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn positive_millis_env(name: &str, default_millis: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value > 0.0)
        .map(|seconds| (seconds * 1000.0).ceil().max(1.0) as u64)
        .unwrap_or(default_millis)
}

fn bool_env(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .map(|raw| {
            matches!(
                raw.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, VecDeque};
    use std::sync::{Arc, Mutex};

    use axum::{
        extract::State,
        http::{HeaderMap, HeaderValue, StatusCode},
        routing::post,
        Json, Router,
    };
    use chrono::{DateTime, Utc};
    use tokio::net::TcpListener;

    use super::*;

    fn at(seconds: i64) -> DateTime<Utc> {
        DateTime::<Utc>::from_timestamp(seconds, 0).expect("test timestamp must be valid")
    }

    fn outbox(id: &str, content_text: &str) -> ChannelOutboxRecord {
        ChannelOutboxRecord {
            id: id.to_string(),
            project_id: "project-1".to_string(),
            channel_config_id: "chan-1".to_string(),
            channel_type: Some("feishu".to_string()),
            webhook_url: Some("https://example.test/hook".to_string()),
            domain: Some("feishu".to_string()),
            conversation_id: "conv-1".to_string(),
            chat_id: "oc-chat-1".to_string(),
            content_text: content_text.to_string(),
            status: "pending".to_string(),
            attempt_count: 1,
            max_attempts: 3,
            sent_channel_message_id: None,
            last_error: None,
            next_retry_at: None,
            created_at: at(1_700_000_000),
            updated_at: None,
        }
    }

    #[derive(Default, Clone)]
    struct FakeStore {
        state: Arc<Mutex<FakeStoreState>>,
    }

    #[derive(Default)]
    struct FakeStoreState {
        queue: VecDeque<ChannelOutboxRecord>,
        sent: Vec<(String, String, String)>,
        failed: Vec<(String, String, String, i64)>,
        lose_marks_for: Vec<String>,
        claim_calls: usize,
    }

    impl FakeStore {
        fn with_rows(rows: impl IntoIterator<Item = ChannelOutboxRecord>) -> Self {
            let store = Self::default();
            store.state.lock().expect("store state").queue = rows.into_iter().collect();
            store
        }

        fn lose_marks_for(&self, outbox_id: &str) {
            self.state
                .lock()
                .expect("store state")
                .lose_marks_for
                .push(outbox_id.to_string());
        }
    }

    #[async_trait]
    impl ChannelOutboxDeliveryStore for FakeStore {
        async fn claim_due_outbox(
            &self,
            _worker_id: &str,
            _lease_seconds: i64,
            limit: i64,
        ) -> Result<Vec<ChannelOutboxRecord>, ChannelApiError> {
            let mut state = self.state.lock().expect("store state");
            state.claim_calls += 1;
            let mut rows = Vec::new();
            for _ in 0..limit.max(0) {
                let Some(row) = state.queue.pop_front() else {
                    break;
                };
                rows.push(row);
            }
            Ok(rows)
        }

        async fn mark_outbox_sent(
            &self,
            outbox_id: &str,
            worker_id: &str,
            sent_channel_message_id: &str,
        ) -> Result<Option<ChannelOutboxRecord>, ChannelApiError> {
            let mut state = self.state.lock().expect("store state");
            if state.lose_marks_for.iter().any(|id| id == outbox_id) {
                return Ok(None);
            }
            state.sent.push((
                outbox_id.to_string(),
                worker_id.to_string(),
                sent_channel_message_id.to_string(),
            ));
            Ok(Some(outbox(outbox_id, "")))
        }

        async fn mark_outbox_failed(
            &self,
            outbox_id: &str,
            worker_id: &str,
            error: &str,
            retry_after_seconds: i64,
        ) -> Result<Option<ChannelOutboxRecord>, ChannelApiError> {
            let mut state = self.state.lock().expect("store state");
            if state.lose_marks_for.iter().any(|id| id == outbox_id) {
                return Ok(None);
            }
            state.failed.push((
                outbox_id.to_string(),
                worker_id.to_string(),
                error.to_string(),
                retry_after_seconds,
            ));
            Ok(Some(outbox(outbox_id, "")))
        }
    }

    #[derive(Default, Clone)]
    struct FakeDeliverer {
        outcomes: Arc<Mutex<BTreeMap<String, Result<ChannelDeliveryOutcome, String>>>>,
        requests: Arc<Mutex<Vec<ChannelDeliveryRequest>>>,
    }

    impl FakeDeliverer {
        fn set_outcome(&self, outbox_id: &str, outcome: Result<ChannelDeliveryOutcome, String>) {
            self.outcomes
                .lock()
                .expect("deliverer outcomes")
                .insert(outbox_id.to_string(), outcome);
        }
    }

    #[async_trait]
    impl ChannelMessageDeliverer for FakeDeliverer {
        async fn deliver(
            &self,
            request: &ChannelDeliveryRequest,
        ) -> Result<ChannelDeliveryOutcome, ChannelDeliveryError> {
            self.requests
                .lock()
                .expect("deliverer requests")
                .push(request.clone());
            self.outcomes
                .lock()
                .expect("deliverer outcomes")
                .get(&request.outbox_id)
                .cloned()
                .unwrap_or_else(|| {
                    Ok(ChannelDeliveryOutcome::Sent {
                        channel_message_id: format!("provider-{}", request.outbox_id),
                    })
                })
                .map_err(ChannelDeliveryError::new)
        }
    }

    fn runtime(
        store: FakeStore,
        deliverer: FakeDeliverer,
    ) -> ChannelOutboxDeliveryRuntime<FakeStore, FakeDeliverer> {
        ChannelOutboxDeliveryRuntime::new(
            store,
            deliverer,
            ChannelOutboxDeliveryConfig {
                worker_id: "worker-1".to_string(),
                lease_seconds: 30,
                batch_limit: 10,
                default_retry_after_seconds: 120,
            },
        )
    }

    fn worker_config(autostart: bool, production_ready: bool) -> ChannelOutboxDeliveryWorkerConfig {
        ChannelOutboxDeliveryWorkerConfig {
            delivery: ChannelOutboxDeliveryConfig {
                worker_id: "worker-1".to_string(),
                lease_seconds: 30,
                batch_limit: 10,
                default_retry_after_seconds: 120,
            },
            poll_interval_millis: 5,
            autostart,
            production_ready,
        }
    }

    #[derive(Clone)]
    struct MockFeishuWebhookState {
        status: StatusCode,
        retry_after: Option<&'static str>,
        body: Value,
        seen: Arc<Mutex<Vec<Value>>>,
    }

    async fn spawn_feishu_webhook_server(
        status: StatusCode,
        retry_after: Option<&'static str>,
        body: Value,
        seen: Arc<Mutex<Vec<Value>>>,
    ) -> String {
        async fn handler(
            State(state): State<MockFeishuWebhookState>,
            Json(payload): Json<Value>,
        ) -> (StatusCode, HeaderMap, Json<Value>) {
            state.seen.lock().expect("seen payloads").push(payload);
            let mut headers = HeaderMap::new();
            if let Some(seconds) = state.retry_after {
                headers.insert(
                    reqwest::header::RETRY_AFTER,
                    HeaderValue::from_static(seconds),
                );
            }
            (state.status, headers, Json(state.body))
        }

        let app = Router::new()
            .route("/hook", post(handler))
            .with_state(MockFeishuWebhookState {
                status,
                retry_after,
                body,
                seen,
            });
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind local webhook server");
        let addr = listener.local_addr().expect("local webhook addr");
        tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("webhook server serves");
        });
        format!("http://{addr}/hook")
    }

    #[tokio::test]
    async fn delivery_runtime_marks_sent_and_retryable_failures() {
        let store = FakeStore::with_rows([
            outbox("outbox-sent", "hello provider"),
            outbox("outbox-failed", "retry me"),
        ]);
        let deliverer = FakeDeliverer::default();
        deliverer.set_outcome(
            "outbox-sent",
            Ok::<_, String>(ChannelDeliveryOutcome::Sent {
                channel_message_id: "msg-provider-1".to_string(),
            }),
        );
        deliverer.set_outcome(
            "outbox-failed",
            Ok::<_, String>(ChannelDeliveryOutcome::Failed {
                error: "rate limited".to_string(),
                retry_after_seconds: Some(42),
            }),
        );

        let summary = runtime(store.clone(), deliverer.clone())
            .run_once()
            .await
            .expect("delivery run succeeds");

        assert_eq!(
            summary,
            ChannelOutboxDeliverySummary {
                claimed: 2,
                sent: 1,
                failed: 1,
                lost_lease: 0,
                delivery_errors: 0,
            }
        );
        let state = store.state.lock().expect("store state");
        assert_eq!(
            state.sent,
            vec![(
                "outbox-sent".to_string(),
                "worker-1".to_string(),
                "msg-provider-1".to_string()
            )]
        );
        assert_eq!(
            state.failed,
            vec![(
                "outbox-failed".to_string(),
                "worker-1".to_string(),
                "rate limited".to_string(),
                42
            )]
        );
        let requests = deliverer.requests.lock().expect("deliverer requests");
        assert_eq!(requests[0].content_text, "hello provider");
        assert_eq!(requests[0].project_id, "project-1");
    }

    #[test]
    fn feishu_webhook_payload_is_text_message_only() {
        let row = outbox("outbox-feishu", "hello Feishu");
        let request = ChannelDeliveryRequest::from_outbox(&row);

        assert_eq!(
            feishu_webhook_payload(&request),
            json!({
                "msg_type": "text",
                "content": {
                    "text": "hello Feishu"
                }
            })
        );
    }

    #[tokio::test]
    async fn feishu_webhook_deliverer_posts_payload_and_returns_provider_message_id() {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let webhook_url = spawn_feishu_webhook_server(
            StatusCode::OK,
            None,
            json!({"code": 0, "data": {"message_id": "om-message-1"}}),
            Arc::clone(&seen),
        )
        .await;
        let mut row = outbox("outbox-feishu", "hello provider");
        row.webhook_url = Some(webhook_url);
        let request = ChannelDeliveryRequest::from_outbox(&row);

        let outcome = FeishuWebhookDeliverer::default()
            .deliver(&request)
            .await
            .expect("delivery succeeds");

        assert_eq!(
            outcome,
            ChannelDeliveryOutcome::Sent {
                channel_message_id: "om-message-1".to_string()
            }
        );
        assert_eq!(
            seen.lock().expect("seen payloads").as_slice(),
            &[json!({
                "msg_type": "text",
                "content": {
                    "text": "hello provider"
                }
            })]
        );
    }

    #[tokio::test]
    async fn feishu_webhook_deliverer_maps_rate_limit_to_retryable_failure() {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let webhook_url = spawn_feishu_webhook_server(
            StatusCode::TOO_MANY_REQUESTS,
            Some("17"),
            json!({"code": 999, "msg": "rate limited"}),
            seen,
        )
        .await;
        let mut row = outbox("outbox-rate", "slow down");
        row.webhook_url = Some(webhook_url);
        let request = ChannelDeliveryRequest::from_outbox(&row);

        let outcome = FeishuWebhookDeliverer::default()
            .deliver(&request)
            .await
            .expect("provider failure is captured");

        assert_eq!(
            outcome,
            ChannelDeliveryOutcome::Failed {
                error: "Feishu webhook returned HTTP 429 Too Many Requests: {\"code\":999,\"msg\":\"rate limited\"}".to_string(),
                retry_after_seconds: Some(17),
            }
        );
    }

    #[tokio::test]
    async fn delivery_runtime_records_provider_errors_with_default_backoff() {
        let store = FakeStore::with_rows([outbox("outbox-error", "boom")]);
        let deliverer = FakeDeliverer::default();
        deliverer.set_outcome("outbox-error", Err("provider unavailable".to_string()));

        let summary = runtime(store.clone(), deliverer)
            .run_once()
            .await
            .expect("delivery run succeeds");

        assert_eq!(summary.claimed, 1);
        assert_eq!(summary.failed, 1);
        assert_eq!(summary.delivery_errors, 1);
        assert_eq!(
            store.state.lock().expect("store state").failed,
            vec![(
                "outbox-error".to_string(),
                "worker-1".to_string(),
                "provider unavailable".to_string(),
                120
            )]
        );
    }

    #[tokio::test]
    async fn delivery_runtime_reports_lost_lease_without_double_counting_delivery() {
        let store = FakeStore::with_rows([outbox("outbox-lost", "sent but lease expired")]);
        store.lose_marks_for("outbox-lost");
        let deliverer = FakeDeliverer::default();

        let summary = runtime(store, deliverer)
            .run_once()
            .await
            .expect("delivery run succeeds");

        assert_eq!(
            summary,
            ChannelOutboxDeliverySummary {
                claimed: 1,
                sent: 0,
                failed: 0,
                lost_lease: 1,
                delivery_errors: 0,
            }
        );
    }

    #[tokio::test]
    async fn delivery_worker_refuses_autostart_when_disabled_without_claiming() {
        let store = FakeStore::with_rows([outbox("outbox-safe", "do not claim")]);
        let worker = Arc::new(ChannelOutboxDeliveryWorker::new(
            store.clone(),
            FakeDeliverer::default(),
            worker_config(false, true),
        ));

        let runtime = worker.spawn_if_enabled();

        assert!(runtime.is_none());
        let state = store.state.lock().expect("store state");
        assert_eq!(state.claim_calls, 0);
        assert_eq!(state.queue.len(), 1);
    }

    #[tokio::test]
    async fn delivery_worker_refuses_autostart_without_production_ready_gate() {
        let store = FakeStore::with_rows([outbox("outbox-safe", "do not claim")]);
        let worker = Arc::new(ChannelOutboxDeliveryWorker::new(
            store.clone(),
            FakeDeliverer::default(),
            worker_config(true, false),
        ));

        let runtime = worker.spawn_if_enabled();

        assert!(runtime.is_none());
        let state = store.state.lock().expect("store state");
        assert_eq!(state.claim_calls, 0);
        assert_eq!(state.queue.len(), 1);
    }

    #[tokio::test]
    async fn delivery_worker_polls_until_stopped_when_gates_are_enabled() {
        let store = FakeStore::with_rows([outbox("outbox-loop", "ship it")]);
        let worker = Arc::new(ChannelOutboxDeliveryWorker::new(
            store.clone(),
            FakeDeliverer::default(),
            worker_config(true, true),
        ));
        let runtime = worker.spawn_if_enabled().expect("runtime should start");

        for _ in 0..20 {
            if store.state.lock().expect("store state").sent.len() == 1 {
                runtime.shutdown().await;
                let state = store.state.lock().expect("store state");
                assert_eq!(state.sent[0].0, "outbox-loop");
                assert!(state.claim_calls >= 1);
                return;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }

        runtime.shutdown().await;
        panic!("delivery worker did not poll before timeout");
    }
}
