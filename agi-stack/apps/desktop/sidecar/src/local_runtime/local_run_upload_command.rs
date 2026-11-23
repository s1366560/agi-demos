//! Control-plane entry for a cloud-registered local run.
//!
//! The conversation and run live in the cloud. This machine only executes tools
//! and uploads the redacted record.

use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use agistack_local_run_upload::{
    drive_local_run, production_limits, request_cancel, DriveRequest, LocalRunCloud, ReqwestCloud,
    UploadQueue,
};
use serde::Deserialize;
use serde_json::{json, Value};

use super::{
    llm_from_runtime_binding, LocalRuntimeService, LocalRuntimeState, LocalToolHost,
    ProviderRuntimeKey, UnconfiguredLocalLlm,
};

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
        let parsed: ExecuteArgs =
            serde_json::from_value(args).map_err(|_| "local_run_request_invalid".to_string())?;
        let root = PathBuf::from(parsed.local_root.trim());
        if !root.is_absolute() || parsed.local_root_label.contains(['/', '\\', ':']) {
            return Err("local_run_root_invalid".to_string());
        }
        if parsed.authorization.trim().is_empty() || parsed.api_base_url.trim().is_empty() {
            return Err("local_run_cloud_session_unavailable".to_string());
        }
        let data_dir = self
            .state
            .app_data_dir
            .clone()
            .ok_or_else(|| "local_run_data_directory_unavailable".to_string())?;
        let queue = UploadQueue::open(&data_dir.join("local-run-upload.db"), production_limits())
            .map_err(|error| error.to_string())?;
        let tools = LocalToolHost::new(&root).map_err(|error| error.to_string())?;
        let llm = llm_for_tenant(&self.state, &parsed.tenant_id);
        let report = drive_local_run(
            &queue,
            &ReqwestCloud::new(),
            llm,
            std::sync::Arc::new(tools),
            DriveRequest {
                user_id: parsed.user_id,
                device_id: parsed.device_id,
                conversation_id: parsed.conversation_id,
                idempotency_key: parsed.idempotency_key,
                message: parsed.message,
                local_root: root,
                local_root_label: parsed.local_root_label,
                api_base_url: parsed.api_base_url,
                authorization: parsed.authorization,
                now_ms: now_ms(),
            },
        )
        .await;
        Ok(json!({
            "sync": report.sync,
            "run_id": report.run_id,
            "status": report.status,
            "late_terminal": report.late_terminal,
            "executed": report.executed,
            "detail": report.detail,
        }))
    }

    pub(crate) async fn stop_uploaded_local_run(&self, args: Value) -> Result<Value, String> {
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
                .await
                .map_err(|error| error)?;
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
}

fn llm_for_tenant(
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
