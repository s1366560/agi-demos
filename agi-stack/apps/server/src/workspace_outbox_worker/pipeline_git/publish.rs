use super::commands::{
    compact_git_error, create_git_askpass_script, is_non_fast_forward_push_rejection,
    is_unrelated_history_merge_rejection, run_git_command,
};
use super::*;

mod remote_merge;

use self::remote_merge::merge_remote_branch_for_publish;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct GitPublishResult {
    pub(super) status: String,
    pub(super) reason: Option<String>,
    pub(super) published_commit: Option<String>,
}

pub(super) async fn publish_git_ref_to_source_control(
    host_code_root: &Path,
    commit_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    token_env: Option<&str>,
    token: Option<&str>,
) -> CoreResult<GitPublishResult> {
    if !host_code_root.exists() {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(format!(
                "host_code_root does not exist: {}",
                host_code_root.display()
            )),
            published_commit: None,
        });
    }
    if !is_safe_git_branch(branch) {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some("unsafe git branch name".to_string()),
            published_commit: None,
        });
    }

    let mut env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    let askpass_path = if let Some(token) = token {
        let path = create_git_askpass_script().await?;
        env.push((
            "GIT_ASKPASS".to_string(),
            path.to_string_lossy().to_string(),
        ));
        env.push(("GIT_TOKEN".to_string(), token.to_string()));
        env.push((
            "GIT_USERNAME".to_string(),
            if token_env == Some("GITLAB_TOKEN") {
                "oauth2".to_string()
            } else {
                "x-access-token".to_string()
            },
        ));
        Some(path)
    } else {
        None
    };

    let result = publish_git_ref_to_source_control_with_env(
        host_code_root,
        commit_ref,
        branch,
        remote_url,
        &env,
    )
    .await;
    if let Some(path) = askpass_path {
        let _ = tokio::fs::remove_file(path).await;
    }
    result
}

async fn publish_git_ref_to_source_control_with_env(
    host_code_root: &Path,
    commit_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
) -> CoreResult<GitPublishResult> {
    let exists = run_git_command(
        host_code_root,
        &["cat-file", "-e", &format!("{commit_ref}^{{commit}}")],
        env,
        60,
    )
    .await?;
    if exists.exit_code != 0 {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&exists)),
            published_commit: None,
        });
    }

    let dirty = run_git_command(host_code_root, &["status", "--porcelain"], env, 60).await?;
    if !dirty.stdout.trim().is_empty() {
        return publish_git_ref_from_temporary_worktree(
            host_code_root,
            commit_ref,
            branch,
            remote_url,
            env,
            "published from temporary worktree because main checkout has uncommitted changes",
        )
        .await;
    }

    let already_ancestor = run_git_command(
        host_code_root,
        &["merge-base", "--is-ancestor", commit_ref, "HEAD"],
        env,
        60,
    )
    .await?;
    if already_ancestor.exit_code != 0 {
        let fast_forward = run_git_command(
            host_code_root,
            &["merge", "--ff-only", commit_ref],
            env,
            120,
        )
        .await?;
        if fast_forward.exit_code != 0 {
            if is_non_fast_forward_push_rejection(&fast_forward)
                || is_unrelated_history_merge_rejection(&fast_forward)
            {
                return publish_git_ref_from_temporary_worktree(
                    host_code_root,
                    commit_ref,
                    branch,
                    remote_url,
                    env,
                    "published from temporary worktree after local branch could not fast-forward to candidate",
                )
                .await;
            }
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&fast_forward)),
                published_commit: None,
            });
        }
    }

    let head = run_git_command(host_code_root, &["rev-parse", "HEAD"], env, 60).await?;
    if head.exit_code != 0 {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&head)),
            published_commit: None,
        });
    }
    let published_commit = head.stdout.trim().to_string();
    push_git_head_to_source_branch(host_code_root, &published_commit, branch, remote_url, env).await
}

async fn push_git_head_to_source_branch(
    host_code_root: &Path,
    published_commit: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
) -> CoreResult<GitPublishResult> {
    let remote = remote_url.unwrap_or("origin");
    let refspec = format!("HEAD:refs/heads/{branch}");
    let push = run_git_command(host_code_root, &["push", remote, &refspec], env, 180).await?;
    if push.exit_code == 0 {
        return Ok(GitPublishResult {
            status: "published".to_string(),
            reason: None,
            published_commit: Some(published_commit.to_string()),
        });
    }
    if is_non_fast_forward_push_rejection(&push) {
        return publish_git_ref_from_temporary_worktree(
            host_code_root,
            published_commit,
            branch,
            remote_url,
            env,
            "published from temporary worktree after remote branch advanced",
        )
        .await;
    }
    Ok(GitPublishResult {
        status: "failed".to_string(),
        reason: Some(compact_git_error(&push)),
        published_commit: Some(published_commit.to_string()),
    })
}

async fn publish_git_ref_from_temporary_worktree(
    host_code_root: &Path,
    publish_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
    default_reason: &str,
) -> CoreResult<GitPublishResult> {
    let temp_parent =
        std::env::temp_dir().join(format!("memstack-source-publish-{}", generate_uuid_v4()));
    let worktree_path = temp_parent.join("worktree");
    tokio::fs::create_dir_all(&temp_parent)
        .await
        .map_err(|err| {
            CoreError::Storage(format!(
                "failed to create source publish temp dir {}: {err}",
                temp_parent.display()
            ))
        })?;
    let mut added = false;
    let result = async {
        let worktree_path_string = worktree_path.to_string_lossy().to_string();
        let add = run_git_command(
            host_code_root,
            &[
                "worktree",
                "add",
                "--detach",
                &worktree_path_string,
                publish_ref,
            ],
            env,
            120,
        )
        .await?;
        if add.exit_code != 0 {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&add)),
                published_commit: None,
            });
        }
        added = true;
        let remote = remote_url.unwrap_or("origin");
        let remote_merge =
            merge_remote_branch_for_publish(&worktree_path, publish_ref, remote, branch, env)
                .await?;
        if remote_merge.status == "failed" {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(
                    remote_merge
                        .reason
                        .unwrap_or_else(|| "remote branch merge failed".to_string()),
                ),
                published_commit: None,
            });
        }
        let head = run_git_command(&worktree_path, &["rev-parse", "HEAD"], env, 60).await?;
        if head.exit_code != 0 {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&head)),
                published_commit: None,
            });
        }
        let published_commit = head.stdout.trim().to_string();
        let refspec = format!("HEAD:refs/heads/{branch}");
        let push = run_git_command(&worktree_path, &["push", remote, &refspec], env, 180).await?;
        if push.exit_code != 0 {
            if is_non_fast_forward_push_rejection(&push) {
                if let Some(retried) = retry_temporary_worktree_push_after_non_fast_forward(
                    &worktree_path,
                    &published_commit,
                    remote,
                    branch,
                    env,
                    default_reason,
                )
                .await?
                {
                    return Ok(retried);
                }
            }
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&push)),
                published_commit: Some(published_commit),
            });
        }
        Ok(GitPublishResult {
            status: "published".to_string(),
            reason: Some(
                remote_merge
                    .reason
                    .unwrap_or_else(|| default_reason.to_string()),
            ),
            published_commit: Some(published_commit),
        })
    }
    .await;

    if added {
        let worktree_path_string = worktree_path.to_string_lossy().to_string();
        let _ = run_git_command(
            host_code_root,
            &["worktree", "remove", "--force", &worktree_path_string],
            env,
            120,
        )
        .await;
    }
    let _ = tokio::fs::remove_dir_all(&temp_parent).await;
    result
}

async fn retry_temporary_worktree_push_after_non_fast_forward(
    worktree_path: &Path,
    candidate_ref: &str,
    remote: &str,
    branch: &str,
    env: &[(String, String)],
    default_reason: &str,
) -> CoreResult<Option<GitPublishResult>> {
    let retry_merge =
        merge_remote_branch_for_publish(worktree_path, candidate_ref, remote, branch, env).await?;
    if retry_merge.status == "failed" {
        return Ok(Some(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(
                retry_merge.reason.unwrap_or_else(|| {
                    "remote branch merge failed after push rejection".to_string()
                }),
            ),
            published_commit: Some(candidate_ref.to_string()),
        }));
    }
    let retry_head = run_git_command(worktree_path, &["rev-parse", "HEAD"], env, 60).await?;
    if retry_head.exit_code != 0 {
        return Ok(Some(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&retry_head)),
            published_commit: Some(candidate_ref.to_string()),
        }));
    }
    let retried_commit = retry_head.stdout.trim().to_string();
    let refspec = format!("HEAD:refs/heads/{branch}");
    let retry_push = run_git_command(worktree_path, &["push", remote, &refspec], env, 180).await?;
    if retry_push.exit_code == 0 {
        let retry_reason = retry_merge
            .reason
            .unwrap_or_else(|| default_reason.to_string());
        return Ok(Some(GitPublishResult {
            status: "published".to_string(),
            reason: Some(format!(
                "{retry_reason}; retried after non-fast-forward push"
            )),
            published_commit: Some(retried_commit),
        }));
    }
    Ok(None)
}
