use std::sync::Arc;

use axum::http::HeaderMap;
use axum::response::Response;
use memstack_workspace_service::{
    PublicAddWorkspaceMemberInput, PublicBindWorkspaceAgentInput, PublicCreateTopologyEdgeInput,
    PublicCreateTopologyNodeInput, PublicCreateWorkspaceGeneInput,
    PublicRemoveWorkspaceMemberInput, PublicUnbindWorkspaceAgentInput,
    PublicUpdateTopologyEdgeFields, PublicUpdateTopologyNodeFields,
    PublicUpdateWorkspaceAgentInput, PublicUpdateWorkspaceGeneFields, PublicUpdateWorkspaceInput,
    PublicUpdateWorkspaceMemberInput, PublicWorkspaceAgentMutationService,
    PublicWorkspaceFileError, PublicWorkspaceFileErrorKind, PublicWorkspaceFileService,
    PublicWorkspaceGeneError, PublicWorkspaceGeneErrorKind, PublicWorkspaceGeneService,
    PublicWorkspaceMemberMutationService, PublicWorkspaceMutationError,
    PublicWorkspaceMutationErrorKind, PublicWorkspaceMutationService, PublicWorkspaceTopologyError,
    PublicWorkspaceTopologyErrorKind, PublicWorkspaceTopologyService, WorkspaceMemberRole,
};
use serde_json::Value;

use super::models::{
    AgentBindPayload, AgentUpdatePayload, DirectoryCreatePayload, EdgeCreatePayload, EdgeIdPayload,
    EdgeUpdatePayload, FileCopyPayload, FileDeletePayload, FileUpdatePayload, GeneCreatePayload,
    GeneIdPayload, GeneUpdatePayload, MemberAddPayload, MemberUpdatePayload, MutationAction,
    NodeCreatePayload, NodeIdPayload, NodeUpdatePayload, UserIdPayload, WorkspaceAgentIdPayload,
    WorkspaceUpdatePayload,
};
use super::{
    AuthorityFacts, CommandContext, FailureKind, file_context, gene_context, mutation_context,
    parse_payload, resolve_service_result, topology_context,
};
use crate::WorkspaceCoreState;

pub(super) async fn dispatch(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    headers: &HeaderMap,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    match command.action {
        MutationAction::BindAgent => bind_agent(state, command, payload).await,
        MutationAction::UpdateAgentBinding => update_agent(state, command, payload).await,
        MutationAction::UnbindAgent => unbind_agent(state, command, payload).await,
        MutationAction::AddMember => add_member(state, command, payload).await,
        MutationAction::UpdateMemberRole => update_member(state, command, payload).await,
        MutationAction::RemoveMember => remove_member(state, command, payload).await,
        MutationAction::CreateGene => create_gene(state, command, payload).await,
        MutationAction::UpdateGene => update_gene(state, command, payload).await,
        MutationAction::DeleteGene => delete_gene(state, command, payload).await,
        MutationAction::CreateDirectory => create_directory(state, command, headers, payload).await,
        MutationAction::UpdateFile => update_file(state, command, headers, payload).await,
        MutationAction::DeleteFile => delete_file(state, command, headers, payload).await,
        MutationAction::CopyFile => copy_file(state, command, headers, payload).await,
        MutationAction::CreateNode => create_node(state, command, payload).await,
        MutationAction::UpdateNode => update_node(state, command, payload).await,
        MutationAction::DeleteNode => delete_node(state, command, payload).await,
        MutationAction::CreateEdge => create_edge(state, command, payload).await,
        MutationAction::UpdateEdge => update_edge(state, command, payload).await,
        MutationAction::DeleteEdge => delete_edge(state, command, payload).await,
        MutationAction::UpdateWorkspace => update_workspace(state, command, payload).await,
        _ => Err(super::invalid_payload()),
    }
}

async fn bind_agent(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: AgentBindPayload = parse_payload(payload)?;
    let input = PublicBindWorkspaceAgentInput {
        context: mutation_context(command),
        agent_id: payload.agent_id,
        display_name: payload.display_name,
        description: payload.description,
        config: payload.config,
        is_active: payload.is_active,
        hex_q: payload.hex_q,
        hex_r: payload.hex_r,
        theme_color: payload.theme_color,
        label: payload.label,
    };
    let result = agent_service(state, command)?.bind(&input).await;
    let outcome = resolve_service_result(state, command, result, mutation_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_agent(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: AgentUpdatePayload = parse_payload(payload)?;
    let input = PublicUpdateWorkspaceAgentInput {
        context: mutation_context(command),
        workspace_agent_id: payload.workspace_agent_id,
        display_name: payload.display_name,
        description: payload.description,
        config: payload.config,
        is_active: payload.is_active,
        hex_q: payload.hex_q,
        hex_r: payload.hex_r,
        theme_color: payload.theme_color,
        label: payload.label,
    };
    let result = agent_service(state, command)?.update(&input).await;
    let outcome = resolve_service_result(state, command, result, mutation_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn unbind_agent(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: WorkspaceAgentIdPayload = parse_payload(payload)?;
    let input = PublicUnbindWorkspaceAgentInput {
        context: mutation_context(command),
        workspace_agent_id: payload.workspace_agent_id,
    };
    let result = agent_service(state, command)?.unbind(&input).await;
    let outcome = resolve_service_result(state, command, result, mutation_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn add_member(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: MemberAddPayload = parse_payload(payload)?;
    let input = PublicAddWorkspaceMemberInput {
        context: mutation_context(command),
        user_id: payload.user_id,
        role: role(payload.role.as_str())?,
    };
    let result = member_service(state, command)?.add(&input).await;
    let outcome = resolve_service_result(state, command, result, mutation_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_member(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: MemberUpdatePayload = parse_payload(payload)?;
    let input = PublicUpdateWorkspaceMemberInput {
        context: mutation_context(command),
        user_id: payload.user_id,
        role: role(payload.role.as_str())?,
    };
    let result = member_service(state, command)?.update(&input).await;
    let outcome = resolve_service_result(state, command, result, mutation_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn remove_member(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: UserIdPayload = parse_payload(payload)?;
    let input = PublicRemoveWorkspaceMemberInput {
        context: mutation_context(command),
        user_id: payload.user_id,
    };
    let result = member_service(state, command)?.remove(&input).await;
    let outcome = resolve_service_result(state, command, result, mutation_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn create_gene(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: GeneCreatePayload = parse_payload(payload)?;
    let input = PublicCreateWorkspaceGeneInput {
        context: gene_context(command),
        name: payload.name,
        category: payload.category,
        description: payload.description,
        config_json: payload.config_json,
        version: payload.version,
        is_active: payload.is_active,
    };
    let result = gene_service(state, command)?.create(&input).await;
    let outcome = resolve_service_result(state, command, result, gene_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_gene(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: GeneUpdatePayload = parse_payload(payload)?;
    let fields = PublicUpdateWorkspaceGeneFields {
        name: payload.name,
        category: payload.category,
        description: payload.description,
        config_json: payload.config_json,
        version: payload.version,
        is_active: payload.is_active,
    };
    let result = gene_service(state, command)?
        .update(&gene_context(command), payload.gene_id.as_str(), &fields)
        .await;
    let outcome = resolve_service_result(state, command, result, gene_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn delete_gene(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: GeneIdPayload = parse_payload(payload)?;
    let result = gene_service(state, command)?
        .delete_with_outcome(&gene_context(command), payload.gene_id.as_str())
        .await;
    let outcome = resolve_service_result(state, command, result, gene_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn create_directory(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    headers: &HeaderMap,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: DirectoryCreatePayload = parse_payload(payload)?;
    let context = file_context(command, headers)?;
    let result = file_service(state, command)?
        .create_directory(
            &context,
            payload.parent_path.as_str(),
            payload.name.as_str(),
        )
        .await;
    let outcome = resolve_service_result(state, command, result, file_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_file(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    headers: &HeaderMap,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: FileUpdatePayload = parse_payload(payload)?;
    let context = file_context(command, headers)?;
    let result = file_service(state, command)?
        .patch(
            &context,
            payload.file_id.as_str(),
            payload.name.as_deref(),
            payload.parent_path.as_deref(),
        )
        .await;
    let outcome = resolve_service_result(state, command, result, file_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn delete_file(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    headers: &HeaderMap,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: FileDeletePayload = parse_payload(payload)?;
    let context = file_context(command, headers)?;
    let result = file_service(state, command)?
        .delete(&context, payload.file_id.as_str(), payload.recursive)
        .await;
    let outcome = resolve_service_result(state, command, result, file_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn copy_file(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    headers: &HeaderMap,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: FileCopyPayload = parse_payload(payload)?;
    let context = file_context(command, headers)?;
    let result = file_service(state, command)?
        .copy(
            &context,
            payload.file_id.as_str(),
            payload.target_parent_path.as_str(),
            payload.name.as_deref(),
        )
        .await;
    let outcome = resolve_service_result(state, command, result, file_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn create_node(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: NodeCreatePayload = parse_payload(payload)?;
    let input = PublicCreateTopologyNodeInput {
        context: topology_context(command),
        node_type: payload.node_type,
        ref_id: payload.ref_id,
        title: payload.title,
        position_x: payload.position_x,
        position_y: payload.position_y,
        hex_q: payload.hex_q,
        hex_r: payload.hex_r,
        status: payload.status,
        tags: payload.tags,
        data: payload.data,
    };
    let result = topology_service(state, command)?.create_node(&input).await;
    let outcome = resolve_service_result(state, command, result, topology_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_node(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: NodeUpdatePayload = parse_payload(payload)?;
    let fields = PublicUpdateTopologyNodeFields {
        node_type: payload.node_type,
        ref_id: payload.ref_id,
        title: payload.title,
        position_x: payload.position_x,
        position_y: payload.position_y,
        hex_q: payload.hex_q,
        hex_r: payload.hex_r,
        status: payload.status,
        tags: payload.tags,
        data: payload.data,
    };
    let result = topology_service(state, command)?
        .update_node(
            &topology_context(command),
            payload.node_id.as_str(),
            &fields,
        )
        .await;
    let outcome = resolve_service_result(state, command, result, topology_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn delete_node(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: NodeIdPayload = parse_payload(payload)?;
    let result = topology_service(state, command)?
        .delete_node(&topology_context(command), payload.node_id.as_str())
        .await;
    let outcome = resolve_service_result(state, command, result, topology_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn create_edge(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: EdgeCreatePayload = parse_payload(payload)?;
    let input = PublicCreateTopologyEdgeInput {
        context: topology_context(command),
        source_node_id: payload.source_node_id,
        target_node_id: payload.target_node_id,
        label: payload.label,
        direction: payload.direction,
        auto_created: payload.auto_created,
        data: payload.data,
    };
    let result = topology_service(state, command)?.create_edge(&input).await;
    let outcome = resolve_service_result(state, command, result, topology_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_edge(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: EdgeUpdatePayload = parse_payload(payload)?;
    let fields = PublicUpdateTopologyEdgeFields {
        source_node_id: payload.source_node_id,
        target_node_id: payload.target_node_id,
        label: payload.label,
        direction: payload.direction,
        auto_created: payload.auto_created,
        data: payload.data,
    };
    let result = topology_service(state, command)?
        .update_edge(
            &topology_context(command),
            payload.edge_id.as_str(),
            &fields,
        )
        .await;
    let outcome = resolve_service_result(state, command, result, topology_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn delete_edge(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: EdgeIdPayload = parse_payload(payload)?;
    let result = topology_service(state, command)?
        .delete_edge(&topology_context(command), payload.edge_id.as_str())
        .await;
    let outcome = resolve_service_result(state, command, result, topology_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

async fn update_workspace(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    payload: Value,
) -> Result<AuthorityFacts, Response> {
    let payload: WorkspaceUpdatePayload = parse_payload(payload)?;
    let input = PublicUpdateWorkspaceInput {
        context: mutation_context(command),
        name: payload.name,
        description: payload.description,
        is_archived: payload.is_archived,
        metadata: payload.metadata,
    };
    let result = mutation_service(state, command)?.update(&input).await;
    let outcome = resolve_service_result(state, command, result, mutation_error_kind).await?;
    Ok(facts(outcome.committed_revision, outcome.replayed))
}

fn role(value: &str) -> Result<WorkspaceMemberRole, Response> {
    WorkspaceMemberRole::parse(value).map_err(|_| super::invalid_payload())
}

fn agent_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceAgentMutationService<'a>, Response> {
    Ok(PublicWorkspaceAgentMutationService::new(
        state.db.as_ref(),
        state.sql_flavor,
        state.agent_registry.as_ref(),
    )
    .with_mutation_authority(command.receipt_authority()?))
}

fn member_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceMemberMutationService<'a>, Response> {
    Ok(
        PublicWorkspaceMemberMutationService::new(state.db.as_ref(), state.sql_flavor)
            .with_mutation_authority(command.receipt_authority()?),
    )
}

fn gene_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceGeneService<'a>, Response> {
    Ok(
        PublicWorkspaceGeneService::new(state.db.as_ref(), state.sql_flavor)
            .with_mutation_authority(command.receipt_authority()?),
    )
}

fn file_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceFileService<'a>, Response> {
    Ok(PublicWorkspaceFileService::new(
        state.db.as_ref(),
        state.sql_flavor,
        Arc::clone(&state.object_store),
    )
    .with_mutation_authority(command.receipt_authority()?))
}

fn topology_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceTopologyService<'a>, Response> {
    Ok(
        PublicWorkspaceTopologyService::new(state.db.as_ref(), state.sql_flavor)
            .with_mutation_authority(command.receipt_authority()?),
    )
}

fn mutation_service<'a>(
    state: &'a WorkspaceCoreState,
    command: &CommandContext,
) -> Result<PublicWorkspaceMutationService<'a>, Response> {
    Ok(
        PublicWorkspaceMutationService::new(state.db.as_ref(), state.sql_flavor)
            .with_mutation_authority(command.receipt_authority()?),
    )
}

const fn facts(revision: u64, replayed: bool) -> AuthorityFacts {
    AuthorityFacts {
        revision,
        duplicate: replayed,
    }
}

fn mutation_error_kind(error: &PublicWorkspaceMutationError) -> FailureKind {
    match error.kind() {
        PublicWorkspaceMutationErrorKind::Validation => FailureKind::InvalidRequest,
        PublicWorkspaceMutationErrorKind::NotFound => FailureKind::NotFound,
        PublicWorkspaceMutationErrorKind::Forbidden => FailureKind::Forbidden,
        PublicWorkspaceMutationErrorKind::Conflict => FailureKind::Conflict,
        PublicWorkspaceMutationErrorKind::Unavailable => FailureKind::Unavailable,
    }
}

fn gene_error_kind(error: &PublicWorkspaceGeneError) -> FailureKind {
    match error.kind() {
        PublicWorkspaceGeneErrorKind::InvalidRequest => FailureKind::InvalidRequest,
        PublicWorkspaceGeneErrorKind::NotFound => FailureKind::NotFound,
        PublicWorkspaceGeneErrorKind::Forbidden => FailureKind::Forbidden,
        PublicWorkspaceGeneErrorKind::Conflict => FailureKind::Conflict,
        PublicWorkspaceGeneErrorKind::Unavailable => FailureKind::Unavailable,
    }
}

fn file_error_kind(error: &PublicWorkspaceFileError) -> FailureKind {
    match error.kind() {
        PublicWorkspaceFileErrorKind::InvalidRequest => FailureKind::InvalidRequest,
        PublicWorkspaceFileErrorKind::NotFound => FailureKind::NotFound,
        PublicWorkspaceFileErrorKind::Forbidden => FailureKind::Forbidden,
        PublicWorkspaceFileErrorKind::Conflict => FailureKind::Conflict,
        PublicWorkspaceFileErrorKind::Unavailable => FailureKind::Unavailable,
    }
}

fn topology_error_kind(error: &PublicWorkspaceTopologyError) -> FailureKind {
    match error.kind() {
        PublicWorkspaceTopologyErrorKind::InvalidRequest => FailureKind::InvalidRequest,
        PublicWorkspaceTopologyErrorKind::NotFound => FailureKind::NotFound,
        PublicWorkspaceTopologyErrorKind::Forbidden => FailureKind::Forbidden,
        PublicWorkspaceTopologyErrorKind::Conflict => FailureKind::Conflict,
        PublicWorkspaceTopologyErrorKind::Unavailable => FailureKind::Unavailable,
    }
}
