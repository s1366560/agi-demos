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
