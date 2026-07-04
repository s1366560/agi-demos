#[cfg(test)]
use super::WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS;
use super::{
    DEFAULT_WORKER_STREAM_IDLE_PROGRESS_INTERVAL_SECONDS,
    DEFAULT_WORKER_STREAM_ORPHAN_GRACE_SECONDS, WORKER_STREAM_COMPLETION_SUMMARY_CHARS,
};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum StopReason {
    AgentFinishedWithoutTerminalEvent,
    AgentNotRunningStreamIdle,
}

impl StopReason {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::AgentFinishedWithoutTerminalEvent => "agent_finished_without_terminal_event",
            Self::AgentNotRunningStreamIdle => "agent_not_running_stream_idle",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct Decision {
    pub(super) should_stop: bool,
    pub(super) reason: Option<StopReason>,
}

pub(super) fn should_stop(
    finished_message_id: Option<&str>,
    stream_message_id: Option<&str>,
    running_exists: bool,
    idle_seconds: f64,
    orphan_grace_seconds: Option<i64>,
) -> Decision {
    if let Some(finished_message_id) = finished_message_id.filter(|value| !value.is_empty()) {
        if stream_message_id.is_none() || stream_message_id == Some(finished_message_id) {
            return Decision {
                should_stop: true,
                reason: Some(StopReason::AgentFinishedWithoutTerminalEvent),
            };
        }
    }

    let grace_seconds = orphan_grace_seconds
        .unwrap_or(DEFAULT_WORKER_STREAM_ORPHAN_GRACE_SECONDS)
        .max(1) as f64;
    if !running_exists && idle_seconds >= grace_seconds {
        return Decision {
            should_stop: true,
            reason: Some(StopReason::AgentNotRunningStreamIdle),
        };
    }

    Decision {
        should_stop: false,
        reason: None,
    }
}

pub(super) fn message_id_from_event(event: &Value) -> Option<&str> {
    if event.get("type").and_then(Value::as_str) != Some("message") {
        return None;
    }
    let data = event.get("data")?.as_object()?;
    data.get("id")
        .or_else(|| data.get("message_id"))
        .and_then(Value::as_str)
        .filter(|message_id| !message_id.is_empty())
}

pub(super) fn should_publish_idle_progress(
    idle_seconds: f64,
    last_published_at: f64,
    now: f64,
    interval_seconds: Option<i64>,
) -> bool {
    let interval = interval_seconds
        .unwrap_or(DEFAULT_WORKER_STREAM_IDLE_PROGRESS_INTERVAL_SECONDS)
        .max(1) as f64;
    if idle_seconds < interval {
        return false;
    }
    last_published_at <= 0.0 || now - last_published_at >= interval
}

pub(super) fn idle_progress_summary(
    idle_seconds: f64,
    last_stream_event_type: Option<&str>,
    running_exists: bool,
    finished_message_id: Option<&str>,
) -> String {
    let marker_state = if running_exists {
        "agent:running present"
    } else {
        "agent:running missing"
    };
    let mut parts = vec![
        format!(
            "Worker stream still active; no new visible stream event for {}s",
            idle_seconds as i64
        ),
        marker_state.to_string(),
    ];
    if let Some(event_type) = last_stream_event_type.filter(|value| !value.is_empty()) {
        parts.push(format!("last_event={event_type}"));
    }
    if let Some(finished_message_id) = finished_message_id.filter(|value| !value.is_empty()) {
        parts.push(format!("agent:finished={finished_message_id}"));
    }
    parts.join("; ")
}

#[cfg(test)]
pub(super) fn worker_launch_started_summary(
    attempt_number: Option<&str>,
    repair_brief_prompt: Option<&str>,
) -> String {
    let attempt_label = attempt_number
        .filter(|value| !value.is_empty())
        .map(|value| format!("attempt #{value}"))
        .unwrap_or_else(|| "attempt".to_string());
    let repair_summary = compact_progress_text(repair_brief_prompt);
    if repair_summary.is_empty() {
        return format!("Worker {attempt_label} started; session is bound and streaming.");
    }
    format!("Worker {attempt_label} started from verifier feedback: {repair_summary}")
}

#[cfg(test)]
pub(super) fn compact_progress_text(value: Option<&str>) -> String {
    let Some(value) = value else {
        return String::new();
    };
    let collapsed = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.is_empty() {
        return collapsed;
    }
    if collapsed.chars().count() <= WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS {
        return collapsed;
    }
    let end = char_prefix_boundary(&collapsed, WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS - 1);
    format!("{}...", collapsed[..end].trim_end())
}

pub(super) fn stream_completion_summary(final_content: &str, accumulated_text: &str) -> String {
    let mut summary = if final_content.is_empty() {
        accumulated_text.trim().to_string()
    } else {
        final_content.trim().to_string()
    };
    if summary.is_empty() {
        summary =
            "Worker stream completed without an explicit workspace terminal report.".to_string();
    }
    if summary.chars().count() > WORKER_STREAM_COMPLETION_SUMMARY_CHARS {
        let end = char_prefix_boundary(&summary, WORKER_STREAM_COMPLETION_SUMMARY_CHARS - 3);
        summary = format!("{}...", &summary[..end]);
    }
    summary
}

pub(super) fn should_synthesize_stream_completion_report(
    terminal_report_tool_observed: bool,
) -> bool {
    !terminal_report_tool_observed
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum TerminalReportToolStatus {
    Denied,
    Applied,
    Attempted,
}

impl TerminalReportToolStatus {
    #[cfg(test)]
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::Denied => "denied",
            Self::Applied => "applied",
            Self::Attempted => "attempted",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum TerminalReportType {
    Completed,
    Blocked,
}

impl TerminalReportType {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Blocked => "blocked",
        }
    }
}

pub(super) fn terminal_report_tool_observation_status(
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

pub(super) fn terminal_report_tool_report_type(event: &Value) -> Option<TerminalReportType> {
    if event.get("type").and_then(Value::as_str) != Some("observe") {
        return None;
    }
    let data = event.get("data")?.as_object()?;
    terminal_report_type_for_tool(data.get("tool_name")?)
}

pub(super) fn terminal_report_metadata_matches_attempt(
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

pub(super) fn should_reconcile_terminal_report_tool(
    terminal_report_tool_applied: bool,
    report_recorded_for_attempt: bool,
) -> bool {
    terminal_report_tool_applied && !report_recorded_for_attempt
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum StreamTerminalEvent {
    Complete,
    Error,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub(super) struct StreamState {
    pub(super) final_content: String,
    pub(super) accumulated_text: String,
    pub(super) terminal_event: Option<StreamTerminalEvent>,
    pub(super) stream_message_id: Option<String>,
    pub(super) terminal_report_tool_observed: bool,
    pub(super) terminal_report_tool_denied: bool,
    pub(super) terminal_report_tool_applied: bool,
    pub(super) terminal_report_tool_report_type: Option<TerminalReportType>,
    pub(super) last_stream_event_type: Option<String>,
}

impl StreamState {
    pub(super) fn observe_event(&mut self, event: &Value) -> Option<StreamTerminalEvent> {
        if self.stream_message_id.is_none() {
            self.stream_message_id = message_id_from_event(event).map(ToOwned::to_owned);
        }
        let event_type = event
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        self.last_stream_event_type = Some(event_type.to_string());
        match event_type {
            "text_delta" => {
                if let Some(text) = event
                    .get("data")
                    .and_then(Value::as_object)
                    .and_then(|data| data.get("text"))
                    .and_then(Value::as_str)
                {
                    self.accumulated_text.push_str(text);
                }
                None
            }
            "observe" => {
                if let Some(status) = terminal_report_tool_observation_status(event) {
                    self.terminal_report_tool_observed = true;
                    if let Some(report_type) = terminal_report_tool_report_type(event) {
                        self.terminal_report_tool_report_type = Some(report_type);
                    }
                    match status {
                        TerminalReportToolStatus::Denied => {
                            self.terminal_report_tool_denied = true;
                        }
                        TerminalReportToolStatus::Applied => {
                            self.terminal_report_tool_applied = true;
                        }
                        TerminalReportToolStatus::Attempted => {}
                    }
                }
                None
            }
            "complete" => {
                self.terminal_event = Some(StreamTerminalEvent::Complete);
                self.final_content = event
                    .get("data")
                    .and_then(Value::as_object)
                    .and_then(|data| data.get("content"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                if self.final_content.is_empty() && !self.accumulated_text.is_empty() {
                    self.final_content = self.accumulated_text.clone();
                }
                self.terminal_event
            }
            "error" => {
                self.terminal_event = Some(StreamTerminalEvent::Error);
                self.final_content = event
                    .get("data")
                    .and_then(Value::as_object)
                    .and_then(|data| data.get("message"))
                    .and_then(Value::as_str)
                    .unwrap_or("Worker stream reported an error")
                    .to_string();
                self.terminal_event
            }
            _ => None,
        }
    }

    #[cfg(test)]
    pub(super) fn mark_stream_ended_without_terminal(&mut self) {
        self.final_content =
            "Worker stream ended without a terminal complete/error event.".to_string();
        self.terminal_event = None;
    }

    pub(super) fn mark_orphaned_stream_stop(&mut self, reason: Option<&str>) {
        let reason = reason.unwrap_or("unknown");
        self.final_content =
            format!("Worker stream stopped without a terminal complete/error event ({reason}).");
        self.terminal_event = None;
    }

    pub(super) fn terminal_outcome(&self, report_recorded_for_attempt: bool) -> TerminalOutcome {
        match self.terminal_event {
            Some(StreamTerminalEvent::Complete) => {
                let summary =
                    stream_completion_summary(&self.final_content, &self.accumulated_text);
                if should_synthesize_stream_completion_report(self.terminal_report_tool_observed) {
                    return TerminalOutcome {
                        outcome_reason: "completed",
                        launch_state: "completed_via_stream",
                        report_type: Some(TerminalReportType::Completed),
                        summary,
                        should_report: true,
                        should_reconcile: false,
                    };
                }
                if should_reconcile_terminal_report_tool(
                    self.terminal_report_tool_applied,
                    report_recorded_for_attempt,
                ) {
                    return TerminalOutcome {
                        outcome_reason: "terminal_report_tool_reconciled",
                        launch_state: "terminal_report_tool_reconciled",
                        report_type: Some(
                            self.terminal_report_tool_report_type
                                .unwrap_or(TerminalReportType::Completed),
                        ),
                        summary,
                        should_report: true,
                        should_reconcile: true,
                    };
                }
                let outcome_reason = if self.terminal_report_tool_applied {
                    "terminal_report_tool_applied"
                } else if self.terminal_report_tool_denied {
                    "terminal_report_tool_denied"
                } else {
                    "terminal_report_tool_observed"
                };
                TerminalOutcome {
                    outcome_reason,
                    launch_state: outcome_reason,
                    report_type: None,
                    summary,
                    should_report: false,
                    should_reconcile: false,
                }
            }
            Some(StreamTerminalEvent::Error) => TerminalOutcome {
                outcome_reason: "blocked",
                launch_state: "blocked",
                report_type: Some(TerminalReportType::Blocked),
                summary: bounded_terminal_summary(&self.final_content, "Worker stream errored."),
                should_report: true,
                should_reconcile: false,
            },
            None => {
                if self.terminal_report_tool_applied {
                    TerminalOutcome {
                        outcome_reason: "terminal_report_tool_applied",
                        launch_state: "terminal_report_tool_applied",
                        report_type: None,
                        summary: bounded_terminal_summary(&self.final_content, ""),
                        should_report: false,
                        should_reconcile: false,
                    }
                } else {
                    TerminalOutcome {
                        outcome_reason: "no_terminal_event",
                        launch_state: "no_terminal_event",
                        report_type: Some(TerminalReportType::Blocked),
                        summary: bounded_terminal_summary(
                            &self.final_content,
                            "Worker stream ended without a terminal complete/error event and without a workspace_report_complete/workspace_report_blocked tool call.",
                        ),
                        should_report: true,
                        should_reconcile: false,
                    }
                }
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct TerminalOutcome {
    pub(super) outcome_reason: &'static str,
    pub(super) launch_state: &'static str,
    pub(super) report_type: Option<TerminalReportType>,
    pub(super) summary: String,
    pub(super) should_report: bool,
    pub(super) should_reconcile: bool,
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

fn bounded_terminal_summary(value: &str, default: &str) -> String {
    let trimmed = value.trim();
    let summary = if trimmed.is_empty() { default } else { trimmed };
    if summary.chars().count() > WORKER_STREAM_COMPLETION_SUMMARY_CHARS {
        let end = char_prefix_boundary(summary, WORKER_STREAM_COMPLETION_SUMMARY_CHARS);
        summary[..end].to_string()
    } else {
        summary.to_string()
    }
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

fn char_prefix_boundary(value: &str, max_chars: usize) -> usize {
    value
        .char_indices()
        .nth(max_chars)
        .map(|(index, _)| index)
        .unwrap_or(value.len())
}
