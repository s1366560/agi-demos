//! Control-plane entry for a cloud-registered local run.
//!
//! The conversation and run live in the cloud. This machine only executes tools
//! and uploads the redacted record.

use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use agistack_local_run_upload::{
    drive_local_run, production_limits, request_cancel, resume_pending_uploads, DriveRequest,
    LocalRunCloud, ReqwestCloud, UploadQueue,
};
use serde::Deserialize;
use serde_json::{json, Value};

use super::{
    llm_from_runtime_binding, LocalRuntimeService, LocalRuntimeState, LocalToolHost,
    ProviderRuntimeKey, UnconfiguredLocalLlm,
};
use agistack_core::ports::ToolHost;
use std::sync::Arc;

#[derive(Deserialize)]
struct ExecuteArgs {
    user_id: String,
    tenant_id: String,
    device_id: String,
    conversation_id: String,
    idempotency_key: String,
    message: String,
    local_root: String,
    local_root_label: String,
    api_base_url: String,
    authorization: String,
}

#[derive(Deserialize)]
struct StopArgs {
    user_id: String,
    device_id: String,
    idempotency_key: String,
    run_id: Option<String>,
    expected_revision: Option<i64>,
    api_base_url: String,
    authorization: String,
}

impl LocalRuntimeService {
    pub(crate) async fn execute_uploaded_local_run(&self, args: Value) -> Result<Value, String> {
        execute_in_workspace(&self.state, args, None, None).await
    }
    pub(crate) async fn stop_uploaded_local_run(&self, args: Value) -> Result<Value, String> {
        stop_in_workspace(args).await
    }
}

pub(super) async fn execute_in_workspace(
    state: &LocalRuntimeState,
    args: Value,
    approved_tools: Option<Arc<dyn ToolHost>>,
    approved_llm: Option<Arc<dyn agistack_core::ports::LlmPort>>,
) -> Result<Value, String> {
    let parsed: ExecuteArgs =
        serde_json::from_value(args).map_err(|_| "local_run_request_invalid".to_string())?;
    let root = PathBuf::from(parsed.local_root.trim());
    if !root.is_absolute() || parsed.local_root_label.contains(['/', '\\', ':']) {
        return Err("local_run_root_invalid".to_string());
    }
    if parsed.authorization.trim().is_empty() || parsed.api_base_url.trim().is_empty() {
        return Err("local_run_cloud_session_unavailable".to_string());
    }
    let data_dir = state
        .app_data_dir
        .clone()
        .ok_or_else(|| "local_run_data_directory_unavailable".to_string())?;
    let queue_path = data_dir.join("local-run-upload.db");
    let queue =
        UploadQueue::open(&queue_path, production_limits()).map_err(|error| error.to_string())?;
    let _ = resume_pending_uploads(
        &queue,
        &ReqwestCloud::new(),
        &parsed.user_id,
        &parsed.device_id,
        &parsed.api_base_url,
        &parsed.authorization,
        now_ms(),
    )
    .await;
    let tools: Arc<dyn ToolHost> = match approved_tools {
        Some(tools) => tools,
        None => Arc::new(LocalToolHost::new(&root).map_err(|error| error.to_string())?),
    };
    let llm = approved_llm.unwrap_or_else(|| llm_for_tenant(state, &parsed.tenant_id));
    let report = drive_local_run(
        &queue,
        &ReqwestCloud::new(),
        llm,
        tools,
        DriveRequest {
            user_id: parsed.user_id.clone(),
            device_id: parsed.device_id.clone(),
            conversation_id: parsed.conversation_id,
            idempotency_key: parsed.idempotency_key,
            message: parsed.message,
            local_root: root,
            local_root_label: parsed.local_root_label,
            api_base_url: parsed.api_base_url.clone(),
            authorization: parsed.authorization.clone(),
            now_ms: now_ms(),
        },
    )
    .await;
    if report.sync == "pending" {
        schedule_upload_resume(
            queue_path,
            parsed.user_id.clone(),
            parsed.device_id.clone(),
            parsed.api_base_url.clone(),
            parsed.authorization.clone(),
        );
    }
    Ok(json!({
        "sync": report.sync,
        "run_id": report.run_id,
        "status": report.status,
        "late_terminal": report.late_terminal,
        "executed": report.executed,
        "detail": report.detail,
    }))
}

pub(super) async fn stop_in_workspace(args: Value) -> Result<Value, String> {
    let parsed: StopArgs =
        serde_json::from_value(args).map_err(|_| "local_run_stop_invalid".to_string())?;
    request_cancel(&parsed.user_id, &parsed.device_id, &parsed.idempotency_key);
    if let Some(run_id) = parsed.run_id.as_deref() {
        let revision = parsed.expected_revision.unwrap_or(1);
        let response = ReqwestCloud::new()
            .send(agistack_local_run_upload::CloudCall {
                method: "POST",
                path: format!(
                    "{}/api/v1/agent/runs/{run_id}/local-stop",
                    parsed.api_base_url.trim_end_matches('/')
                ),
                body: json!({
                    "expected_revision": revision,
                    "execution_machine_id": parsed.device_id,
                }),
                authorization: parsed.authorization,
            })
            .await?;
        if !(200..300).contains(&response.status) {
            return Err("local_run_stop_rejected".to_string());
        }
        return Ok(response.body);
    }
    Ok(json!({
        "sync": "pending",
        "status": "cancel_requested",
        "detail": "Stop was requested. The cloud record is not synced yet.",
    }))
}

fn schedule_upload_resume(
    queue_path: PathBuf,
    user_id: String,
    device_id: String,
    api_base_url: String,
    authorization: String,
) {
    tokio::spawn(async move {
        for step in 0..5 {
            tokio::time::sleep(std::time::Duration::from_secs(1_u64 << step)).await;
            let Ok(queue) = UploadQueue::open(&queue_path, production_limits()) else {
                return;
            };
            let reports = resume_pending_uploads(
                &queue,
                &ReqwestCloud::new(),
                &user_id,
                &device_id,
                &api_base_url,
                &authorization,
                now_ms(),
            )
            .await;
            if reports.iter().all(|report| report.sync != "pending") {
                return;
            }
        }
    });
}

pub(super) fn llm_for_tenant(
    state: &LocalRuntimeState,
    tenant_id: &str,
) -> std::sync::Arc<dyn agistack_core::ports::LlmPort> {
    let Some(route) = state.selected_provider_route(tenant_id) else {
        return std::sync::Arc::new(UnconfiguredLocalLlm);
    };
    let key = ProviderRuntimeKey {
        tenant_id: tenant_id.to_string(),
        provider_id: route.provider_id,
    };
    let runtime = match state.provider_runtime.lock() {
        Ok(runtime) => runtime,
        Err(_) => return std::sync::Arc::new(UnconfiguredLocalLlm),
    };
    let Some(mut binding) = runtime.bindings.get(&key).cloned() else {
        return std::sync::Arc::new(UnconfiguredLocalLlm);
    };
    binding.model.clone_from(&route.model_id);
    let credential = runtime.credentials.get(&key).cloned();
    drop(runtime);
    llm_from_runtime_binding(binding, credential)
        .unwrap_or_else(|| std::sync::Arc::new(UnconfiguredLocalLlm))
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or(0)
}
