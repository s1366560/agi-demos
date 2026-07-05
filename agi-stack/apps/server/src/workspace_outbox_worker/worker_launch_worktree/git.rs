use super::*;

pub(super) async fn prepare_worker_launch_worktree_with_git(
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
