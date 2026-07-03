use super::*;

pub(super) fn metadata_string_from_path(value: &Value, path: &[&str]) -> Option<String> {
    let mut cursor = value;
    for key in path {
        cursor = cursor.get(*key)?;
    }
    metadata_string(Some(cursor))
}

pub(super) fn accepted_attempt_matches_node_expected_commit(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> bool {
    let Some(expected) = node_expected_commit_ref(node) else {
        return true;
    };
    let actual_refs = attempt_commit_refs(attempt);
    if actual_refs.is_empty() {
        return last_verified_attempt_matches_expected_commit(node, attempt, &expected);
    }
    if actual_refs
        .iter()
        .any(|actual| git_commit_refs_match(&expected, actual))
    {
        return true;
    }
    last_verified_attempt_contains_attempt_commit(node, attempt, &actual_refs)
}

pub(super) fn attempt_cancelled_because_parent_done_without_output(
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> bool {
    attempt_cancelled_because_parent_done(attempt) && !attempt_has_candidate_output(attempt)
}

pub(super) fn attempt_cancelled_because_parent_done(
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> bool {
    if attempt.status.trim().to_ascii_lowercase() != "cancelled" {
        return false;
    }
    attempt.adjudication_reason.as_deref() == Some("recovery:parent_done")
        || attempt.leader_feedback.as_deref() == Some("recovery:parent_done")
}

pub(super) fn accepted_attempt_evidence_refs(
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Vec<String> {
    let mut refs = Vec::new();
    for artifact in &attempt.candidate_artifacts_json {
        let artifact = artifact.trim();
        if artifact.is_empty() {
            continue;
        }
        if artifact.starts_with("artifact:") {
            refs.push(artifact.to_string());
        } else {
            refs.push(format!("artifact:{artifact}"));
        }
    }
    for verification in &attempt.candidate_verifications_json {
        let verification = verification.trim();
        if !verification.is_empty() {
            refs.push(verification.to_string());
        }
    }
    dedup_strings(&mut refs);
    refs
}

pub(super) fn first_valid_commit_ref(refs: &[String]) -> Option<String> {
    refs.iter()
        .filter_map(|reference| prefixed_ref(reference, "commit_ref:"))
        .filter_map(|value| commit_ref_token(&value))
        .next()
}

pub(super) fn first_prefixed_ref(refs: &[String], prefix: &str) -> Option<String> {
    refs.iter()
        .filter_map(|reference| prefixed_ref(reference, prefix))
        .next()
}

pub(super) fn prefixed_refs(refs: &[String], prefix: &str) -> Vec<String> {
    refs.iter()
        .filter_map(|reference| prefixed_ref(reference, prefix))
        .collect()
}

pub(super) fn attempt_commit_refs(attempt: &WorkspaceTaskSessionAttemptRecord) -> Vec<String> {
    let mut refs: Vec<String> = accepted_attempt_evidence_refs(attempt)
        .iter()
        .filter_map(|reference| prefixed_ref(reference, "commit_ref:"))
        .filter_map(|value| commit_ref_token(&value))
        .collect();
    dedup_strings(&mut refs);
    refs
}

pub(super) fn node_expected_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    if let Some(Value::Object(checkpoint)) = &node.feature_checkpoint_json {
        if let Some(token) = commit_ref_token(checkpoint.get("commit_ref")?.as_str()?) {
            return Some(token);
        }
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    for key in [
        "source_publish_source_commit_ref",
        "verified_commit_ref",
        "worktree_integration_commit_ref",
    ] {
        if let Some(token) = metadata
            .get(key)
            .and_then(Value::as_str)
            .and_then(commit_ref_token)
        {
            return Some(token);
        }
    }
    None
}

pub(super) fn last_verified_attempt_matches_expected_commit(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    expected: &str,
) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
    if metadata
        .get("last_verification_passed")
        .and_then(Value::as_bool)
        != Some(true)
        || metadata
            .get("last_verification_attempt_id")
            .and_then(Value::as_str)
            != Some(attempt.id.as_str())
    {
        return false;
    }
    let mut refs = node_metadata_commit_refs(&metadata);
    for key in [
        "source_publish_source_commit_ref",
        "source_publish_commit_ref",
        "verified_commit_ref",
        "worktree_integration_commit_ref",
    ] {
        if let Some(token) = metadata
            .get(key)
            .and_then(Value::as_str)
            .and_then(commit_ref_token)
        {
            refs.push(token);
        }
    }
    dedup_strings(&mut refs);
    refs.iter()
        .any(|metadata_ref| git_commit_refs_match(expected, metadata_ref))
}

pub(super) fn last_verified_attempt_contains_attempt_commit(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    actual_refs: &[String],
) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
    if metadata
        .get("last_verification_passed")
        .and_then(Value::as_bool)
        != Some(true)
        || metadata
            .get("last_verification_attempt_id")
            .and_then(Value::as_str)
            != Some(attempt.id.as_str())
    {
        return false;
    }
    let metadata_refs = node_metadata_commit_refs(&metadata);
    metadata_refs.iter().any(|metadata_ref| {
        actual_refs
            .iter()
            .any(|actual_ref| git_commit_refs_match(metadata_ref, actual_ref))
    })
}

pub(super) fn node_metadata_commit_refs(metadata: &Map<String, Value>) -> Vec<String> {
    let mut refs = Vec::new();
    for key in [
        "verification_evidence_refs",
        "candidate_artifacts",
        "candidate_verifications",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "execution_verifications",
    ] {
        for value in metadata_string_values(metadata.get(key)) {
            if let Some(token) = prefixed_ref(&value, "commit_ref:")
                .and_then(|candidate| commit_ref_token(&candidate))
            {
                refs.push(token);
            }
        }
    }
    dedup_strings(&mut refs);
    refs
}

pub(super) fn prefixed_ref(reference: &str, prefix: &str) -> Option<String> {
    let trimmed = reference.trim();
    if trimmed.starts_with(prefix) {
        return Some(trimmed[prefix.len()..].trim().to_string());
    }
    let artifact_prefix = format!("artifact:{prefix}");
    if trimmed.starts_with(&artifact_prefix) {
        return Some(trimmed[artifact_prefix.len()..].trim().to_string());
    }
    None
}

pub(super) fn commit_ref_token(value: &str) -> Option<String> {
    let token = value.split_whitespace().next()?.trim();
    if (6..=40).contains(&token.len()) && token.chars().all(|ch| ch.is_ascii_hexdigit()) {
        Some(token.to_string())
    } else {
        None
    }
}

pub(super) fn git_commit_refs_match(left: &str, right: &str) -> bool {
    let left = left.trim();
    let right = right.trim();
    if left.is_empty() || right.is_empty() {
        return false;
    }
    left == right
        || (left.len() >= 7 && right.starts_with(left))
        || (right.len() >= 7 && left.starts_with(right))
}

pub(super) fn metadata_string_values(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(values)) => values
            .iter()
            .filter_map(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned)
            .collect(),
        Some(Value::String(value)) if !value.trim().is_empty() => vec![value.trim().to_string()],
        _ => Vec::new(),
    }
}

pub(super) fn reset_feature_checkpoint(value: Option<Value>) -> Option<Value> {
    match value {
        Some(Value::Object(mut checkpoint)) => {
            checkpoint.insert("worktree_path".to_string(), Value::Null);
            checkpoint.insert("branch_name".to_string(), Value::Null);
            checkpoint.insert("base_ref".to_string(), json!("HEAD"));
            checkpoint.insert("commit_ref".to_string(), Value::Null);
            Some(Value::Object(checkpoint))
        }
        other => other,
    }
}

pub(super) fn dedup_strings(values: &mut Vec<String>) {
    let mut deduped = Vec::with_capacity(values.len());
    for value in values.drain(..) {
        if !deduped.contains(&value) {
            deduped.push(value);
        }
    }
    *values = deduped;
}

pub(super) fn metadata_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}
