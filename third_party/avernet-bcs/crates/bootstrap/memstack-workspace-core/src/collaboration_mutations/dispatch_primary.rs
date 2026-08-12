use axum::response::Response;
use memstack_workspace_service::{
    PublicCreateBlackboardPostInput, PublicCreateBlackboardReplyInput,
    PublicCreateWorkspaceObjectiveInput, PublicCreateWorkspaceTaskInput,
    PublicUpdateBlackboardPostFields, PublicUpdateBlackboardReplyInput,
    PublicUpdateWorkspaceObjectiveFields, PublicUpdateWorkspaceTaskFields,
    PublicWorkspaceBlackboardError, PublicWorkspaceBlackboardErrorKind,
    PublicWorkspaceBlackboardService, PublicWorkspaceObjectiveError,
    PublicWorkspaceObjectiveErrorKind, PublicWorkspaceObjectiveService, PublicWorkspaceTaskError,
    PublicWorkspaceTaskErrorKind, PublicWorkspaceTaskRecoveryInput, PublicWorkspaceTaskService,
};
use serde_json::Value;

use super::models::{
    MutationAction, ObjectiveCreatePayload, ObjectiveIdPayload, ObjectiveProjectionPayload,
    ObjectiveUpdatePayload, PostCreatePayload, PostIdPayload, PostUpdatePayload,
    ReplyCreatePayload, ReplyDeletePayload, ReplyUpdatePayload, TaskAssignPayload,
    TaskCreatePayload, TaskIdPayload, TaskRecoveryPayload, TaskUpdatePayload,
};
use super::{
    AuthorityFacts, CommandContext, FailureKind, blackboard_context, objective_context,
    parse_payload, resolve_service_result, task_context,
};
use crate::WorkspaceCoreState;

pub(super) async fn dispatch(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    match command.action {
        MutationAction::CreateObjective => create_objective(state, command, payload).await,
        MutationAction::UpdateObjective => update_objective(state, command, payload).await,
        MutationAction::DeleteObjective => delete_objective(state, command, payload).await,
        MutationAction::ProjectObjectiveToTask => {
            project_objective_to_task(state, command, payload).await
        }
        MutationAction::CreateTask => create_task(state, command, payload).await,
        MutationAction::UpdateTask => update_task(state, command, payload).await,
        MutationAction::DeleteTask => delete_task(state, command, payload).await,
        MutationAction::AssignTaskAgent => assign_task(state, command, payload).await,
        MutationAction::UnassignTaskAgent => unassign_task(state, command, payload).await,
        MutationAction::ApplyTaskRecoveryAction => recover_task(state, command, payload).await,
        MutationAction::CreatePost => create_post(state, command, payload).await,
        MutationAction::UpdatePost => update_post(state, command, payload).await,
        MutationAction::DeletePost => delete_post(state, command, payload).await,
        MutationAction::PinPost => set_post_pinned(state, command, payload, true).await,
        MutationAction::UnpinPost => set_post_pinned(state, command, payload, false).await,
        MutationAction::CreateReply => create_reply(state, command, payload).await,
        MutationAction::UpdateReply => update_reply(state, command, payload).await,
        MutationAction::DeleteReply => delete_reply(state, command, payload).await,
        _ => Err(super::invalid_payload()),
    }
}

async fn create_objective(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: ObjectiveCreatePayload = parse_payload(payload)?;
    let input = PublicCreateWorkspaceObjectiveInput {
        context: objective_context(command),
        title: payload.title,
        description: payload.description,
        objective_type: payload.obj_type,
        parent_objective_id: payload.parent_id,
        progress: payload.progress,
    };
    let result = objective_service(state, command)?.create(&input).await;
    let outcome = resolve_service_result(state, command, result, objective_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_objective(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: ObjectiveUpdatePayload = parse_payload(payload)?;
    let context = objective_context(command);
    let fields = PublicUpdateWorkspaceObjectiveFields {
        title: payload.title,
        description: payload.description,
        objective_type: payload.obj_type,
        parent_objective_id: payload.parent_id,
        progress: payload.progress,
    };
    let result = objective_service(state, command)?
        .update(&context, payload.objective_id.as_str(), &fields)
        .await;
    let outcome = resolve_service_result(state, command, result, objective_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn delete_objective(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: ObjectiveIdPayload = parse_payload(payload)?;
    let result = objective_service(state, command)?
        .delete(&objective_context(command), payload.objective_id.as_str())
        .await;
    let outcome = resolve_service_result(state, command, result, objective_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn project_objective_to_task(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: ObjectiveProjectionPayload = parse_payload(payload)?;
    let result = objective_service(state, command)?
        .project_to_task(
            &objective_context(command),
            payload.objective_id.as_str(),
            payload.preferred_language.as_deref(),
        )
        .await;
    let outcome = resolve_service_result(state, command, result, objective_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn create_task(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: TaskCreatePayload = parse_payload(payload)?;
    let input = PublicCreateWorkspaceTaskInput {
        context: task_context(command),
        title: payload.title,
        description: payload.description,
        assignee_user_id: payload.assignee_user_id,
        metadata: payload.metadata,
        preferred_language: payload.preferred_language,
        priority: payload.priority,
        estimated_effort: payload.estimated_effort,
        blocker_reason: payload.blocker_reason,
    };
    let result = task_service(state, command)?.create(&input).await;
    let outcome = resolve_service_result(state, command, result, task_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_task(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: TaskUpdatePayload = parse_payload(payload)?;
    let fields = PublicUpdateWorkspaceTaskFields {
        title: payload.title,
        description: payload.description,
        assignee_user_id: payload.assignee_user_id,
        status: payload.status,
        metadata: payload.metadata,
        priority: payload.priority,
        estimated_effort: payload.estimated_effort,
        blocker_reason: payload.blocker_reason,
    };
    let result = task_service(state, command)?
        .update(&task_context(command), payload.task_id.as_str(), &fields)
        .await;
    let outcome = resolve_service_result(state, command, result, task_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn delete_task(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: TaskIdPayload = parse_payload(payload)?;
    let result = task_service(state, command)?
        .delete(&task_context(command), payload.task_id.as_str())
        .await;
    let outcome = resolve_service_result(state, command, result, task_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn assign_task(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: TaskAssignPayload = parse_payload(payload)?;
    let result = task_service(state, command)?
        .assign_agent(
            &task_context(command),
            payload.task_id.as_str(),
            payload.workspace_agent_id.as_str(),
            payload.preferred_language.as_deref(),
        )
        .await;
    let outcome = resolve_service_result(state, command, result, task_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn unassign_task(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: TaskIdPayload = parse_payload(payload)?;
    let result = task_service(state, command)?
        .unassign_agent(&task_context(command), payload.task_id.as_str())
        .await;
    let outcome = resolve_service_result(state, command, result, task_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn recover_task(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: TaskRecoveryPayload = parse_payload(payload)?;
    let input = PublicWorkspaceTaskRecoveryInput {
        action: payload.action,
        reason: payload.reason,
        workspace_agent_id: payload.workspace_agent_id,
    };
    let result = task_service(state, command)?
        .recovery_action_with_authority(&task_context(command), payload.task_id.as_str(), &input)
        .await;
    let outcome = resolve_service_result(state, command, result, task_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn create_post(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: PostCreatePayload = parse_payload(payload)?;
    let input = PublicCreateBlackboardPostInput {
        context: blackboard_context(command),
        title: payload.title,
        content: payload.content,
        status: payload.status,
        is_pinned: payload.is_pinned,
        metadata: payload.metadata,
    };
    let result = blackboard_service(state, command)?
        .create_post(&input)
        .await;
    let outcome = resolve_service_result(state, command, result, blackboard_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_post(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: PostUpdatePayload = parse_payload(payload)?;
    let fields = PublicUpdateBlackboardPostFields {
        title: payload.title,
        content: payload.content,
        status: payload.status,
        is_pinned: payload.is_pinned,
        metadata: payload.metadata,
    };
    let result = blackboard_service(state, command)?
        .update_post(
            &blackboard_context(command),
            payload.post_id.as_str(),
            &fields,
        )
        .await;
    let outcome = resolve_service_result(state, command, result, blackboard_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn delete_post(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: PostIdPayload = parse_payload(payload)?;
    let result = blackboard_service(state, command)?
        .delete_post_with_outcome(&blackboard_context(command), payload.post_id.as_str())
        .await;
    let outcome = resolve_service_result(state, command, result, blackboard_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn set_post_pinned(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
    pinned: bool,
) -> Result<AuthorityFacts, Response> {
    let payload: PostIdPayload = parse_payload(payload)?;
    let result = blackboard_service(state, command)?
        .set_post_pinned(
            &blackboard_context(command),
            payload.post_id.as_str(),
            pinned,
        )
        .await;
    let outcome = resolve_service_result(state, command, result, blackboard_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn create_reply(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: ReplyCreatePayload = parse_payload(payload)?;
    let input = PublicCreateBlackboardReplyInput {
        context: blackboard_context(command),
        content: payload.content,
        metadata: payload.metadata,
    };
    let result = blackboard_service(state, command)?
        .create_reply(payload.post_id.as_str(), &input)
        .await;
    let outcome = resolve_service_result(state, command, result, blackboard_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_reply(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: ReplyUpdatePayload = parse_payload(payload)?;
    let input = PublicUpdateBlackboardReplyInput {
        content: payload.content,
        metadata: payload.metadata,
    };
    let result = blackboard_service(state, command)?
        .update_reply(
            &blackboard_context(command),
            payload.post_id.as_str(),
            payload.reply_id.as_str(),
            &input,
        )
        .await;
    let outcome = resolve_service_result(state, command, result, blackboard_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn delete_reply(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: ReplyDeletePayload = parse_payload(payload)?;
    let result = blackboard_service(state, command)?
        .delete_reply_with_outcome(
            &blackboard_context(command),
            payload.post_id.as_str(),
            payload.reply_id.as_str(),
        )
        .await;
    let outcome = resolve_service_result(state, command, result, blackboard_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

fn objective_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceObjectiveService<'a>, Response> {
    Ok(
        PublicWorkspaceObjectiveService::new(state.db.as_ref(), state.sql_flavor)
            .with_mutation_authority(command.receipt_authority()?),
    )
}

fn task_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceTaskService<'a>, Response> {
    Ok(
        PublicWorkspaceTaskService::new(state.db.as_ref(), state.sql_flavor)
            .with_mutation_authority(command.receipt_authority()?),
    )
}

fn blackboard_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceBlackboardService<'a>, Response> {
    Ok(
        PublicWorkspaceBlackboardService::new(state.db.as_ref(), state.sql_flavor)
            .with_mutation_authority(command.receipt_authority()?),
    )
}

const fn facts(revision: u64, replayed: bool) -> AuthorityFacts {
    AuthorityFacts {
        revision,
        duplicate: replayed,
    }
}

fn objective_error_kind(error: &PublicWorkspaceObjectiveError) -> FailureKind {
    match error.kind() {
        PublicWorkspaceObjectiveErrorKind::InvalidRequest => FailureKind::InvalidRequest,
        PublicWorkspaceObjectiveErrorKind::NotFound => FailureKind::NotFound,
        PublicWorkspaceObjectiveErrorKind::Forbidden => FailureKind::Forbidden,
        PublicWorkspaceObjectiveErrorKind::Conflict => FailureKind::Conflict,
        PublicWorkspaceObjectiveErrorKind::Unavailable => FailureKind::Unavailable,
    }
}

fn task_error_kind(error: &PublicWorkspaceTaskError) -> FailureKind {
    match error.kind() {
        PublicWorkspaceTaskErrorKind::InvalidRequest => FailureKind::InvalidRequest,
        PublicWorkspaceTaskErrorKind::NotFound => FailureKind::NotFound,
        PublicWorkspaceTaskErrorKind::Forbidden => FailureKind::Forbidden,
        PublicWorkspaceTaskErrorKind::Conflict => FailureKind::Conflict,
        PublicWorkspaceTaskErrorKind::Unavailable => FailureKind::Unavailable,
    }
}

fn blackboard_error_kind(error: &PublicWorkspaceBlackboardError) -> FailureKind {
    match error.kind() {
        PublicWorkspaceBlackboardErrorKind::InvalidRequest => FailureKind::InvalidRequest,
        PublicWorkspaceBlackboardErrorKind::NotFound => FailureKind::NotFound,
        PublicWorkspaceBlackboardErrorKind::Forbidden => FailureKind::Forbidden,
        PublicWorkspaceBlackboardErrorKind::Conflict => FailureKind::Conflict,
        PublicWorkspaceBlackboardErrorKind::Unavailable => FailureKind::Unavailable,
    }
}
