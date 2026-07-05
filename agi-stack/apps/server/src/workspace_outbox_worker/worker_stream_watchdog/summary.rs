#[cfg(test)]
use super::WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS;
use super::WORKER_STREAM_COMPLETION_SUMMARY_CHARS;

#[cfg(test)]
pub(in crate::workspace_outbox_worker) fn worker_launch_started_summary(
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
fn compact_progress_text(value: Option<&str>) -> String {
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

pub(in crate::workspace_outbox_worker) fn stream_completion_summary(
    final_content: &str,
    accumulated_text: &str,
) -> String {
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

pub(super) fn bounded_terminal_summary(value: &str, default: &str) -> String {
    let trimmed = value.trim();
    let summary = if trimmed.is_empty() { default } else { trimmed };
    if summary.chars().count() > WORKER_STREAM_COMPLETION_SUMMARY_CHARS {
        let end = char_prefix_boundary(summary, WORKER_STREAM_COMPLETION_SUMMARY_CHARS);
        summary[..end].to_string()
    } else {
        summary.to_string()
    }
}

fn char_prefix_boundary(value: &str, max_chars: usize) -> usize {
    value
        .char_indices()
        .nth(max_chars)
        .map(|(index, _)| index)
        .unwrap_or(value.len())
}
