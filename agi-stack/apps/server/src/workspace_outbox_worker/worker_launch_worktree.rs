use super::*;

#[derive(Debug, Clone)]
pub(super) struct WorkerLaunchWorktreeContext {
    pub(super) metadata_patch: Map<String, Value>,
    pub(super) setup_failed: bool,
    pub(super) setup_reason: Option<String>,
}

pub(super) async fn worker_launch_worktree_context(
    workspace: Option<&WorkspaceRecord>,
    task: &WorkspaceTaskRecord,
    node: Option<&WorkspacePlanNodeRecord>,
    attempt_id: Option<&str>,
) -> CoreResult<Option<WorkerLaunchWorktreeContext>> {
    let feature = node
        .and_then(|node| node.feature_checkpoint_json.as_ref())
        .filter(|value| value.is_object())
        .or_else(|| {
            task.metadata_json
                .get("feature_checkpoint")
                .filter(|value| value.is_object())
        });
    if feature.is_none() && attempt_id.is_none() {
        return Ok(None);
    }

    let task_metadata = task.metadata_json.clone();
    let workspace_metadata = workspace
        .map(|workspace| workspace.metadata_json.clone())
        .unwrap_or(Value::Null);
    let base_ref = feature
        .and_then(|value| metadata_string_from_path(value, &["base_ref"]))
        .or_else(|| feature.and_then(|value| metadata_string_from_path(value, &["commit_ref"])))
        .unwrap_or_else(|| "HEAD".to_string());
    let sandbox_code_root = sandbox_code_root_for_integration(&task_metadata, &workspace_metadata);
    let Some(sandbox_code_root) = sandbox_code_root else {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some("sandbox_code_root is not available for this workspace"),
                workspace_root: None,
                sandbox_code_root: None,
                active_root: None,
                worktree_path: None,
                branch_name: None,
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    };

    let worktree_path_template =
        feature.and_then(|value| metadata_string_from_path(value, &["worktree_path"]));
    let branch_name = feature
        .and_then(|value| metadata_string_from_path(value, &["branch_name"]))
        .or_else(|| {
            let attempt_id = attempt_id?;
            let node_id = node
                .map(|node| node.id.as_str())
                .unwrap_or(task.id.as_str());
            Some(worktree_branch_name(node_id, attempt_id))
        });

    if (worktree_path_template.is_none() || branch_name.is_none()) && attempt_id.is_none() {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some(
                    "feature checkpoint does not include worktree_path and branch_name",
                ),
                workspace_root: None,
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: None,
                branch_name: branch_name.as_deref(),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let worktree_path = match (worktree_path_template, attempt_id) {
        (Some(template), _) => template.replace("${sandbox_code_root}", &sandbox_code_root),
        (None, Some(attempt_id)) => default_attempt_worktree_path(&sandbox_code_root, attempt_id),
        (None, None) => String::new(),
    };
    let branch_name = branch_name.unwrap_or_else(|| {
        worktree_branch_name(
            node.map(|node| node.id.as_str())
                .unwrap_or(task.id.as_str()),
            attempt_id.unwrap_or("attempt"),
        )
    });

    if worktree_path.contains("${sandbox_code_root}") {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some(
                    "worktree_path still contains an unresolved sandbox_code_root placeholder",
                ),
                workspace_root: None,
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let worktree_path = normalize_posix_path(&worktree_path);
    if let Some(reason) = worker_launch_worktree_path_failure(&sandbox_code_root, &worktree_path) {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "failed",
                setup_reason: Some(&reason),
                workspace_root: workspace_root_for_code_root(&sandbox_code_root).as_deref(),
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: Some(&base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let code_root = Path::new(&sandbox_code_root);
    if !code_root.exists() {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some("sandbox_code_root is not a local path on the Rust worker host"),
                workspace_root: workspace_root_for_code_root(&sandbox_code_root).as_deref(),
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: Some(&base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    Ok(Some(
        prepare_worker_launch_worktree_with_git(
            code_root,
            Path::new(&worktree_path),
            &branch_name,
            &base_ref,
            attempt_id,
        )
        .await?,
    ))
}

struct WorktreeContextInput<'a> {
    setup_status: &'a str,
    setup_reason: Option<&'a str>,
    workspace_root: Option<&'a str>,
    sandbox_code_root: Option<&'a str>,
    active_root: Option<&'a str>,
    worktree_path: Option<&'a str>,
    branch_name: Option<&'a str>,
    base_ref: Option<&'a str>,
    attempt_id: Option<&'a str>,
    setup_output: Option<&'a str>,
    original_base_ref: Option<&'a str>,
    resolved_base_ref: Option<&'a str>,
    fallback_reason: Option<&'a str>,
    git_fsck_summary: Option<&'a str>,
    pruned_worktrees_count: Option<i64>,
}

fn worker_launch_worktree_context_value(
    input: WorktreeContextInput<'_>,
) -> WorkerLaunchWorktreeContext {
    let active_root = input.active_root.map(ToOwned::to_owned);
    let is_isolated = active_root.is_some();
    let attempt_worktree = json!({
        "workspace_root": input.workspace_root,
        "sandbox_code_root": input.sandbox_code_root,
        "active_root": active_root,
        "worktree_path": input.worktree_path,
        "branch_name": input.branch_name,
        "base_ref": input.base_ref,
        "attempt_id": input.attempt_id,
        "is_isolated": is_isolated,
        "setup_status": input.setup_status,
        "setup_reason": input.setup_reason,
        "setup_output": input.setup_output,
        "original_base_ref": input.original_base_ref,
        "resolved_base_ref": input.resolved_base_ref,
        "fallback_reason": input.fallback_reason,
        "git_fsck_summary": input.git_fsck_summary,
        "pruned_worktrees_count": input.pruned_worktrees_count
    });
    let setup = json!({
        "status": input.setup_status,
        "reason": input.setup_reason,
        "output": input.setup_output,
        "worktree_path": input.worktree_path,
        "branch_name": input.branch_name,
        "base_ref": input.base_ref,
        "attempt_id": input.attempt_id,
        "original_base_ref": input.original_base_ref,
        "resolved_base_ref": input.resolved_base_ref,
        "fallback_reason": input.fallback_reason,
        "git_fsck_summary": input.git_fsck_summary,
        "pruned_worktrees_count": input.pruned_worktrees_count
    });
    let mut metadata_patch = Map::new();
    metadata_patch.insert("attempt_worktree".to_string(), attempt_worktree);
    metadata_patch.insert("worktree_setup".to_string(), setup);
    if let Some(active_root) = input.active_root {
        metadata_patch.insert("active_execution_root".to_string(), json!(active_root));
    }
    WorkerLaunchWorktreeContext {
        metadata_patch,
        setup_failed: input.setup_status == "failed",
        setup_reason: input.setup_reason.map(ToOwned::to_owned),
    }
}

async fn prepare_worker_launch_worktree_with_git(
    sandbox_code_root: &Path,
    worktree_path: &Path,
    branch_name: &str,
    base_ref: &str,
    attempt_id: Option<&str>,
) -> CoreResult<WorkerLaunchWorktreeContext> {
    let env: Vec<(String, String)> = Vec::new();
    let sandbox_code_root_text = sandbox_code_root.to_string_lossy().to_string();
    let worktree_path_text = worktree_path.to_string_lossy().to_string();
    let workspace_root = workspace_root_for_code_root(&sandbox_code_root.to_string_lossy());
    let git_root = run_git_command(
        sandbox_code_root,
        &["rev-parse", "--show-toplevel"],
        &env,
        30,
    )
    .await?;
    if git_root.exit_code != 0 {
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "skipped",
            setup_reason: Some("sandbox_code_root is not a git checkout"),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: None,
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some(&compact_git_error(&git_root)),
            original_base_ref: Some(base_ref),
            resolved_base_ref: None,
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }

    if worktree_path.exists() {
        let existing = run_git_command(
            worktree_path,
            &["rev-parse", "--is-inside-work-tree"],
            &env,
            30,
        )
        .await?;
        if existing.exit_code != 0 {
            let reason = format!(
                "worktree_path exists but is not a git worktree: {}",
                worktree_path.display()
            );
            return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
                setup_status: "failed",
                setup_reason: Some(&reason),
                workspace_root: workspace_root.as_deref(),
                sandbox_code_root: Some(&sandbox_code_root_text),
                active_root: None,
                worktree_path: Some(&worktree_path_text),
                branch_name: Some(branch_name),
                base_ref: Some(base_ref),
                attempt_id,
                setup_output: Some(&compact_git_error(&existing)),
                original_base_ref: Some(base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            }));
        }
        let head = short_git_head(worktree_path, &env).await?;
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "prepared",
            setup_reason: Some("attempt worktree already exists"),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: Some(&worktree_path_text),
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some("existing git worktree reused"),
            original_base_ref: Some(base_ref),
            resolved_base_ref: Some(&head),
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }

    if let Some(parent) = worktree_path.parent() {
        tokio::fs::create_dir_all(parent).await.map_err(|err| {
            CoreError::Storage(format!(
                "create attempt worktree parent {}: {err}",
                parent.display()
            ))
        })?;
    }
    let _ = run_git_command(sandbox_code_root, &["worktree", "prune"], &env, 60).await?;
    let worktree_arg = worktree_path.to_string_lossy().to_string();
    let add = run_git_command(
        sandbox_code_root,
        &[
            "worktree",
            "add",
            "-B",
            branch_name,
            &worktree_arg,
            base_ref,
        ],
        &env,
        120,
    )
    .await?;
    if add.exit_code != 0 {
        let reason = compact_git_error(&add);
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "failed",
            setup_reason: Some(&reason),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: None,
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some(&compact_text(&add.stdout, 1200)),
            original_base_ref: Some(base_ref),
            resolved_base_ref: None,
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }
    let head = short_git_head(worktree_path, &env).await?;
    Ok(worker_launch_worktree_context_value(WorktreeContextInput {
        setup_status: "prepared",
        setup_reason: None,
        workspace_root: workspace_root.as_deref(),
        sandbox_code_root: Some(&sandbox_code_root_text),
        active_root: Some(&worktree_path_text),
        worktree_path: Some(&worktree_path_text),
        branch_name: Some(branch_name),
        base_ref: Some(base_ref),
        attempt_id,
        setup_output: Some(&compact_text(&add.stdout, 1200)),
        original_base_ref: Some(base_ref),
        resolved_base_ref: Some(&head),
        fallback_reason: None,
        git_fsck_summary: None,
        pruned_worktrees_count: None,
    }))
}

fn worker_launch_worktree_path_failure(
    sandbox_code_root: &str,
    worktree_path: &str,
) -> Option<String> {
    let code_root = normalize_posix_path(sandbox_code_root);
    let worktree_path = normalize_posix_path(worktree_path);
    if !worktree_path.starts_with('/') {
        return Some(format!("worktree_path is not absolute: {worktree_path}"));
    }
    if worktree_path == code_root || worktree_path.starts_with(&format!("{code_root}/")) {
        return Some(format!(
            "workspace run contract rejected worker launch path: worktree_path must not be inside sandbox_code_root; code_root={code_root}; worktree_path={worktree_path}"
        ));
    }
    None
}

fn workspace_root_for_code_root(sandbox_code_root: &str) -> Option<String> {
    let normalized = normalize_posix_path(sandbox_code_root);
    normalized
        .rsplit_once('/')
        .map(|(parent, _)| if parent.is_empty() { "/" } else { parent })
        .map(ToOwned::to_owned)
}
