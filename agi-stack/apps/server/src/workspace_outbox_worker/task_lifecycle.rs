use super::*;

pub(super) fn accepted_attempt_projection_base_metadata(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Map<String, Value> {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    metadata.remove("terminal_attempt_retry_count");
    metadata.remove("terminal_attempt_retry_reason");
    metadata.remove("retry_not_before");
    if !attempt_commit_refs(attempt).is_empty() {
        return metadata;
    }
    for key in NO_COMMIT_ACCEPTED_ATTEMPT_STALE_METADATA_KEYS {
        metadata.remove(key);
    }
    metadata
}

pub(super) fn accepted_attempt_projection_feature_checkpoint(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Option<Value> {
    if !attempt_commit_refs(attempt).is_empty() || node.feature_checkpoint_json.is_none() {
        return node.feature_checkpoint_json.clone();
    }
    reset_feature_checkpoint(node.feature_checkpoint_json.clone())
}

pub(super) fn accepted_worktree_projection_complete_for_node(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    metadata: &Map<String, Value>,
) -> bool {
    let has_commit_for_integration = !attempt_commit_refs(attempt).is_empty()
        || accepted_attempt_integration_commit_ref(node).is_some();
    if !has_commit_for_integration {
        return true;
    }
    let status = metadata_string(metadata.get("worktree_integration_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    WORKTREE_INTEGRATION_DONE_STATUSES.contains(&status.as_str())
}

pub(super) fn done_node_needs_worktree_integration_retry(node: &WorkspacePlanNodeRecord) -> bool {
    if node.intent != "done" || node.execution != "idle" {
        return false;
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    if metadata_string(metadata.get("worktree_integration_status")).as_deref() != Some("failed") {
        return false;
    }
    dependency_commit_needs_integration(node, &metadata)
}

pub(super) fn dependency_commit_needs_integration(
    node: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
) -> bool {
    if node_disposition_satisfies_dependency_without_integration(metadata) {
        return false;
    }
    if node_verified_commit_ref(node).is_none() {
        return false;
    }
    let Some(worktree_path) = node_attempt_worktree_path(node, metadata) else {
        return false;
    };
    if !looks_like_attempt_worktree(&worktree_path) {
        return false;
    }
    let status = metadata_string(metadata.get("worktree_integration_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    if status == "failed"
        && metadata
            .get("terminal_attempt_status")
            .and_then(Value::as_str)
            == Some("accepted")
        && metadata
            .get("worktree_integration_dirty_signature")
            .is_none_or(Value::is_null)
        && metadata_string(metadata.get("worktree_integration_summary"))
            .unwrap_or_default()
            .to_ascii_lowercase()
            .contains("commit_ref not found in attempt worktree")
    {
        return false;
    }
    !matches!(status.as_str(), "merged" | "already_merged" | "skipped")
}

pub(super) fn dirty_main_dependency_dispatch_candidate(node: &WorkspacePlanNodeRecord) -> bool {
    if node.intent != "todo" || node.execution != "idle" || node.depends_on_json.is_empty() {
        return false;
    }
    if node
        .current_attempt_id
        .as_deref()
        .is_some_and(|attempt_id| !attempt_id.trim().is_empty())
    {
        return false;
    }
    if node.workspace_task_id.as_deref().is_none_or(str::is_empty) {
        return false;
    }
    metadata_string(
        object_or_empty(node.metadata_json.clone()).get("dirty_main_dependency_dispatch_outbox_id"),
    )
    .is_none()
}

pub(super) fn dependency_dispatch_blockers(
    node: &WorkspacePlanNodeRecord,
    nodes_by_id: &HashMap<String, WorkspacePlanNodeRecord>,
) -> (Vec<String>, Vec<String>) {
    let metadata = object_or_empty(node.metadata_json.clone());
    let repair_dependency = metadata_string(metadata.get("blocked_by_repair_node_id"));
    let mut dependency_ids = node.depends_on_json.clone();
    if let Some(repair_dependency) = repair_dependency.as_deref() {
        if !dependency_ids.iter().any(|id| id == repair_dependency) {
            dependency_ids.push(repair_dependency.to_string());
        }
    }
    dependency_ids.sort();
    dependency_ids.dedup();

    let mut blocking = Vec::new();
    let mut dirty_main_seed_dependencies = Vec::new();
    for dependency_id in dependency_ids {
        let Some(dependency) = nodes_by_id.get(&dependency_id) else {
            blocking.push(dependency_id);
            continue;
        };
        if dependency.intent != "done" {
            blocking.push(dependency_id);
            continue;
        }
        let dependency_metadata = object_or_empty(dependency.metadata_json.clone());
        if dependency_commit_needs_integration(dependency, &dependency_metadata) {
            if repair_dependency_can_seed_downstream_worktree(
                node,
                &dependency_id,
                repair_dependency.as_deref(),
                dependency,
                &dependency_metadata,
            ) {
                dirty_main_seed_dependencies.push(dependency_id);
                continue;
            }
            blocking.push(dependency_id);
        }
    }
    (blocking, dirty_main_seed_dependencies)
}

pub(super) fn repair_dependency_can_seed_downstream_worktree(
    node: &WorkspacePlanNodeRecord,
    dependency_id: &str,
    repair_dependency: Option<&str>,
    dependency: &WorkspacePlanNodeRecord,
    dependency_metadata: &Map<String, Value>,
) -> bool {
    if metadata_string(dependency_metadata.get("worktree_integration_status")).as_deref()
        != Some("blocked_dirty_main")
    {
        return false;
    }
    if dependency_dispatch_commit_ref(dependency).is_none() {
        return false;
    }
    repair_dependency.is_some_and(|repair_dependency| repair_dependency == dependency_id)
        || metadata_string(object_or_empty(node.metadata_json.clone()).get("repair_for_node_id"))
            .is_some()
        || node_is_iteration_artifact(node, "plan", "sprint_backlog")
        || node_is_iteration_artifact(node, "implement", "increment")
        || node_is_iteration_artifact(node, "test", "verification")
        || node_is_iteration_artifact(node, "review", "feedback")
        || node_is_iteration_artifact(node, "deploy", "release_candidate")
        || nodes_repair_same_original(node, dependency)
}

pub(super) fn node_is_iteration_artifact(
    node: &WorkspacePlanNodeRecord,
    phase: &str,
    artifact: &str,
) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
    metadata_string(metadata.get("iteration_phase")).as_deref() == Some(phase)
        && metadata_string(metadata.get("scrum_artifact")).as_deref() == Some(artifact)
}

pub(super) fn nodes_repair_same_original(
    node: &WorkspacePlanNodeRecord,
    dependency: &WorkspacePlanNodeRecord,
) -> bool {
    let node_metadata = object_or_empty(node.metadata_json.clone());
    let dependency_metadata = object_or_empty(dependency.metadata_json.clone());
    let Some(node_repair_for) = metadata_string(node_metadata.get("repair_for_node_id")) else {
        return false;
    };
    metadata_string(dependency_metadata.get("repair_for_node_id")).as_deref()
        == Some(node_repair_for.as_str())
}

pub(super) fn dependency_base_ref_for_dispatch(
    node: &WorkspacePlanNodeRecord,
    nodes_by_id: &HashMap<String, WorkspacePlanNodeRecord>,
) -> Option<String> {
    let mut candidates = Vec::new();
    for dependency_id in &node.depends_on_json {
        let Some(dependency) = nodes_by_id.get(dependency_id) else {
            continue;
        };
        if dependency.intent != "done" {
            continue;
        }
        let Some(commit_ref) = dependency_dispatch_commit_ref(dependency) else {
            continue;
        };
        let timestamp = dependency
            .completed_at
            .or(dependency.updated_at)
            .unwrap_or(dependency.created_at);
        candidates.push((timestamp, dependency_id.clone(), commit_ref));
    }
    candidates
        .into_iter()
        .max_by(|left, right| left.0.cmp(&right.0).then_with(|| left.1.cmp(&right.1)))
        .map(|(_, _, commit_ref)| commit_ref)
}

pub(super) fn dependency_dispatch_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let metadata = object_or_empty(node.metadata_json.clone());
    if metadata_string(metadata.get("worktree_integration_status")).as_deref()
        == Some("blocked_dirty_main")
    {
        if let Some(commit_ref) = metadata_string(metadata.get("verified_commit_ref")) {
            return Some(commit_ref);
        }
    }
    for key in [
        "source_publish_commit_ref",
        "worktree_integration_commit_ref",
        "verified_commit_ref",
    ] {
        if let Some(commit_ref) = metadata_string(metadata.get(key)) {
            return Some(commit_ref);
        }
    }
    feature_checkpoint_commit_ref(node)
}

pub(super) fn feature_checkpoint_with_base_ref(
    value: Option<Value>,
    base_ref: &str,
) -> Option<Value> {
    match value {
        Some(Value::Object(mut checkpoint)) => {
            checkpoint.insert("base_ref".to_string(), json!(base_ref));
            Some(Value::Object(checkpoint))
        }
        other => other,
    }
}

pub(super) fn node_disposition_satisfies_dependency_without_integration(
    metadata: &Map<String, Value>,
) -> bool {
    metadata_string(metadata.get("verification_feedback_disposition")).as_deref()
        == Some("supervisor_agent_disposed_node")
        && metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
            == Some("dispose_node")
        && metadata_string(metadata.get("last_verification_judge_next_action_kind")).as_deref()
            != Some("retry_same_node")
}

pub(super) fn node_verified_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let metadata = object_or_empty(node.metadata_json.clone());
    metadata
        .get("verified_commit_ref")
        .and_then(Value::as_str)
        .and_then(commit_ref_token)
        .or_else(|| {
            metadata
                .get("worktree_integration_commit_ref")
                .and_then(Value::as_str)
                .and_then(commit_ref_token)
        })
        .or_else(|| feature_checkpoint_commit_ref(node))
}

pub(super) fn node_attempt_worktree_path(
    node: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
) -> Option<String> {
    metadata_string(metadata.get("worktree_integration_worktree_path"))
        .or_else(|| metadata_string(metadata.get("active_execution_root")))
        .or_else(|| metadata_string(metadata.get("worktree_path")))
        .or_else(|| {
            metadata_string_from_path(
                node.feature_checkpoint_json
                    .as_ref()
                    .unwrap_or(&Value::Null),
                &["worktree_path"],
            )
        })
}

pub(super) fn looks_like_attempt_worktree(path: &str) -> bool {
    path.contains("/.memstack/worktrees/")
}

pub(super) fn clear_failed_worktree_retry_stale_attempt_metadata(
    mut metadata: Map<String, Value>,
) -> Map<String, Value> {
    for key in FAILED_WORKTREE_RETRY_STALE_METADATA_KEYS {
        metadata.remove(*key);
    }
    metadata
}

pub(super) fn apply_verification_checkpoint_metadata(
    metadata: &mut Map<String, Value>,
    summary: &str,
    commit_ref: Option<&str>,
    git_diff_summary: Option<&str>,
    test_commands: &[String],
    created_at: DateTime<Utc>,
) {
    if commit_ref.is_none() && git_diff_summary.is_none() && test_commands.is_empty() {
        return;
    }
    if let Some(commit_ref) = commit_ref {
        if let Some(Value::Object(feature_checkpoint)) = metadata.get_mut("feature_checkpoint") {
            feature_checkpoint.insert("commit_ref".to_string(), json!(commit_ref));
        }
    }
    let handoff = metadata
        .entry("handoff_package".to_string())
        .or_insert_with(|| {
            json!({
                "reason": "planned",
                "summary": "Accepted by durable plan verifier.",
                "next_steps": [],
                "completed_steps": [],
                "changed_files": [],
                "git_head": Value::Null,
                "git_diff_summary": "",
                "test_commands": [],
                "verification_notes": "",
                "created_at": created_at.to_rfc3339()
            })
        });
    if !handoff.is_object() {
        *handoff = json!({
            "reason": "planned",
            "summary": "Accepted by durable plan verifier.",
            "next_steps": [],
            "completed_steps": [],
            "changed_files": [],
            "git_head": Value::Null,
            "git_diff_summary": "",
            "test_commands": [],
            "verification_notes": "",
            "created_at": created_at.to_rfc3339()
        });
    }
    if let Value::Object(handoff) = handoff {
        if let Some(commit_ref) = commit_ref {
            handoff.insert("git_head".to_string(), json!(commit_ref));
        }
        if let Some(git_diff_summary) = git_diff_summary {
            handoff.insert("git_diff_summary".to_string(), json!(git_diff_summary));
        }
        if !test_commands.is_empty() {
            handoff.insert("test_commands".to_string(), json!(test_commands));
        }
        handoff.insert("verification_notes".to_string(), json!(summary));
    }
}

pub(super) fn accepted_attempt_integration_commit_ref(
    node: &WorkspacePlanNodeRecord,
) -> Option<String> {
    feature_checkpoint_commit_ref(node).or_else(|| node_expected_commit_ref(node))
}

pub(super) fn feature_checkpoint_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    if let Some(Value::Object(checkpoint)) = &node.feature_checkpoint_json {
        return checkpoint
            .get("commit_ref")
            .and_then(Value::as_str)
            .and_then(commit_ref_token);
    }
    None
}

pub(super) fn worktree_integration_metadata(
    status: &str,
    summary: &str,
    attempt_id: &str,
    commit_ref: Option<&str>,
    worktree_path: Option<&str>,
    now: DateTime<Utc>,
    dirty_signature: Option<&str>,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("worktree_integration_status".to_string(), json!(status));
    metadata.insert("worktree_integration_summary".to_string(), json!(summary));
    metadata.insert(
        "worktree_integration_attempt_id".to_string(),
        json!(attempt_id),
    );
    metadata.insert(
        "worktree_integration_ran_at".to_string(),
        json!(now.to_rfc3339()),
    );
    if let Some(commit_ref) = commit_ref {
        metadata.insert(
            "worktree_integration_commit_ref".to_string(),
            json!(commit_ref),
        );
    }
    if let Some(worktree_path) = worktree_path {
        metadata.insert(
            "worktree_integration_worktree_path".to_string(),
            json!(worktree_path),
        );
    }
    metadata.insert(
        "worktree_integration_dirty_signature".to_string(),
        dirty_signature.map_or(Value::Null, |value| json!(value)),
    );
    metadata
}

pub(super) fn worktree_integration_event_type(status: &str) -> &'static str {
    match status {
        "merged" => "accepted_worktree_integrated",
        "already_merged" | "skipped" => "accepted_worktree_integration_skipped",
        "blocked_dirty_main" => "accepted_worktree_integration_blocked",
        "failed" => "accepted_worktree_integration_failed",
        _ => "accepted_worktree_integration_failed",
    }
}

pub(super) fn sandbox_code_root_for_integration(
    task_metadata: &Value,
    workspace_metadata: &Value,
) -> Option<String> {
    metadata_string_from_path(task_metadata, &["sandbox_code_root"])
        .or_else(|| {
            metadata_string_from_path(task_metadata, &["code_context", "sandbox_code_root"])
        })
        .or_else(|| metadata_string_from_path(workspace_metadata, &["sandbox_code_root"]))
        .or_else(|| {
            metadata_string_from_path(workspace_metadata, &["code_context", "sandbox_code_root"])
        })
}

pub(super) fn accepted_attempt_worktree_path(
    node: &WorkspacePlanNodeRecord,
    task_metadata: &Value,
    sandbox_code_root: &str,
    attempt_id: &str,
) -> Option<String> {
    let raw_path = metadata_string_from_path(
        node.feature_checkpoint_json
            .as_ref()
            .unwrap_or(&Value::Null),
        &["worktree_path"],
    )
    .or_else(|| metadata_string_from_path(task_metadata, &["feature_checkpoint", "worktree_path"]))
    .unwrap_or_else(|| default_attempt_worktree_path(sandbox_code_root, attempt_id));
    let path = raw_path.replace("${sandbox_code_root}", sandbox_code_root);
    if path.contains("${sandbox_code_root}") {
        return None;
    }
    Some(normalize_posix_path(&path))
}

pub(super) fn apply_attempt_worktree_checkpoint(
    node: &mut WorkspacePlanNodeRecord,
    attempt_id: &str,
) {
    let Some(Value::Object(mut checkpoint)) = node.feature_checkpoint_json.clone() else {
        return;
    };
    let base_ref = attempt_retry_base_ref(node)
        .or_else(|| {
            checkpoint
                .get("commit_ref")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
        })
        .or_else(|| {
            checkpoint
                .get("base_ref")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
        })
        .unwrap_or_else(|| "HEAD".to_string());
    checkpoint.insert(
        "worktree_path".to_string(),
        json!(format!(
            "${{sandbox_code_root}}/../.memstack/worktrees/{attempt_id}"
        )),
    );
    checkpoint.insert(
        "branch_name".to_string(),
        json!(worktree_branch_name(&node.id, attempt_id)),
    );
    checkpoint.insert("base_ref".to_string(), json!(base_ref));
    node.feature_checkpoint_json = Some(Value::Object(checkpoint));
}

pub(super) fn attempt_retry_base_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let metadata = object_or_empty(node.metadata_json.clone());
    for key in [
        "source_publish_commit_ref",
        "source_publish_source_commit_ref",
        "worktree_integration_commit_ref",
        "verified_commit_ref",
        "dirty_main_dependency_base_ref",
    ] {
        if let Some(value) = metadata_string(metadata.get(key)) {
            return Some(value);
        }
    }
    None
}

pub(super) fn worktree_branch_name(node_id: &str, attempt_id: &str) -> String {
    let node_token = safe_git_token(node_id).chars().take(48).collect::<String>();
    let attempt_token = safe_git_token(attempt_id)
        .chars()
        .take(12)
        .collect::<String>();
    format!("workspace/{node_token}-{attempt_token}")
}

pub(super) fn safe_git_token(value: &str) -> String {
    let token = value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-') {
                ch
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches(&['.', '/', '-'][..])
        .to_string();
    if token.is_empty() {
        "node".to_string()
    } else {
        token
    }
}

pub(super) fn default_attempt_worktree_path(sandbox_code_root: &str, attempt_id: &str) -> String {
    normalize_posix_path(&format!(
        "{}/../.memstack/worktrees/{}",
        sandbox_code_root.trim_end_matches('/'),
        attempt_id
    ))
}

pub(super) fn normalize_posix_path(value: &str) -> String {
    let absolute = value.starts_with('/');
    let mut parts = Vec::new();
    for part in value.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                if !parts.is_empty() {
                    parts.pop();
                } else if !absolute {
                    parts.push("..");
                }
            }
            other => parts.push(other),
        }
    }
    let mut normalized = parts.join("/");
    if absolute {
        normalized.insert(0, '/');
    }
    if normalized.is_empty() {
        if absolute {
            "/".to_string()
        } else {
            ".".to_string()
        }
    } else {
        normalized
    }
}

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

pub(super) fn terminal_attempt_pending_pipeline_verification(
    node: &WorkspacePlanNodeRecord,
    status: &str,
) -> bool {
    if node_waiting_for_verification_retry(node) {
        return true;
    }
    if node_has_pipeline_gate_in_flight(node, status) {
        return true;
    }
    if node.execution != "reported" || status == "accepted" {
        return false;
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    let pipeline_status = metadata_string(metadata.get("pipeline_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !matches!(
        pipeline_status.as_str(),
        "failed" | "failure" | "error" | "success"
    ) {
        return false;
    }
    metadata_string(metadata.get("pipeline_run_id")).is_some()
        || metadata_string(metadata.get("external_id")).is_some()
}

pub(super) fn node_waiting_for_verification_retry(node: &WorkspacePlanNodeRecord) -> bool {
    node.execution == "reported"
        && object_or_empty(node.metadata_json.clone())
            .get("retry_verification_only")
            .and_then(Value::as_bool)
            == Some(true)
}

pub(super) fn node_has_pipeline_gate_in_flight(
    node: &WorkspacePlanNodeRecord,
    status: &str,
) -> bool {
    if status == "accepted" || node.intent != "in_progress" {
        return false;
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    let pipeline_status = metadata_string(metadata.get("pipeline_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    let gate_status = metadata_string(metadata.get("pipeline_gate_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    matches!(
        pipeline_status.as_str(),
        "requested" | "running" | "processing"
    ) || matches!(gate_status.as_str(), "requested" | "running" | "processing")
}

pub(super) fn metadata_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

pub(super) fn copy_retry_context_payload_fields(
    source: &Map<String, Value>,
    target: &mut Map<String, Value>,
) {
    for key in [
        "previous_attempt_id",
        "retry_attempt_id",
        "retry_reason",
        "retry_origin",
        "worker_stream_orphan_retry_reason",
        "worker_stream_orphan_summary",
    ] {
        if let Some(value) = source.get(key).filter(|value| !value.is_null()) {
            target.insert(key.to_string(), value.clone());
        }
    }
}

pub(super) fn should_reset_attempt_retry_worker_state(
    event_type: &str,
    payload: &Map<String, Value>,
) -> bool {
    event_type == ATTEMPT_RETRY_EVENT
        && (string_from_map(payload, "retry_reason").is_some()
            || string_from_map(payload, "previous_attempt_id").is_some()
            || string_from_map(payload, "retry_attempt_id").is_some()
            || metadata_string(payload.get("retry_origin")).is_some()
            || metadata_string(payload.get("worker_stream_orphan_retry_reason")).is_some()
            || metadata_string(payload.get("worker_stream_orphan_summary")).is_some())
}

pub(super) fn clear_attempt_retry_worker_stream_state(metadata: &mut Map<String, Value>) {
    for key in ATTEMPT_RETRY_STALE_WORKER_STREAM_METADATA_KEYS {
        metadata.remove(*key);
    }
}

pub(super) fn worker_stream_replay_metadata_matches_attempt(
    metadata: &Map<String, Value>,
    attempt_id: &str,
) -> bool {
    string_from_map(metadata, "worker_stream_replay_attempt_id")
        .or_else(|| string_from_map(metadata, LAST_WORKER_REPORT_ATTEMPT_ID))
        .as_deref()
        .is_none_or(|recorded_attempt_id| recorded_attempt_id == attempt_id)
}

pub(super) fn copy_metadata_string_field(
    source: &Map<String, Value>,
    target: &mut Map<String, Value>,
    key: &str,
) {
    if let Some(value) = metadata_string(source.get(key)) {
        target.insert(key.to_string(), json!(value));
    }
}

pub(super) fn apply_attempt_retry_context(
    metadata: &mut Map<String, Value>,
    payload: &Map<String, Value>,
    now: DateTime<Utc>,
) {
    let mut has_retry_context = false;
    if let Some(retry_reason) = string_from_map(payload, "retry_reason") {
        metadata.insert("last_retry_reason".to_string(), json!(retry_reason));
        has_retry_context = true;
    }
    if let Some(previous_attempt_id) = string_from_map(payload, "previous_attempt_id")
        .or_else(|| string_from_map(payload, "retry_attempt_id"))
    {
        metadata.insert(
            "last_retry_previous_attempt_id".to_string(),
            json!(previous_attempt_id),
        );
        has_retry_context = true;
    }
    for key in [
        "retry_origin",
        "worker_stream_orphan_retry_reason",
        "worker_stream_orphan_summary",
    ] {
        if let Some(value) = metadata_string(payload.get(key)) {
            metadata.insert(key.to_string(), json!(value));
            has_retry_context = true;
        }
    }
    if has_retry_context {
        metadata.insert("last_retry_context_at".to_string(), json!(now.to_rfc3339()));
    }
}

pub(super) fn release_node_for_terminal_retry(
    node: &mut WorkspacePlanNodeRecord,
    reason: &str,
    now: DateTime<Utc>,
    max_retries: i64,
) -> bool {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    let retry_count = metadata
        .get("terminal_attempt_retry_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "terminal_attempt_retry_count".to_string(),
        json!(retry_count),
    );
    metadata.insert("terminal_attempt_retry_reason".to_string(), json!(reason));
    metadata.insert(
        "terminal_attempt_reconciled_at".to_string(),
        json!(now.to_rfc3339()),
    );
    metadata.remove("retry_not_before");

    let retry_exhausted = retry_count > max_retries;
    node.intent = if retry_exhausted {
        "blocked".to_string()
    } else {
        "todo".to_string()
    };
    node.execution = "idle".to_string();
    node.current_attempt_id = None;
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
    retry_exhausted
}

pub(super) fn plan_terminal_attempt_max_retries() -> i64 {
    positive_i64_env(
        PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV,
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES,
    )
}

#[allow(clippy::too_many_arguments)]
pub(super) fn worker_report_supervisor_tick(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    attempt_id: &str,
    root_goal_task_id: &str,
    actor_user_id: &str,
    leader_agent_id: Option<&str>,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: SUPERVISOR_TICK_EVENT.to_string(),
        payload_json: json!({
            "workspace_id": workspace_id,
            "root_task_id": root_goal_task_id,
            "actor_user_id": actor_user_id,
            "leader_agent_id": leader_agent_id,
            "plan_id": plan_id,
            "node_id": node_id,
            "attempt_id": attempt_id
        }),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 3,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "worker_report",
            "node_id": node_id,
            "attempt_id": attempt_id
        }),
        created_at: now,
        updated_at: None,
    }
}

pub(super) fn supervisor_replan_tick_outbox(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    task_id: Option<&str>,
    worker_agent_id: Option<&str>,
    reason: &str,
    previous_attempt_id: Option<&str>,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut payload = Map::new();
    payload.insert("workspace_id".to_string(), json!(workspace_id));
    payload.insert("plan_id".to_string(), json!(plan_id));
    payload.insert("node_id".to_string(), json!(node_id));
    payload.insert(
        "actor_user_id".to_string(),
        json!(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
    );
    payload.insert(
        "operator_action".to_string(),
        json!("operator_replan_requested"),
    );
    payload.insert(
        "supervisor_action".to_string(),
        json!(SUPERVISOR_DECISION_REPLAN_NODE_ACTION),
    );
    payload.insert(
        "retry_reason".to_string(),
        json!(SUPERVISOR_DECISION_REPLAN_NODE_REASON),
    );
    payload.insert("reason".to_string(), json!(reason));
    if let Some(task_id) = task_id {
        payload.insert("task_id".to_string(), json!(task_id));
    }
    if let Some(worker_agent_id) = worker_agent_id {
        payload.insert("worker_agent_id".to_string(), json!(worker_agent_id));
    }
    if let Some(previous_attempt_id) = previous_attempt_id {
        payload.insert(
            "previous_attempt_id".to_string(),
            json!(previous_attempt_id),
        );
        payload.insert("retry_attempt_id".to_string(), json!(previous_attempt_id));
    }

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: SUPERVISOR_TICK_EVENT.to_string(),
        payload_json: Value::Object(payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "workspace_plan.supervisor_decision_replan",
            "node_id": node_id,
            "previous_attempt_id": previous_attempt_id
        }),
        created_at: now,
        updated_at: None,
    }
}

pub(super) fn supervisor_request_pipeline_outbox(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    attempt_id: Option<&str>,
    reason: &str,
    metadata: &Map<String, Value>,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut payload = Map::new();
    payload.insert("workspace_id".to_string(), json!(workspace_id));
    payload.insert("plan_id".to_string(), json!(plan_id));
    payload.insert("node_id".to_string(), json!(node_id));
    payload.insert(
        "reason".to_string(),
        json!(SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON),
    );
    payload.insert("summary".to_string(), json!(reason));
    if let Some(attempt_id) = attempt_id {
        payload.insert("attempt_id".to_string(), json!(attempt_id));
    }

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: PIPELINE_RUN_REQUESTED_EVENT.to_string(),
        payload_json: Value::Object(payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "workspace_plan.supervisor_decision_request_pipeline",
            "node_id": node_id,
            "attempt_id": attempt_id,
            "supervisor_action": SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION,
            "confidence": metadata.get("last_supervisor_decision_confidence").cloned().unwrap_or(Value::Null),
            "feedback_items": metadata.get("last_supervisor_decision_feedback_items").cloned().unwrap_or(Value::Null),
        }),
        created_at,
        updated_at: None,
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn supervisor_retry_attempt_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    task_id: &str,
    worker_agent_id: &str,
    actor_user_id: &str,
    leader_agent_id: &str,
    root_goal_task_id: Option<&str>,
    retry_attempt_id: Option<&str>,
    retry_reason: &str,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut retry_payload = Map::new();
    retry_payload.insert("workspace_id".to_string(), json!(workspace_id));
    retry_payload.insert("plan_id".to_string(), json!(plan_id));
    retry_payload.insert("node_id".to_string(), json!(node_id));
    retry_payload.insert("task_id".to_string(), json!(task_id));
    retry_payload.insert("worker_agent_id".to_string(), json!(worker_agent_id));
    retry_payload.insert("actor_user_id".to_string(), json!(actor_user_id));
    retry_payload.insert("leader_agent_id".to_string(), json!(leader_agent_id));
    retry_payload.insert("retry_reason".to_string(), json!(retry_reason));
    if let Some(root_goal_task_id) = root_goal_task_id {
        retry_payload.insert(ROOT_GOAL_TASK_ID.to_string(), json!(root_goal_task_id));
    }
    if let Some(retry_attempt_id) = retry_attempt_id {
        retry_payload.insert("previous_attempt_id".to_string(), json!(retry_attempt_id));
        retry_payload.insert("retry_attempt_id".to_string(), json!(retry_attempt_id));
    }
    for optional_key in [
        "extra_instructions",
        "force_schedule",
        "repair_brief_prompt",
        "reuse_conversation_id",
    ] {
        if let Some(value) = payload.get(optional_key) {
            retry_payload.insert(optional_key.to_string(), value.clone());
        }
    }
    copy_retry_context_payload_fields(payload, &mut retry_payload);

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: ATTEMPT_RETRY_EVENT.to_string(),
        payload_json: Value::Object(retry_payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: item.max_attempts,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "workspace_plan.supervisor_tick.retry_admission",
            "previous_outbox_id": item.id,
            "retry_node_id": node_id,
            "retry_attempt_id": retry_attempt_id,
            "retry_reason": retry_reason
        }),
        created_at,
        updated_at: None,
    }
}
