use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(in crate::workspace_outbox_worker) enum TerminalReportToolStatus {
    Denied,
    Applied,
    Attempted,
}

impl TerminalReportToolStatus {
    #[cfg(test)]
    pub(in crate::workspace_outbox_worker) fn as_str(self) -> &'static str {
        match self {
            Self::Denied => "denied",
            Self::Applied => "applied",
            Self::Attempted => "attempted",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(in crate::workspace_outbox_worker) enum TerminalReportType {
    Completed,
    Blocked,
}

impl TerminalReportType {
    pub(in crate::workspace_outbox_worker) fn as_str(self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Blocked => "blocked",
        }
    }
}

pub(in crate::workspace_outbox_worker) fn terminal_report_tool_observation_status(
    event: &Value,
) -> Option<TerminalReportToolStatus> {
    if event.get("type").and_then(Value::as_str) != Some("observe") {
        return None;
    }
    let data = event.get("data")?.as_object()?;
    let _report_type = terminal_report_type_for_tool(data.get("tool_name")?)?;
    if data.get("error").is_some_and(json_truthy) {
        return Some(TerminalReportToolStatus::Denied);
    }
    Some(terminal_report_tool_result_status(data.get("result")))
}

pub(in crate::workspace_outbox_worker) fn terminal_report_tool_report_type(
    event: &Value,
) -> Option<TerminalReportType> {
    if event.get("type").and_then(Value::as_str) != Some("observe") {
        return None;
    }
    let data = event.get("data")?.as_object()?;
    terminal_report_type_for_tool(data.get("tool_name")?)
}

pub(in crate::workspace_outbox_worker) fn terminal_report_metadata_matches_attempt(
    metadata: Option<&Value>,
    attempt_id: Option<&str>,
    report_type: Option<&str>,
) -> bool {
    let Some(attempt_id) = attempt_id.filter(|value| !value.is_empty()) else {
        return false;
    };
    let Some(metadata) = metadata.and_then(Value::as_object) else {
        return false;
    };
    if metadata
        .get("last_worker_report_attempt_id")
        .and_then(Value::as_str)
        != Some(attempt_id)
    {
        return false;
    }
    match report_type.filter(|value| !value.is_empty()) {
        Some(report_type) => {
            metadata
                .get("last_worker_report_type")
                .and_then(Value::as_str)
                == Some(report_type)
        }
        None => true,
    }
}

pub(in crate::workspace_outbox_worker) fn should_reconcile_terminal_report_tool(
    terminal_report_tool_applied: bool,
    report_recorded_for_attempt: bool,
) -> bool {
    terminal_report_tool_applied && !report_recorded_for_attempt
}

pub(in crate::workspace_outbox_worker) fn should_synthesize_stream_completion_report(
    terminal_report_tool_observed: bool,
) -> bool {
    !terminal_report_tool_observed
}

fn terminal_report_type_for_tool(value: &Value) -> Option<TerminalReportType> {
    match value.as_str()?.trim() {
        "workspace_report_complete" => Some(TerminalReportType::Completed),
        "workspace_report_blocked" => Some(TerminalReportType::Blocked),
        _ => None,
    }
}

fn terminal_report_tool_result_status(result: Option<&Value>) -> TerminalReportToolStatus {
    let result_text = result.and_then(Value::as_str).unwrap_or("");
    if let Ok(Value::Object(parsed)) = serde_json::from_str::<Value>(result_text) {
        if let Some(status) = parsed_terminal_report_tool_status(&parsed) {
            return status;
        }
    }
    let lowered = result_text.to_lowercase();
    if lowered.contains("completion denied:")
        || lowered.contains("terminal_report_apply_failed")
        || lowered.contains("\"error\"")
    {
        TerminalReportToolStatus::Denied
    } else {
        TerminalReportToolStatus::Attempted
    }
}

fn parsed_terminal_report_tool_status(
    parsed: &serde_json::Map<String, Value>,
) -> Option<TerminalReportToolStatus> {
    if let Some(applied_report) = parsed.get("applied_report").and_then(Value::as_object) {
        if applied_report
            .get("skipped_supervisor_only")
            .and_then(Value::as_bool)
            == Some(true)
        {
            return Some(TerminalReportToolStatus::Attempted);
        }
        if applied_report.get("applied").and_then(Value::as_bool) == Some(true) {
            return Some(TerminalReportToolStatus::Applied);
        }
    }
    if parsed.get("ok").and_then(Value::as_bool) == Some(true) {
        return Some(TerminalReportToolStatus::Applied);
    }
    if parsed.get("error").is_some_and(json_truthy) {
        return Some(TerminalReportToolStatus::Denied);
    }
    None
}

fn json_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}
