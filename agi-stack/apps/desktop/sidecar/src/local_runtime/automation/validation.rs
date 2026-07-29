use std::str::FromStr;

use axum::{http::StatusCode, Json};
use chrono::DateTime;
use chrono_tz::Tz;
use croner::Cron;
use serde_json::Value;

use super::{
    error, error_with_code, AutomationConfig, CreateAutomationRequest, RunAutomationRequest,
    UpdateAutomationRequest, AUTOMATION_RUN_CONTRACT_VERSION, DEFAULT_TIMEOUT_SECONDS,
};

pub(super) fn validate_create(
    request: &CreateAutomationRequest,
) -> Result<(), (StatusCode, Json<Value>)> {
    validate_idempotency_key(&request.idempotency_key)?;
    validate_name(&request.name)?;
    validate_config(&request.schedule, &["at", "every", "cron"], "schedule")?;
    validate_schedule_config(&request.schedule)?;
    validate_config(&request.payload, &["system_event", "agent_turn"], "payload")?;
    validate_payload_config(&request.payload)?;
    validate_config(
        &request.delivery,
        &["none", "announce", "webhook"],
        "delivery",
    )?;
    validate_local_delivery(&request.delivery)?;
    validate_conversation_mode(&request.conversation_mode)?;
    validate_optional_id(request.workspace_id.as_deref(), "workspace_id")?;
    validate_optional_id(request.conversation_id.as_deref(), "conversation_id")?;
    validate_timezone(&request.timezone)?;
    validate_runtime_limits(request.timeout_seconds, request.max_retries)
}

pub(super) fn validate_update(
    request: &UpdateAutomationRequest,
) -> Result<(), (StatusCode, Json<Value>)> {
    validate_idempotency_key(&request.idempotency_key)?;
    if let Some(name) = request.name.as_deref() {
        validate_name(name)?;
    }
    if let Some(schedule) = request.schedule.as_ref() {
        validate_config(schedule, &["at", "every", "cron"], "schedule")?;
        validate_schedule_config(schedule)?;
    }
    if let Some(payload) = request.payload.as_ref() {
        validate_config(payload, &["system_event", "agent_turn"], "payload")?;
        validate_payload_config(payload)?;
    }
    if let Some(delivery) = request.delivery.as_ref() {
        validate_config(delivery, &["none", "announce", "webhook"], "delivery")?;
        validate_local_delivery(delivery)?;
    }
    if let Some(mode) = request.conversation_mode.as_deref() {
        validate_conversation_mode(mode)?;
    }
    validate_optional_id(request.workspace_id.as_deref(), "workspace_id")?;
    validate_optional_id(request.conversation_id.as_deref(), "conversation_id")?;
    if let Some(timezone) = request.timezone.as_deref() {
        validate_timezone(timezone)?;
    }
    validate_runtime_limits(
        request.timeout_seconds.unwrap_or(DEFAULT_TIMEOUT_SECONDS),
        request.max_retries.unwrap_or_default(),
    )
}

pub(super) fn validate_run(
    request: &RunAutomationRequest,
) -> Result<(), (StatusCode, Json<Value>)> {
    if request.contract_version != AUTOMATION_RUN_CONTRACT_VERSION {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "automation_contract_version_unsupported",
            "contract_version must be 2",
        ));
    }
    if request.expected_revision == 0 {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "automation_expected_revision_invalid",
            "expected_revision must be a positive integer",
        ));
    }
    validate_run_idempotency_key(&request.idempotency_key)?;
    if request
        .conversation_id
        .as_deref()
        .is_some_and(|value| value.trim().is_empty())
    {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "automation_conversation_id_invalid",
            "conversation_id must not be empty",
        ));
    }
    Ok(())
}

fn validate_local_delivery(delivery: &AutomationConfig) -> Result<(), (StatusCode, Json<Value>)> {
    if delivery.kind == "webhook" {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "local_automation_webhook_delivery_unavailable",
            "webhook delivery has no local execution authority",
        ));
    }
    Ok(())
}

fn validate_optional_id(value: Option<&str>, field: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if value.is_some_and(|value| value.trim().is_empty() || value.len() > 255) {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "automation_execution_target_invalid",
            format!("{field} must contain between 1 and 255 characters"),
        ));
    }
    Ok(())
}

fn validate_schedule_config(schedule: &AutomationConfig) -> Result<(), (StatusCode, Json<Value>)> {
    let valid = match schedule.kind.as_str() {
        "at" => schedule
            .config
            .get("run_at")
            .or_else(|| schedule.config.get("target_time"))
            .and_then(Value::as_str)
            .is_some_and(|value| DateTime::parse_from_rfc3339(value).is_ok()),
        "every" => schedule
            .config
            .get("interval_seconds")
            .and_then(Value::as_u64)
            .is_some_and(|value| value > 0),
        "cron" => schedule
            .config
            .get("expr")
            .or_else(|| schedule.config.get("expression"))
            .and_then(Value::as_str)
            .is_some_and(|value| Cron::from_str(value).is_ok()),
        _ => false,
    };
    if !valid {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "local_automation_schedule_invalid",
            "schedule config is invalid",
        ));
    }
    Ok(())
}

fn validate_payload_config(payload: &AutomationConfig) -> Result<(), (StatusCode, Json<Value>)> {
    let field = match payload.kind.as_str() {
        "agent_turn" => "message",
        "system_event" => "content",
        _ => {
            return Err(error_with_code(
                StatusCode::UNPROCESSABLE_ENTITY,
                "local_automation_payload_invalid",
                "payload config is invalid",
            ));
        }
    };
    let content = payload
        .config
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim);
    if !matches!(content, Some(value) if !value.is_empty()) {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "local_automation_payload_invalid",
            "payload config is invalid",
        ));
    }
    Ok(())
}

fn validate_timezone(timezone: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if Tz::from_str(timezone).is_err() {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "local_automation_timezone_invalid",
            "timezone is invalid",
        ));
    }
    Ok(())
}

pub(super) fn validate_idempotency_key(value: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if value.trim().is_empty() || value.len() > 200 {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "idempotency_key must contain between 1 and 200 characters",
        ));
    }
    Ok(())
}

fn validate_run_idempotency_key(value: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if value.is_empty()
        || value.len() > 255
        || !value
            .as_bytes()
            .iter()
            .all(|byte| (33..=126).contains(byte))
    {
        return Err(error_with_code(
            StatusCode::UNPROCESSABLE_ENTITY,
            "automation_idempotency_key_invalid",
            "idempotency_key must contain 1 to 255 visible ASCII characters",
        ));
    }
    Ok(())
}

fn validate_name(value: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if value.trim().is_empty() || value.len() > 200 {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "name must contain between 1 and 200 characters",
        ));
    }
    Ok(())
}

fn validate_config(
    config: &AutomationConfig,
    allowed: &[&str],
    field: &str,
) -> Result<(), (StatusCode, Json<Value>)> {
    if !allowed.contains(&config.kind.as_str()) {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("unsupported {field} kind"),
        ));
    }
    Ok(())
}

fn validate_conversation_mode(value: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if !matches!(value, "reuse" | "fresh") {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "conversation_mode must be reuse or fresh",
        ));
    }
    Ok(())
}

fn validate_runtime_limits(
    timeout_seconds: u64,
    max_retries: u64,
) -> Result<(), (StatusCode, Json<Value>)> {
    if timeout_seconds == 0 || timeout_seconds > 86_400 {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "timeout_seconds must be between 1 and 86400",
        ));
    }
    if max_retries > 20 {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "max_retries must be less than or equal to 20",
        ));
    }
    Ok(())
}
