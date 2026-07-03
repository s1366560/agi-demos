use super::commands::{
    compact_git_error, git_blob_hash, is_unrelated_history_merge_rejection, run_git_command,
    short_git_head,
};
use super::*;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(in crate::workspace_outbox_worker) struct AcceptedWorktreeIntegrationResult {
    pub(in crate::workspace_outbox_worker) status: String,
    pub(in crate::workspace_outbox_worker) summary: String,
    pub(in crate::workspace_outbox_worker) commit_ref: String,
    pub(in crate::workspace_outbox_worker) dirty_signature: Option<String>,
}

pub(in crate::workspace_outbox_worker) async fn integrate_accepted_attempt_worktree_with_git(
    sandbox_code_root: &Path,
    worktree_path: &Path,
    commit_ref: &str,
) -> CoreResult<AcceptedWorktreeIntegrationResult> {
    let env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    if !sandbox_code_root.exists() {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: format!(
                "sandbox_code_root does not exist: {}",
                sandbox_code_root.display()
            ),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    }
    if !worktree_path.exists() {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: format!(
                "accepted worktree does not exist: {}",
                worktree_path.display()
            ),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    }

    let resolved_commit = resolve_accepted_worktree_commit(worktree_path, commit_ref, &env).await?;
    let Some(resolved_commit) = resolved_commit else {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: "status=failed\nreason=commit_ref not found in attempt worktree".to_string(),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    };

    let already_merged = run_git_command(
        sandbox_code_root,
        &["merge-base", "--is-ancestor", &resolved_commit, "HEAD"],
        &env,
        60,
    )
    .await?;
    if already_merged.exit_code == 0 {
        let git_head = short_git_head(sandbox_code_root, &env).await?;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "already_merged".to_string(),
            summary: format!(
                "resolved_commit_ref={resolved_commit}\nstatus=already_merged\ngit_head={git_head}"
            ),
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }

    let dirty = run_git_command(sandbox_code_root, &["status", "--porcelain"], &env, 60).await?;
    if dirty.exit_code != 0 {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: compact_git_error(&dirty),
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }
    if !dirty.stdout.trim().is_empty() {
        let signature = git_blob_hash(sandbox_code_root, &dirty.stdout, &env).await?;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "blocked_dirty_main".to_string(),
            summary: compact_text(
                &format!(
                    "status=blocked_dirty_main\nreason=sandbox_code_root has uncommitted changes\ndirty_signature={}\n{}",
                    signature,
                    dirty.stdout.trim()
                ),
                1200,
            ),
            commit_ref: resolved_commit,
            dirty_signature: Some(signature),
        });
    }

    let merge = run_git_command(
        sandbox_code_root,
        &["merge", "--no-edit", &resolved_commit],
        &env,
        120,
    )
    .await?;
    let merge = if merge.exit_code != 0 && is_unrelated_history_merge_rejection(&merge) {
        let _ = run_git_command(sandbox_code_root, &["merge", "--abort"], &env, 60).await;
        run_git_command(
            sandbox_code_root,
            &[
                "merge",
                "--no-edit",
                "--allow-unrelated-histories",
                "-X",
                "theirs",
                &resolved_commit,
            ],
            &env,
            120,
        )
        .await?
    } else {
        merge
    };
    if merge.exit_code != 0 {
        let summary = compact_text(
            &format!(
                "{}\nstatus=failed\nreason=merge_failed_aborted",
                compact_git_error(&merge)
            ),
            1200,
        );
        let _ = run_git_command(sandbox_code_root, &["merge", "--abort"], &env, 60).await;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary,
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }

    let git_head = short_git_head(sandbox_code_root, &env).await?;
    Ok(AcceptedWorktreeIntegrationResult {
        status: "merged".to_string(),
        summary: compact_text(
            &format!(
                "resolved_commit_ref={resolved_commit}\n{}\nstatus=merged\ngit_head={git_head}",
                merge.stdout.trim()
            ),
            1200,
        ),
        commit_ref: resolved_commit,
        dirty_signature: None,
    })
}

async fn resolve_accepted_worktree_commit(
    worktree_path: &Path,
    commit_ref: &str,
    env: &[(String, String)],
) -> CoreResult<Option<String>> {
    let exists = run_git_command(
        worktree_path,
        &["cat-file", "-e", &format!("{commit_ref}^{{commit}}")],
        env,
        60,
    )
    .await?;
    if exists.exit_code == 0 {
        let resolved = run_git_command(
            worktree_path,
            &["rev-parse", &format!("{commit_ref}^{{commit}}")],
            env,
            60,
        )
        .await?;
        if resolved.exit_code == 0 {
            return Ok(Some(resolved.stdout.trim().to_string()));
        }
    }
    let short_commit = commit_ref.chars().take(12).collect::<String>();
    let repaired = run_git_command(
        worktree_path,
        &[
            "rev-parse",
            "--verify",
            "--quiet",
            &format!("{short_commit}^{{commit}}"),
        ],
        env,
        60,
    )
    .await?;
    if repaired.exit_code == 0 {
        let value = repaired.stdout.trim();
        if !value.is_empty() {
            return Ok(Some(value.to_string()));
        }
    }
    Ok(None)
}
