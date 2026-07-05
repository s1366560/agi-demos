use super::*;

mod accepted;
mod commands;
mod publish;
mod source_publish;

pub(super) use self::accepted::integrate_accepted_attempt_worktree_with_git;
pub(super) use self::commands::{
    compact_git_error, current_worktree_dirty_signature, run_git_command, short_git_head,
};
pub(super) use self::source_publish::{
    finish_drone_provider_unavailable, finish_drone_source_publish_failure,
    host_code_root_from_workspace, pipeline_contract_metadata, pipeline_run_metadata,
    prepare_drone_source_publish, source_publish_source_commit_ref, DroneSourcePublishOutcome,
};

fn is_safe_git_branch(value: &str) -> bool {
    let value = value.trim();
    if value.is_empty()
        || value.starts_with('-')
        || value.starts_with('/')
        || value.ends_with('/')
        || value.contains("..")
        || value.contains("//")
        || value.contains("@{")
        || value.contains('\\')
    {
        return false;
    }
    value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '/' | '-'))
}
