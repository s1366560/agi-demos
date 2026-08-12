//! Legacy-compatible public Workspace Agent mutation orchestration.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::{
    AgentId, AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
    WorkspaceAgentBindingId, WorkspaceCommandError, WorkspaceMemberRole, WorkspaceMutationAction,
    WorkspaceMutationAuthority,
};
use memstack_workspace_store::{
    WorkspaceAgentSnapshot, WorkspaceAgentStore, WorkspaceMemberStore, WorkspaceMutationPlanner,
    WorkspaceMutationStore, WorkspaceMutationStoreError, WorkspaceProfileStore,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::canonical_json;
use crate::public_mutations::{
    PublicWorkspaceMutationContext, PublicWorkspaceMutationError, PublicWorkspaceMutationOutcome,
    attach_receipt_authority, canonical_hash, mutation_command, parse_scope, resolve_revision,
};

const PUBLIC_AGENT_NAMESPACE: Uuid = Uuid::from_u128(0x3df7_c1e9_3e0a_4b7e_b85c_4ea2_02c5_0f21);
const DISPLAY_NAME_MAX_CHARS: usize = 120;
const DESCRIPTION_MAX_CHARS: usize = 500;
const THEME_COLOR_MAX_CHARS: usize = 32;
const LABEL_MAX_CHARS: usize = 64;
const MAX_HEX_RADIUS: i64 = 24;

/// Legacy POST Agent binding input.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicBindWorkspaceAgentInput {
    pub context: PublicWorkspaceMutationContext,
    pub agent_id: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub config: Value,
    pub is_active: bool,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub theme_color: Option<String>,
    pub label: Option<String>,
}

/// Legacy PATCH Agent binding input. `None` preserves persisted values.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicUpdateWorkspaceAgentInput {
    pub context: PublicWorkspaceMutationContext,
    pub workspace_agent_id: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub config: Option<Value>,
    pub is_active: Option<bool>,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub theme_color: Option<String>,
    pub label: Option<String>,
}

/// Legacy DELETE Agent binding input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicUnbindWorkspaceAgentInput {
    pub context: PublicWorkspaceMutationContext,
    pub workspace_agent_id: String,
}

/// Public compatibility service over the shared Agent roster transaction contract.
pub struct PublicWorkspaceAgentMutationService<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
    agent_registry: &'a dyn AgentRegistryPort,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceAgentMutationService<'a> {
    #[must_use]
    pub const fn new(
        db: &'a dyn DbPlugin,
        flavor: DbSqlFlavor,
        agent_registry: &'a dyn AgentRegistryPort,
    ) -> Self {
        Self {
            db,
            flavor,
            agent_registry,
            receipt_authority: None,
        }
    }

    /// Persist a collaboration receipt envelope with the Agent domain write.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    /// Bind one externally validated Agent to the Workspace and BCS roster.
    ///
    /// A POST for an already-bound Agent updates the existing relation and
    /// emits `workspace_agent_bound` with `is_update=true`, matching legacy.
    ///
    /// # Errors
    ///
    /// Returns a structured validation, permission, conflict, registry, or
    /// persistence error.
    pub async fn bind(
        &self,
        input: &PublicBindWorkspaceAgentInput,
    ) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
        validate_bind_input(input)?;
        let agent_id = AgentId::parse(input.agent_id.clone())?;
        let scope = parse_scope(&input.context)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let profile = profile_store
            .read_profile(&scope)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        require_editor_access(self.db, self.flavor, &scope, &input.context.user_id).await?;
        let revision =
            resolve_revision(&profile_store, &scope, input.context.expected_revision).await?;
        let command = attach_receipt_authority(
            mutation_command(
                &input.context,
                scope.clone(),
                WorkspaceMutationAction::BindAgent,
                revision,
                bind_request_hash(input)?,
            )?,
            self.receipt_authority.as_ref(),
        );
        let planner = WorkspaceMutationPlanner::new(self.flavor);
        if let Some(outcome) = WorkspaceMutationStore::new(self.db)
            .replay_committed(&command, &planner.replay_lookup(&command))
            .await?
        {
            return Ok(public_outcome(outcome));
        }

        let registry_agent = self
            .agent_registry
            .resolve(&AgentRegistryLookup::new(
                scope.tenant_id().clone(),
                scope.project_id().clone(),
                agent_id,
            ))
            .await?
            .ok_or(PublicWorkspaceMutationError::AgentUnavailable)?;
        if registry_agent.agent_id().as_str() != input.agent_id {
            return Err(AgentRegistryPortError::Unavailable.into());
        }

        let agent_store = WorkspaceAgentStore::new(self.db, self.flavor);
        let existing = agent_store
            .read_by_agent_id(&scope, &input.agent_id)
            .await?;
        let is_update = existing.is_some();
        let now = Utc::now();
        let persisted_at = now.to_rfc3339_opts(SecondsFormat::Micros, false);
        let response_at = now.to_rfc3339_opts(SecondsFormat::Micros, true);
        let binding = bind_snapshot(input, existing.as_ref(), &persisted_at)?;
        let bot_name = bind_bot_name(&binding, &registry_agent);
        let bot_info = bot_info(&binding);
        let mutations = if is_update {
            agent_store.update_mutations(
                &scope,
                &profile,
                &binding,
                &bot_name,
                &bot_info,
                &persisted_at,
            )
        } else {
            agent_store.insert_mutations(
                &scope,
                &profile,
                &binding,
                &bot_name,
                &bot_info,
                &persisted_at,
            )
        };
        let response = agent_response(&binding, Some(response_at.as_str()));
        let event_payload = json!({
            "workspace_id": &binding.workspace_id,
            "workspace_agent_id": &binding.binding_id,
            "agent_id": &binding.agent_id,
            "agent": &response,
            "is_update": is_update,
            "bound_by": &input.context.user_id,
        });
        let plan = planner.plan_existing(&command, mutations, response, event_payload)?;
        execute_agent(self.db, &command, plan, profile.is_deleted()).await
    }

    /// Patch one Agent binding and its BCS Bot projection.
    ///
    /// # Errors
    ///
    /// Returns a structured validation, permission, conflict, or persistence error.
    pub async fn update(
        &self,
        input: &PublicUpdateWorkspaceAgentInput,
    ) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
        validate_update_input(input)?;
        let _ = WorkspaceAgentBindingId::parse(input.workspace_agent_id.clone())?;
        let scope = parse_scope(&input.context)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let profile = profile_store
            .read_profile(&scope)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        require_editor_access(self.db, self.flavor, &scope, &input.context.user_id).await?;
        let revision =
            resolve_revision(&profile_store, &scope, input.context.expected_revision).await?;
        let command = attach_receipt_authority(
            mutation_command(
                &input.context,
                scope.clone(),
                WorkspaceMutationAction::UpdateAgentBinding,
                revision,
                update_request_hash(input)?,
            )?,
            self.receipt_authority.as_ref(),
        );
        let planner = WorkspaceMutationPlanner::new(self.flavor);
        if let Some(outcome) = WorkspaceMutationStore::new(self.db)
            .replay_committed(&command, &planner.replay_lookup(&command))
            .await?
        {
            return Ok(public_outcome(outcome));
        }

        let agent_store = WorkspaceAgentStore::new(self.db, self.flavor);
        let mut binding = agent_store
            .read_by_binding_id(&scope, &input.workspace_agent_id)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        apply_update(&mut binding, input)?;
        let now = Utc::now();
        let persisted_at = now.to_rfc3339_opts(SecondsFormat::Micros, false);
        let response_at = now.to_rfc3339_opts(SecondsFormat::Micros, true);
        binding.updated_at = Some(persisted_at.clone());
        let bot_name = binding
            .display_name
            .clone()
            .unwrap_or_else(|| binding.bot_name.clone());
        let bot_info = bot_info(&binding);
        let response = agent_response(&binding, Some(response_at.as_str()));
        let event_payload = json!({
            "workspace_id": &binding.workspace_id,
            "workspace_agent_id": &binding.binding_id,
            "agent_id": &binding.agent_id,
            "agent": &response,
            "is_update": true,
            "bound_by": &input.context.user_id,
        });
        let plan = planner.plan_existing(
            &command,
            agent_store.update_mutations(
                &scope,
                &profile,
                &binding,
                &bot_name,
                &bot_info,
                &persisted_at,
            ),
            response,
            event_payload,
        )?;
        execute_agent(self.db, &command, plan, profile.is_deleted()).await
    }

    /// Remove one Agent binding, BCS Bot, and Group Participant atomically.
    ///
    /// # Errors
    ///
    /// Returns a structured validation, permission, conflict, or persistence error.
    pub async fn unbind(
        &self,
        input: &PublicUnbindWorkspaceAgentInput,
    ) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
        let _ = WorkspaceAgentBindingId::parse(input.workspace_agent_id.clone())?;
        let scope = parse_scope(&input.context)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let profile = profile_store
            .read_profile(&scope)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        require_editor_access(self.db, self.flavor, &scope, &input.context.user_id).await?;
        let revision =
            resolve_revision(&profile_store, &scope, input.context.expected_revision).await?;
        let command = attach_receipt_authority(
            mutation_command(
                &input.context,
                scope.clone(),
                WorkspaceMutationAction::UnbindAgent,
                revision,
                unbind_request_hash(input)?,
            )?,
            self.receipt_authority.as_ref(),
        );
        let planner = WorkspaceMutationPlanner::new(self.flavor);
        if let Some(outcome) = WorkspaceMutationStore::new(self.db)
            .replay_committed(&command, &planner.replay_lookup(&command))
            .await?
        {
            return Ok(public_outcome(outcome));
        }

        let agent_store = WorkspaceAgentStore::new(self.db, self.flavor);
        let binding = agent_store
            .read_by_binding_id(&scope, &input.workspace_agent_id)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        let event_payload = json!({
            "workspace_id": &binding.workspace_id,
            "workspace_agent_id": &binding.binding_id,
            "agent_id": &binding.agent_id,
            "unbound_by": &input.context.user_id,
        });
        let plan = planner.plan_existing(
            &command,
            agent_store.remove_mutations(&scope, &profile, &binding),
            json!({
                "workspace_id": &binding.workspace_id,
                "workspace_agent_id": &binding.binding_id,
            }),
            event_payload,
        )?;
        execute_agent(self.db, &command, plan, profile.is_deleted()).await
    }
}

fn bind_snapshot(
    input: &PublicBindWorkspaceAgentInput,
    existing: Option<&WorkspaceAgentSnapshot>,
    persisted_at: &str,
) -> Result<WorkspaceAgentSnapshot, WorkspaceCommandError> {
    let target = resolve_hex_target(
        existing.and_then(|value| value.hex_q),
        existing.and_then(|value| value.hex_r),
        input.hex_q,
        input.hex_r,
    )?;
    let binding_id = existing
        .map(|value| value.binding_id.clone())
        .unwrap_or_else(|| binding_identifier(input));
    Ok(WorkspaceAgentSnapshot {
        binding_id: binding_id.clone(),
        workspace_id: input.context.workspace_id.clone(),
        agent_id: input.agent_id.clone(),
        bot_uuid: existing
            .map(|value| value.bot_uuid.clone())
            .unwrap_or_else(|| binding_id.clone()),
        participant_actor_id: existing
            .map(|value| value.participant_actor_id.clone())
            .unwrap_or_else(|| binding_id.clone()),
        bot_name: existing
            .map(|value| value.bot_name.clone())
            .unwrap_or_else(|| input.agent_id.clone()),
        display_name: input.display_name.clone(),
        description: input.description.clone(),
        config: input.config.clone(),
        is_active: input.is_active,
        hex_q: target.map(|value| value.0),
        hex_r: target.map(|value| value.1),
        theme_color: input
            .theme_color
            .clone()
            .or_else(|| existing.and_then(|value| value.theme_color.clone())),
        label: input
            .label
            .clone()
            .or_else(|| existing.and_then(|value| value.label.clone())),
        status: existing
            .map(|value| value.status.clone())
            .unwrap_or_else(|| "idle".to_string()),
        created_at: existing
            .map(|value| value.created_at.clone())
            .unwrap_or_else(|| persisted_at.to_string()),
        updated_at: Some(persisted_at.to_string()),
    })
}

async fn require_editor_access(
    db: &dyn DbPlugin,
    flavor: DbSqlFlavor,
    scope: &memstack_workspace_service_api::WorkspaceScope,
    user_id: &str,
) -> Result<(), PublicWorkspaceMutationError> {
    let member = WorkspaceMemberStore::new(db, flavor)
        .read_member(scope, user_id)
        .await?
        .ok_or(PublicWorkspaceMutationError::Forbidden)?;
    if matches!(
        member.role,
        WorkspaceMemberRole::Owner | WorkspaceMemberRole::Editor
    ) {
        Ok(())
    } else {
        Err(PublicWorkspaceMutationError::Forbidden)
    }
}

fn apply_update(
    binding: &mut WorkspaceAgentSnapshot,
    input: &PublicUpdateWorkspaceAgentInput,
) -> Result<(), WorkspaceCommandError> {
    let target = resolve_hex_target(binding.hex_q, binding.hex_r, input.hex_q, input.hex_r)?;
    if let Some(value) = &input.display_name {
        binding.display_name = Some(value.clone());
    }
    if let Some(value) = &input.description {
        binding.description = Some(value.clone());
    }
    if let Some(value) = &input.config {
        binding.config.clone_from(value);
    }
    if let Some(value) = input.is_active {
        binding.is_active = value;
    }
    if input.hex_q.is_some() || input.hex_r.is_some() {
        binding.hex_q = target.map(|value| value.0);
        binding.hex_r = target.map(|value| value.1);
    }
    if let Some(value) = &input.theme_color {
        binding.theme_color = Some(value.clone());
    }
    if let Some(value) = &input.label {
        binding.label = Some(value.clone());
    }
    Ok(())
}

fn resolve_hex_target(
    current_q: Option<i64>,
    current_r: Option<i64>,
    requested_q: Option<i64>,
    requested_r: Option<i64>,
) -> Result<Option<(i64, i64)>, WorkspaceCommandError> {
    if requested_q.is_none() && requested_r.is_none() {
        return current_q
            .zip(current_r)
            .map(validate_hex_target)
            .transpose();
    }
    let q = requested_q.or(current_q);
    let r = requested_r.or(current_r);
    match (q, r) {
        (Some(q), Some(r)) => validate_hex_target((q, r)).map(Some),
        _ => Err(WorkspaceCommandError::InvalidHexPair),
    }
}

fn validate_hex_target(target: (i64, i64)) -> Result<(i64, i64), WorkspaceCommandError> {
    let (q, r) = target;
    let s = q
        .checked_add(r)
        .ok_or(WorkspaceCommandError::HexOutOfBounds)?;
    if q.abs() > MAX_HEX_RADIUS || r.abs() > MAX_HEX_RADIUS || s.abs() > MAX_HEX_RADIUS {
        return Err(WorkspaceCommandError::HexOutOfBounds);
    }
    if (q, r) == (0, 0) {
        return Err(WorkspaceCommandError::ReservedHex);
    }
    Ok(target)
}

fn validate_bind_input(input: &PublicBindWorkspaceAgentInput) -> Result<(), WorkspaceCommandError> {
    validate_optional_text(&input.display_name, "display_name", DISPLAY_NAME_MAX_CHARS)?;
    validate_optional_text(&input.description, "description", DESCRIPTION_MAX_CHARS)?;
    validate_optional_text(&input.theme_color, "theme_color", THEME_COLOR_MAX_CHARS)?;
    validate_optional_text(&input.label, "label", LABEL_MAX_CHARS)?;
    if !input.config.is_object() {
        return Err(WorkspaceCommandError::ConfigNotObject);
    }
    let _ = resolve_hex_target(None, None, input.hex_q, input.hex_r)?;
    Ok(())
}

fn validate_update_input(
    input: &PublicUpdateWorkspaceAgentInput,
) -> Result<(), WorkspaceCommandError> {
    validate_optional_text(&input.display_name, "display_name", DISPLAY_NAME_MAX_CHARS)?;
    validate_optional_text(&input.description, "description", DESCRIPTION_MAX_CHARS)?;
    validate_optional_text(&input.theme_color, "theme_color", THEME_COLOR_MAX_CHARS)?;
    validate_optional_text(&input.label, "label", LABEL_MAX_CHARS)?;
    if input
        .config
        .as_ref()
        .is_some_and(|value| !value.is_object())
    {
        return Err(WorkspaceCommandError::ConfigNotObject);
    }
    Ok(())
}

fn validate_optional_text(
    value: &Option<String>,
    field: &'static str,
    max_chars: usize,
) -> Result<(), WorkspaceCommandError> {
    let Some(value) = value else {
        return Ok(());
    };
    let actual_chars = value.chars().count();
    if actual_chars > max_chars {
        return Err(WorkspaceCommandError::TooLong {
            field,
            max_chars,
            actual_chars,
        });
    }
    Ok(())
}

fn binding_identifier(input: &PublicBindWorkspaceAgentInput) -> String {
    let Some(idempotency_key) = &input.context.idempotency_key else {
        return Uuid::new_v4().to_string();
    };
    let mut digest = Sha256::new();
    for part in [
        input.context.tenant_id.as_str(),
        input.context.project_id.as_str(),
        input.context.workspace_id.as_str(),
        input.context.user_id.as_str(),
        input.agent_id.as_str(),
        idempotency_key.as_str(),
    ] {
        let part_len = u64::try_from(part.len()).map_or(u64::MAX, |length| length);
        digest.update(part_len.to_be_bytes());
        digest.update(part.as_bytes());
    }
    Uuid::new_v5(&PUBLIC_AGENT_NAMESPACE, &digest.finalize()).to_string()
}

fn bind_bot_name(binding: &WorkspaceAgentSnapshot, registry: &AgentRegistryAgent) -> String {
    binding
        .display_name
        .clone()
        .or_else(|| registry.display_name().map(str::to_string))
        .unwrap_or_else(|| registry.name().to_string())
}

fn bot_info(binding: &WorkspaceAgentSnapshot) -> String {
    canonical_json(&json!({
        "workspace_id": &binding.workspace_id,
        "agent_id": &binding.agent_id,
        "description": &binding.description,
        "config": &binding.config,
    }))
    .to_string()
}

fn agent_response(binding: &WorkspaceAgentSnapshot, updated_at: Option<&str>) -> Value {
    json!({
        "id": &binding.binding_id,
        "workspace_id": &binding.workspace_id,
        "agent_id": &binding.agent_id,
        "display_name": &binding.display_name,
        "description": &binding.description,
        "config": &binding.config,
        "is_active": binding.is_active,
        "hex_q": binding.hex_q,
        "hex_r": binding.hex_r,
        "theme_color": &binding.theme_color,
        "label": &binding.label,
        "status": &binding.status,
        "created_at": &binding.created_at,
        "updated_at": updated_at,
    })
}

fn bind_request_hash(
    input: &PublicBindWorkspaceAgentInput,
) -> Result<memstack_workspace_service_api::RequestHash, PublicWorkspaceMutationError> {
    canonical_hash(json!({
        "action": "bind_agent",
        "tenant_id": &input.context.tenant_id,
        "project_id": &input.context.project_id,
        "workspace_id": &input.context.workspace_id,
        "actor_id": &input.context.user_id,
        "agent_id": &input.agent_id,
        "display_name": &input.display_name,
        "description": &input.description,
        "config": &input.config,
        "is_active": input.is_active,
        "hex_q": input.hex_q,
        "hex_r": input.hex_r,
        "theme_color": &input.theme_color,
        "label": &input.label,
    }))
}

fn update_request_hash(
    input: &PublicUpdateWorkspaceAgentInput,
) -> Result<memstack_workspace_service_api::RequestHash, PublicWorkspaceMutationError> {
    canonical_hash(json!({
        "action": "update_agent_binding",
        "tenant_id": &input.context.tenant_id,
        "project_id": &input.context.project_id,
        "workspace_id": &input.context.workspace_id,
        "actor_id": &input.context.user_id,
        "workspace_agent_id": &input.workspace_agent_id,
        "display_name": &input.display_name,
        "description": &input.description,
        "config": &input.config,
        "is_active": input.is_active,
        "hex_q": input.hex_q,
        "hex_r": input.hex_r,
        "theme_color": &input.theme_color,
        "label": &input.label,
    }))
}

fn unbind_request_hash(
    input: &PublicUnbindWorkspaceAgentInput,
) -> Result<memstack_workspace_service_api::RequestHash, PublicWorkspaceMutationError> {
    canonical_hash(json!({
        "action": "unbind_agent",
        "tenant_id": &input.context.tenant_id,
        "project_id": &input.context.project_id,
        "workspace_id": &input.context.workspace_id,
        "actor_id": &input.context.user_id,
        "workspace_agent_id": &input.workspace_agent_id,
    }))
}

async fn execute_agent(
    db: &dyn DbPlugin,
    command: &memstack_workspace_service_api::WorkspaceMutationCommand,
    plan: memstack_workspace_store::WorkspaceMutationPlan,
    was_deleted: bool,
) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
    let outcome = WorkspaceMutationStore::new(db).execute(command, plan).await;
    let outcome = match outcome {
        Err(WorkspaceMutationStoreError::AccessDenied) if was_deleted => {
            return Err(PublicWorkspaceMutationError::NotFound);
        }
        Err(WorkspaceMutationStoreError::DomainConflict) => {
            return Err(PublicWorkspaceMutationError::InvalidRequest);
        }
        result => result?,
    };
    Ok(public_outcome(outcome))
}

fn public_outcome(
    outcome: memstack_workspace_store::WorkspaceMutationOutcome,
) -> PublicWorkspaceMutationOutcome {
    PublicWorkspaceMutationOutcome {
        receipt_id: outcome.receipt_id,
        committed_revision: outcome.committed_revision,
        response: outcome.response,
        replayed: outcome.replayed,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hex_target_rejects_reserved_center_partial_pairs_and_radius_overflow() {
        assert_eq!(
            resolve_hex_target(None, None, Some(0), Some(0)),
            Err(WorkspaceCommandError::ReservedHex)
        );
        assert_eq!(
            resolve_hex_target(None, None, Some(1), None),
            Err(WorkspaceCommandError::InvalidHexPair)
        );
        assert_eq!(
            resolve_hex_target(None, None, Some(24), Some(1)),
            Err(WorkspaceCommandError::HexOutOfBounds)
        );
        assert_eq!(
            resolve_hex_target(None, None, Some(24), Some(-24)),
            Ok(Some((24, -24)))
        );
    }
}
