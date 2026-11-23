//! Register a cloud run, execute it once on this machine, and upload the record.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use agistack_core::ports::{LlmPort, ToolHost};
use async_trait::async_trait;
use serde_json::{json, Value};

use crate::execute::execute_local_turn;
use crate::queue::UploadQueue;
use crate::redact::redact_uploaded_json;

static CANCELS: OnceLock<Mutex<HashMap<String, Arc<AtomicBool>>>> = OnceLock::new();

pub fn request_cancel(user_id: &str, device_id: &str, run_key: &str) -> Arc<AtomicBool> {
    let key = format!("{user_id}\u{0000}{device_id}\u{0000}{run_key}");
    let map = CANCELS.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = map.lock().expect("cancel map");
    let flag = guard
        .entry(key)
        .or_insert_with(|| Arc::new(AtomicBool::new(false)))
        .clone();
    flag.store(true, Ordering::Release);
    flag
}

fn cancel_flag(user_id: &str, device_id: &str, run_key: &str) -> Arc<AtomicBool> {
    let key = format!("{user_id}\u{0000}{device_id}\u{0000}{run_key}");
    let map = CANCELS.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = map.lock().expect("cancel map");
    guard
        .entry(key)
        .or_insert_with(|| Arc::new(AtomicBool::new(false)))
        .clone()
}

#[derive(Clone, Debug)]
pub struct CloudCall {
    pub method: &'static str,
    pub path: String,
    pub body: Value,
    pub authorization: String,
}

#[derive(Clone, Debug)]
pub struct CloudReply {
    pub status: u16,
    pub body: Value,
}

#[async_trait]
pub trait LocalRunCloud: Send + Sync {
    async fn send(&self, request: CloudCall) -> Result<CloudReply, String>;
}

pub struct ReqwestCloud {
    client: reqwest::Client,
}

impl ReqwestCloud {
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::new(),
        }
    }
}

impl Default for ReqwestCloud {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl LocalRunCloud for ReqwestCloud {
    async fn send(&self, request: CloudCall) -> Result<CloudReply, String> {
        let builder = match request.method {
            "POST" => self.client.post(&request.path),
            "PATCH" => self.client.patch(&request.path),
            _ => return Err("unsupported local-run method".to_string()),
        };
        let response = builder
            .header("authorization", request.authorization)
            .header("x-agi-surface", "desktop")
            .json(&request.body)
            .send()
            .await
            .map_err(|error| format!("local run upload failed: {error}"))?;
        let status = response.status().as_u16();
        let body = response.json::<Value>().await.unwrap_or(Value::Null);
        Ok(CloudReply { status, body })
    }
}

pub struct DriveRequest {
    pub user_id: String,
    pub device_id: String,
    pub conversation_id: String,
    pub idempotency_key: String,
    pub message: String,
    pub local_root: PathBuf,
    pub local_root_label: String,
    pub api_base_url: String,
    pub authorization: String,
    pub now_ms: i64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DriveReport {
    pub sync: String,
    pub run_id: Option<String>,
    pub status: String,
    pub late_terminal: bool,
    pub executed: bool,
    pub detail: String,
}

pub async fn drive_local_run(
    queue: &UploadQueue,
    cloud: &dyn LocalRunCloud,
    llm: Arc<dyn LlmPort>,
    tools: Arc<dyn ToolHost>,
    request: DriveRequest,
) -> DriveReport {
    let root = request.local_root.to_string_lossy().to_string();
    let message = match redact_uploaded_json(&Value::String(request.message.clone()), &root) {
        Value::String(text) => text,
        _ => "<redacted>".to_string(),
    };
    let cancel = cancel_flag(
        &request.user_id,
        &request.device_id,
        &request.idempotency_key,
    );
    let claim = match queue.claim(
        &request.user_id,
        &request.device_id,
        &request.idempotency_key,
    ) {
        Ok(claim) => claim,
        Err(error) => return failed_report(error.to_string()),
    };
    if let Some(existing) = &claim {
        if matches!(
            existing.state.as_str(),
            "finished" | "failed" | "uploading" | "executing"
        ) {
            let drained = drain(queue, cloud, &request, existing.run_id.clone()).await;
            return DriveReport {
                sync: drained.sync,
                run_id: existing.run_id.clone(),
                status: existing.state.clone(),
                late_terminal: false,
                executed: false,
                detail: "Local execution was not repeated. Upload state follows the durable queue."
                    .to_string(),
            };
        }
    }
    if queue
        .save_claim(
            &request.user_id,
            &request.device_id,
            &request.idempotency_key,
            claim.as_ref().and_then(|item| item.run_id.as_deref()),
            "reserving",
            request.now_ms,
        )
        .is_err()
    {
        return failed_report("UPLOAD_QUEUE_UNAVAILABLE".to_string());
    }
    let register_body = json!({
        "idempotency_key": request.idempotency_key,
        "message": message,
        "execution_machine_id": request.device_id,
        "local_root_label": request.local_root_label,
        "permission_mode": null,
    });
    if queue
        .enqueue(
            &request.user_id,
            &request.device_id,
            &request.idempotency_key,
            &request.conversation_id,
            "register",
            &register_body.to_string(),
            request.now_ms,
        )
        .is_err()
    {
        return failed_report("UPLOAD_QUEUE_FULL".to_string());
    }
    let registered = drain(queue, cloud, &request, None).await;
    if registered.sync == "conflict" || registered.sync == "failed" {
        let _ = queue.save_claim(
            &request.user_id,
            &request.device_id,
            &request.idempotency_key,
            None,
            "failed",
            request.now_ms,
        );
        return DriveReport {
            executed: false,
            ..registered
        };
    }
    if registered.sync == "pending" {
        let _ = queue.save_claim(
            &request.user_id,
            &request.device_id,
            &request.idempotency_key,
            None,
            "reserving",
            request.now_ms,
        );
        return DriveReport {
            executed: false,
            detail: "The cloud record is not synced yet. Local tools were not started.".to_string(),
            ..registered
        };
    }
    let run_id = registered.run_id.clone().unwrap_or_default();
    let revision = registered_revision(&registered);
    let profile = registered
        .detail
        .split(';')
        .find_map(|part| part.strip_prefix("profile="))
        .unwrap_or("read_only")
        .to_string();
    if cancel.load(Ordering::Acquire) {
        return finish_cancelled(queue, cloud, &request, &run_id, revision).await;
    }
    if queue
        .save_claim(
            &request.user_id,
            &request.device_id,
            &request.idempotency_key,
            Some(&run_id),
            "executing",
            request.now_ms,
        )
        .is_err()
    {
        return failed_report("UPLOAD_QUEUE_UNAVAILABLE".to_string());
    }
    let turn = execute_local_turn(
        llm,
        tools,
        &request.local_root,
        &profile,
        &message,
        &run_id,
        Arc::clone(&cancel),
    )
    .await;
    let _ = queue.save_claim(
        &request.user_id,
        &request.device_id,
        &request.idempotency_key,
        Some(&run_id),
        "uploading",
        request.now_ms,
    );
    let events = turn
        .events
        .iter()
        .enumerate()
        .map(|(index, event)| {
            json!({
                "seq": index + 1,
                "kind": event["kind"].as_str().unwrap_or("log"),
                "payload": redact_uploaded_json(&event["payload"], &root),
            })
        })
        .collect::<Vec<_>>();
    for batch_events in event_batches(events) {
        let batch = json!({
            "execution_machine_id": request.device_id,
            "events": batch_events,
        });
        if queue
            .enqueue(
                &request.user_id,
                &request.device_id,
                &request.idempotency_key,
                &request.conversation_id,
                "events",
                &batch.to_string(),
                request.now_ms,
            )
            .is_err()
        {
            return failed_report("UPLOAD_QUEUE_FULL".to_string());
        }
    }
    let terminal = json!({
        "expected_revision": revision,
        "status": turn.status,
        "execution_machine_id": request.device_id,
        "error": turn.error,
    });
    if queue
        .enqueue(
            &request.user_id,
            &request.device_id,
            &request.idempotency_key,
            &request.conversation_id,
            "terminal",
            &terminal.to_string(),
            request.now_ms,
        )
        .is_err()
    {
        return failed_report("UPLOAD_QUEUE_FULL".to_string());
    }
    let uploaded = drain(queue, cloud, &request, Some(run_id.clone())).await;
    let final_state = if uploaded.sync == "synced" {
        "finished"
    } else if uploaded.sync == "pending" {
        "uploading"
    } else {
        "failed"
    };
    let _ = queue.save_claim(
        &request.user_id,
        &request.device_id,
        &request.idempotency_key,
        Some(&run_id),
        final_state,
        request.now_ms,
    );
    DriveReport {
        executed: true,
        run_id: Some(run_id),
        ..uploaded
    }
}

async fn finish_cancelled(
    queue: &UploadQueue,
    cloud: &dyn LocalRunCloud,
    request: &DriveRequest,
    run_id: &str,
    revision: i64,
) -> DriveReport {
    let terminal = json!({
        "expected_revision": revision,
        "status": "cancelled",
        "execution_machine_id": request.device_id,
        "error": null,
    });
    if queue
        .enqueue(
            &request.user_id,
            &request.device_id,
            &request.idempotency_key,
            &request.conversation_id,
            "terminal",
            &terminal.to_string(),
            request.now_ms,
        )
        .is_err()
    {
        return failed_report("UPLOAD_QUEUE_FULL".to_string());
    }
    let uploaded = drain(queue, cloud, request, Some(run_id.to_string())).await;
    let _ = queue.save_claim(
        &request.user_id,
        &request.device_id,
        &request.idempotency_key,
        Some(run_id),
        "finished",
        request.now_ms,
    );
    DriveReport {
        executed: false,
        status: "cancelled".to_string(),
        ..uploaded
    }
}

const MAX_BATCH_EVENTS: usize = 32;
const MAX_BATCH_BYTES: usize = 200 * 1024;

fn event_batches(events: Vec<Value>) -> Vec<Vec<Value>> {
    let mut batches = Vec::new();
    let mut current = Vec::new();
    let mut size = 96usize;
    for event in events.into_iter().map(fit_event_wire) {
        let length = serde_json::to_string(&event)
            .map(|text| text.len())
            .unwrap_or(0)
            + 1;
        if !current.is_empty()
            && (current.len() >= MAX_BATCH_EVENTS || size + length > MAX_BATCH_BYTES)
        {
            batches.push(std::mem::take(&mut current));
            size = 96;
        }
        size += length;
        current.push(event);
    }
    if !current.is_empty() {
        batches.push(current);
    }
    batches
}

fn fit_event_wire(mut event: Value) -> Value {
    let length = serde_json::to_string(&event)
        .map(|text| text.len())
        .unwrap_or(0);
    if length <= 180 * 1024 {
        return event;
    }
    if let Some(payload) = event.get_mut("payload").and_then(Value::as_object_mut) {
        payload.remove("content_base64");
        payload.insert("artifact_rejected".to_string(), json!("too_large"));
    }
    event
}

pub async fn resume_pending_uploads(
    queue: &UploadQueue,
    cloud: &dyn LocalRunCloud,
    user_id: &str,
    device_id: &str,
    api_base_url: &str,
    authorization: &str,
    now_ms: i64,
) -> Vec<DriveReport> {
    let keys = match queue.pending_run_keys(user_id, device_id, now_ms) {
        Ok(keys) => keys,
        Err(error) => return vec![failed_report(error.to_string())],
    };
    let mut reports = Vec::new();
    for (run_key, conversation_id) in keys {
        let known_run_id = queue
            .claim(user_id, device_id, &run_key)
            .ok()
            .flatten()
            .and_then(|claim| claim.run_id);
        let request = DriveRequest {
            user_id: user_id.to_string(),
            device_id: device_id.to_string(),
            conversation_id,
            idempotency_key: run_key,
            message: String::new(),
            local_root: PathBuf::new(),
            local_root_label: String::new(),
            api_base_url: api_base_url.to_string(),
            authorization: authorization.to_string(),
            now_ms,
        };
        reports.push(drain(queue, cloud, &request, known_run_id).await);
    }
    reports
}

struct DrainState {
    sync: String,
    run_id: Option<String>,
    status: String,
    late_terminal: bool,
    detail: String,
}

async fn drain(
    queue: &UploadQueue,
    cloud: &dyn LocalRunCloud,
    request: &DriveRequest,
    known_run_id: Option<String>,
) -> DriveReport {
    let mut state = DrainState {
        sync: "synced".to_string(),
        run_id: known_run_id,
        status: "queued".to_string(),
        late_terminal: false,
        detail: String::new(),
    };
    loop {
        let due = match queue.due_for_run(
            &request.user_id,
            &request.device_id,
            &request.idempotency_key,
            request.now_ms,
        ) {
            Ok(items) => items,
            Err(error) => return failed_report(error.to_string()),
        };
        let Some(item) = due.into_iter().next() else {
            break;
        };
        let body = serde_json::from_str::<Value>(&item.body).unwrap_or(Value::Null);
        let call = match item.kind.as_str() {
            "register" => CloudCall {
                method: "POST",
                path: format!(
                    "{}/api/v1/agent/conversations/{}/local-runs",
                    request.api_base_url.trim_end_matches('/'),
                    item.conversation_id
                ),
                body,
                authorization: request.authorization.clone(),
            },
            "events" => {
                let Some(run_id) = state.run_id.clone() else {
                    let _ = queue.mark_failed(item.id, "LOCAL_RUN_NOT_REGISTERED", request.now_ms);
                    return failed_report("LOCAL_RUN_NOT_REGISTERED".to_string());
                };
                CloudCall {
                    method: "POST",
                    path: format!(
                        "{}/api/v1/agent/runs/{run_id}/events:batch",
                        request.api_base_url.trim_end_matches('/')
                    ),
                    body,
                    authorization: request.authorization.clone(),
                }
            }
            "terminal" => {
                let Some(run_id) = state.run_id.clone() else {
                    let _ = queue.mark_failed(item.id, "LOCAL_RUN_NOT_REGISTERED", request.now_ms);
                    return failed_report("LOCAL_RUN_NOT_REGISTERED".to_string());
                };
                CloudCall {
                    method: "PATCH",
                    path: format!(
                        "{}/api/v1/agent/runs/{run_id}/local-terminal",
                        request.api_base_url.trim_end_matches('/')
                    ),
                    body,
                    authorization: request.authorization.clone(),
                }
            }
            _ => {
                let _ = queue.mark_failed(item.id, "LOCAL_RUN_QUEUE_KIND", request.now_ms);
                continue;
            }
        };
        match cloud.send(call).await {
            Ok(reply) if (200..300).contains(&reply.status) => {
                if item.kind == "register" {
                    state.run_id = reply
                        .body
                        .get("run_id")
                        .and_then(Value::as_str)
                        .map(str::to_string);
                    state.status = reply
                        .body
                        .get("status")
                        .and_then(Value::as_str)
                        .unwrap_or("queued")
                        .to_string();
                    let profile = reply
                        .body
                        .get("permission_profile")
                        .and_then(Value::as_str)
                        .unwrap_or("read_only");
                    let revision = reply
                        .body
                        .get("revision")
                        .and_then(Value::as_i64)
                        .unwrap_or(1);
                    state.detail = format!("profile={profile};revision={revision}");
                }
                if item.kind == "terminal" {
                    state.late_terminal = reply
                        .body
                        .get("late_terminal")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    state.status = reply
                        .body
                        .get("status")
                        .and_then(Value::as_str)
                        .unwrap_or(&state.status)
                        .to_string();
                }
                let _ = queue.mark_acked(item.id, request.now_ms);
            }
            Ok(reply) if matches!(reply.status, 409 | 401 | 403 | 413 | 422) => {
                let _ = queue.mark_failed(item.id, "LOCAL_RUN_UPLOAD_REJECTED", request.now_ms);
                return DriveReport {
                    sync: if reply.status == 409 {
                        "conflict"
                    } else {
                        "failed"
                    }
                    .to_string(),
                    run_id: state.run_id,
                    status: state.status,
                    late_terminal: false,
                    executed: false,
                    detail: "The cloud rejected the upload. It was not retried or overwritten."
                        .to_string(),
                };
            }
            Ok(reply) => {
                if item.attempts + 1 >= queue.limits().max_attempts {
                    let _ =
                        queue.mark_failed(item.id, "LOCAL_RUN_UPLOAD_EXHAUSTED", request.now_ms);
                    return failed_report(format!("upload failed with status {}", reply.status));
                }
                let _ = queue.mark_retry(item.id, "retryable", request.now_ms + 1);
                return DriveReport {
                    sync: "pending".to_string(),
                    run_id: state.run_id,
                    status: state.status,
                    late_terminal: false,
                    executed: false,
                    detail: "The cloud record is not synced yet.".to_string(),
                };
            }
            Err(_) => {
                if item.attempts + 1 >= queue.limits().max_attempts {
                    let _ =
                        queue.mark_failed(item.id, "LOCAL_RUN_UPLOAD_EXHAUSTED", request.now_ms);
                    return failed_report("upload failed".to_string());
                }
                let _ = queue.mark_retry(item.id, "network", request.now_ms + 1);
                return DriveReport {
                    sync: "pending".to_string(),
                    run_id: state.run_id,
                    status: state.status,
                    late_terminal: false,
                    executed: false,
                    detail: "The cloud record is not synced yet.".to_string(),
                };
            }
        }
    }
    DriveReport {
        sync: state.sync,
        run_id: state.run_id,
        status: state.status,
        late_terminal: state.late_terminal,
        executed: false,
        detail: if state.detail.is_empty() {
            "Local run record is on the cloud.".to_string()
        } else {
            state.detail
        },
    }
}

fn registered_revision(report: &DriveReport) -> i64 {
    report
        .detail
        .split("revision=")
        .nth(1)
        .and_then(|value| value.parse().ok())
        .unwrap_or(1)
}

fn failed_report(detail: String) -> DriveReport {
    DriveReport {
        sync: "failed".to_string(),
        run_id: None,
        status: "failed".to_string(),
        late_terminal: false,
        executed: false,
        detail,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::queue::{production_limits, UploadLimits, UploadQueue};
    use agistack_adapters_local_tools::LocalToolHost;
    use agistack_adapters_mem::llm::ScriptedLlm;
    use agistack_core::agent::types::AgentAction;
    use std::sync::atomic::{AtomicUsize, Ordering as AtomicOrdering};

    struct ScriptCloud {
        hits: AtomicUsize,
        conflict_on: Option<&'static str>,
        fail_times: AtomicUsize,
    }

    #[async_trait]
    impl LocalRunCloud for ScriptCloud {
        async fn send(&self, request: CloudCall) -> Result<CloudReply, String> {
            self.hits.fetch_add(1, AtomicOrdering::SeqCst);
            if self.fail_times.load(AtomicOrdering::SeqCst) > 0 {
                self.fail_times.fetch_sub(1, AtomicOrdering::SeqCst);
                return Err("offline".to_string());
            }
            if self
                .conflict_on
                .is_some_and(|kind| request.path.contains(kind) || request.method == kind)
            {
                return Ok(CloudReply {
                    status: 409,
                    body: json!({"code": "LOCAL_RUN_EVENT_CONFLICT"}),
                });
            }
            if request.path.ends_with("/local-runs") {
                return Ok(CloudReply {
                    status: 200,
                    body: json!({
                        "run_id": "run-1",
                        "revision": 1,
                        "status": "queued",
                        "permission_profile": "read_only",
                        "upload_state": "pending"
                    }),
                });
            }
            if request.path.contains("events:batch") {
                let body = request.body.to_string();
                assert!(!body.contains("/Users/alice"));
                assert!(!body.contains("Bearer secret-token"));
                return Ok(CloudReply {
                    status: 200,
                    body: json!({"accepted_through_seq": 1, "upload_state": "events_accepted"}),
                });
            }
            Ok(CloudReply {
                status: 200,
                body: json!({"status": "completed", "revision": 2, "late_terminal": false, "upload_state": "synced"}),
            })
        }
    }

    fn queue() -> (UploadQueue, PathBuf) {
        let path = std::env::temp_dir().join(format!(
            "local-run-drive-{}-{}.db",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let queue = UploadQueue::open(&path, production_limits()).expect("queue");
        (queue, path)
    }

    fn request(root: PathBuf) -> DriveRequest {
        DriveRequest {
            user_id: "alice".to_string(),
            device_id: "machine-a1".to_string(),
            conversation_id: "conv-1".to_string(),
            idempotency_key: "local-key-001".to_string(),
            message: "list /Users/alice/src/agi-demos".to_string(),
            local_root: root.clone(),
            local_root_label: "agi-demos".to_string(),
            api_base_url: "https://cloud.example".to_string(),
            authorization: "Bearer secret-token".to_string(),
            now_ms: 50,
        }
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn executes_once_uploads_redacted_events_and_does_not_repeat() {
        let root =
            std::env::temp_dir().join(format!("local-run-drive-root-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).expect("root");
        let (queue, path) = queue();
        let cloud = ScriptCloud {
            hits: AtomicUsize::new(0),
            conflict_on: None,
            fail_times: AtomicUsize::new(0),
        };
        let llm = Arc::new(ScriptedLlm::new(vec![
            AgentAction::CallTool {
                tool: "list".to_string(),
                input_json: "{}".to_string(),
            },
            AgentAction::Finish {
                answer: "done".to_string(),
            },
        ]));
        let tools = Arc::new(LocalToolHost::new(&root).expect("host"));
        let report = drive_local_run(&queue, &cloud, llm, tools, request(root.clone())).await;
        assert_eq!(report.sync, "synced");
        assert_eq!(report.executed, true);
        assert!(!queue.contains_text("Bearer secret-token").expect("scan"));
        assert!(!queue.contains_text("/Users/alice").expect("scan"));
        let hits = cloud.hits.load(AtomicOrdering::SeqCst);
        let llm = Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "again".to_string(),
        }]));
        let tools = Arc::new(LocalToolHost::new(&root).expect("host"));
        let second = drive_local_run(&queue, &cloud, llm, tools, request(root.clone())).await;
        assert_eq!(second.executed, false);
        assert_eq!(cloud.hits.load(AtomicOrdering::SeqCst), hits);
        let _ = std::fs::remove_file(path);
        let _ = std::fs::remove_dir_all(root);
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn conflict_stops_without_a_blind_retry() {
        let root = std::env::temp_dir().join(format!("local-run-conflict-{}", std::process::id()));
        std::fs::create_dir_all(&root).expect("root");
        let (queue, path) = queue();
        let cloud = ScriptCloud {
            hits: AtomicUsize::new(0),
            conflict_on: Some("events:batch"),
            fail_times: AtomicUsize::new(0),
        };
        let llm = Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "done".to_string(),
        }]));
        let tools = Arc::new(LocalToolHost::new(&root).expect("host"));
        let report = drive_local_run(&queue, &cloud, llm, tools, request(root.clone())).await;
        assert_eq!(report.sync, "conflict");
        let hits = cloud.hits.load(AtomicOrdering::SeqCst);
        let llm = Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "done".to_string(),
        }]));
        let tools = Arc::new(LocalToolHost::new(&root).expect("host"));
        let _ = drive_local_run(&queue, &cloud, llm, tools, request(root.clone())).await;
        assert!(cloud.hits.load(AtomicOrdering::SeqCst) <= hits + 1);
        let _ = std::fs::remove_file(path);
        let _ = std::fs::remove_dir_all(root);
    }

    #[tokio::test]
    async fn network_failure_stays_pending_and_does_not_claim_synced() {
        let (queue, path) = queue();
        let cloud = ScriptCloud {
            hits: AtomicUsize::new(0),
            conflict_on: None,
            fail_times: AtomicUsize::new(1),
        };
        let llm = Arc::new(ScriptedLlm::new(vec![]));
        let root = std::env::temp_dir();
        let tools = Arc::new(LocalToolHost::new(&root).expect("host"));
        let report = drive_local_run(&queue, &cloud, llm, tools, request(root)).await;
        assert_eq!(report.sync, "pending");
        assert_ne!(report.sync, "synced");
        assert!(!report.executed);
        let _ = std::fs::remove_file(path);
        let _ = UploadLimits {
            max_bytes: 1,
            retention_ms: 1,
            max_attempts: 1,
        };
    }

    struct PathCloud {
        paths: std::sync::Mutex<Vec<String>>,
    }

    #[async_trait]
    impl LocalRunCloud for PathCloud {
        async fn send(&self, request: CloudCall) -> Result<CloudReply, String> {
            self.paths.lock().expect("paths").push(request.path.clone());
            if request.path.contains("/conversations/") {
                let conversation = request
                    .path
                    .split("/conversations/")
                    .nth(1)
                    .unwrap_or("missing")
                    .trim_end_matches("/local-runs");
                return Ok(CloudReply {
                    status: 200,
                    body: json!({
                        "run_id": format!("run-{conversation}"),
                        "revision": 1,
                        "status": "queued",
                        "permission_profile": "read_only"
                    }),
                });
            }
            Ok(CloudReply {
                status: 200,
                body: json!({"status": "completed", "late_terminal": false, "upload_state": "synced"}),
            })
        }
    }

    #[tokio::test]
    async fn resume_drains_each_run_on_its_own_conversation() {
        let (queue, path) = queue();
        queue
            .enqueue(
                "alice",
                "machine-a1",
                "key-a",
                "conv-a",
                "register",
                r#"{"idempotency_key":"key-a","message":"a","execution_machine_id":"machine-a1","local_root_label":"demo"}"#,
                10,
            )
            .expect("enqueue a");
        queue
            .enqueue(
                "alice",
                "machine-a1",
                "key-b",
                "conv-b",
                "register",
                r#"{"idempotency_key":"key-b","message":"b","execution_machine_id":"machine-a1","local_root_label":"demo"}"#,
                10,
            )
            .expect("enqueue b");
        let cloud = PathCloud {
            paths: std::sync::Mutex::new(Vec::new()),
        };
        let reports = resume_pending_uploads(
            &queue,
            &cloud,
            "alice",
            "machine-a1",
            "https://cloud.example",
            "Bearer secret-token",
            10,
        )
        .await;
        assert_eq!(reports.len(), 2);
        assert!(reports.iter().all(|report| report.sync == "synced"));
        let paths = cloud.paths.lock().expect("paths").clone();
        assert!(paths
            .iter()
            .any(|path| path.contains("/conversations/conv-a/")));
        assert!(paths
            .iter()
            .any(|path| path.contains("/conversations/conv-b/")));
        assert!(!paths
            .iter()
            .any(|path| path.contains("conv-a") && path.contains("conv-b")));
        let _ = std::fs::remove_file(path);
    }
}
