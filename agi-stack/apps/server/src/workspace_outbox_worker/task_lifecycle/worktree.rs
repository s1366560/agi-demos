use super::*;

pub(in crate::workspace_outbox_worker) fn accepted_attempt_integration_commit_ref(
    node: &WorkspacePlanNodeRecord,
) -> Option<String> {
    feature_checkpoint_commit_ref(node).or_else(|| node_expected_commit_ref(node))
}

pub(in crate::workspace_outbox_worker) fn feature_checkpoint_commit_ref(
    node: &WorkspacePlanNodeRecord,
) -> Option<String> {
    if let Some(Value::Object(checkpoint)) = &node.feature_checkpoint_json {
        return checkpoint
            .get("commit_ref")
            .and_then(Value::as_str)
            .and_then(commit_ref_token);
    }
    None
}

pub(in crate::workspace_outbox_worker) fn worktree_integration_metadata(
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

pub(in crate::workspace_outbox_worker) fn worktree_integration_event_type(
    status: &str,
) -> &'static str {
    match status {
        "merged" => "accepted_worktree_integrated",
        "already_merged" | "skipped" => "accepted_worktree_integration_skipped",
        "blocked_dirty_main" => "accepted_worktree_integration_blocked",
        "failed" => "accepted_worktree_integration_failed",
        _ => "accepted_worktree_integration_failed",
    }
}

pub(in crate::workspace_outbox_worker) fn sandbox_code_root_for_integration(
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

pub(in crate::workspace_outbox_worker) fn accepted_attempt_worktree_path(
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

pub(in crate::workspace_outbox_worker) fn apply_attempt_worktree_checkpoint(
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

fn attempt_retry_base_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let metadata = object_as_map(&node.metadata_json);
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

pub(in crate::workspace_outbox_worker) fn worktree_branch_name(
    node_id: &str,
    attempt_id: &str,
) -> String {
    let node_token = safe_git_token(node_id).chars().take(48).collect::<String>();
    let attempt_token = safe_git_token(attempt_id)
        .chars()
        .take(12)
        .collect::<String>();
    format!("workspace/{node_token}-{attempt_token}")
}

fn safe_git_token(value: &str) -> String {
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

pub(in crate::workspace_outbox_worker) fn default_attempt_worktree_path(
    sandbox_code_root: &str,
    attempt_id: &str,
) -> String {
    normalize_posix_path(&format!(
        "{}/../.memstack/worktrees/{}",
        sandbox_code_root.trim_end_matches('/'),
        attempt_id
    ))
}

pub(in crate::workspace_outbox_worker) fn normalize_posix_path(value: &str) -> String {
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
