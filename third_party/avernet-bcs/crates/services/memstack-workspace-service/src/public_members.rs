//! Legacy-compatible public Workspace member mutation orchestration.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::{
    UserId, WorkspaceMemberRole, WorkspaceMutationAction, WorkspaceMutationAuthority,
};
use memstack_workspace_store::{
    WorkspaceMemberSnapshot, WorkspaceMemberStore, WorkspaceMutationPlanner,
    WorkspaceMutationStore, WorkspaceMutationStoreError, WorkspaceProfileStore,
};
use serde_json::json;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::public_mutations::{
    PublicWorkspaceMutationContext, PublicWorkspaceMutationError, PublicWorkspaceMutationOutcome,
    attach_receipt_authority, canonical_hash, mutation_command, parse_scope, resolve_revision,
};

const PUBLIC_MEMBER_NAMESPACE: Uuid = Uuid::from_u128(0x129e_83a6_aa80_4561_a2c5_64ff_71c4_33e8);

/// Legacy POST member input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicAddWorkspaceMemberInput {
    pub context: PublicWorkspaceMutationContext,
    pub user_id: String,
    pub role: WorkspaceMemberRole,
}

/// Legacy PATCH member input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicUpdateWorkspaceMemberInput {
    pub context: PublicWorkspaceMutationContext,
    pub user_id: String,
    pub role: WorkspaceMemberRole,
}

/// Legacy DELETE member input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicRemoveWorkspaceMemberInput {
    pub context: PublicWorkspaceMutationContext,
    pub user_id: String,
}

/// Public compatibility service over the shared member transaction contract.
pub struct PublicWorkspaceMemberMutationService<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceMemberMutationService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            db,
            flavor,
            receipt_authority: None,
        }
    }

    /// Persist a collaboration receipt envelope with the member domain write.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    /// Add one Project principal to both Workspace ACL and BCS human roster.
    ///
    /// # Errors
    ///
    /// Returns a structured validation, permission, conflict, or persistence error.
    pub async fn add(
        &self,
        input: &PublicAddWorkspaceMemberInput,
    ) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
        let _ = UserId::parse(input.user_id.clone())?;
        let scope = parse_scope(&input.context)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let profile = profile_store
            .read_profile(&scope)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        let member_store = WorkspaceMemberStore::new(self.db, self.flavor);
        let has_project_membership = member_store
            .has_project_membership(&scope, &input.user_id)
            .await?;
        let revision =
            resolve_revision(&profile_store, &scope, input.context.expected_revision).await?;
        let command = attach_receipt_authority(
            mutation_command(
                &input.context,
                scope.clone(),
                WorkspaceMutationAction::AddMember,
                revision,
                canonical_hash(json!({
                    "action": "add_member",
                    "tenant_id": &input.context.tenant_id,
                    "project_id": &input.context.project_id,
                    "workspace_id": &input.context.workspace_id,
                    "actor_id": &input.context.user_id,
                    "user_id": &input.user_id,
                    "role": input.role.as_str(),
                }))?,
            )?,
            self.receipt_authority.as_ref(),
        );
        let now = Utc::now();
        let persisted_at = now.to_rfc3339_opts(SecondsFormat::Micros, false);
        let response_at = now.to_rfc3339_opts(SecondsFormat::Micros, true);
        let member = WorkspaceMemberSnapshot {
            member_id: member_identifier(input),
            workspace_id: input.context.workspace_id.clone(),
            user_id: input.user_id.clone(),
            participant_actor_id: input.user_id.clone(),
            role: input.role,
            invited_by: Some(input.context.user_id.clone()),
            created_at: persisted_at.clone(),
            updated_at: Some(persisted_at.clone()),
        };
        let response = member_response(&member, Some(response_at.as_str()));
        let event_payload = member_event_payload(&member, None, response_at.as_str());
        let plan = WorkspaceMutationPlanner::new(self.flavor).plan_existing(
            &command,
            member_store.add_mutations(&scope, &profile, &member, &persisted_at),
            response,
            event_payload,
        )?;
        execute_member(
            self.db,
            &command,
            plan,
            profile.is_deleted(),
            Some(has_project_membership),
        )
        .await
    }

    /// Update one Workspace ACL and BCS human roster role.
    ///
    /// # Errors
    ///
    /// Returns a structured validation, permission, conflict, or persistence error.
    pub async fn update(
        &self,
        input: &PublicUpdateWorkspaceMemberInput,
    ) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
        let _ = UserId::parse(input.user_id.clone())?;
        let scope = parse_scope(&input.context)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let profile = profile_store
            .read_profile(&scope)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        let member_store = WorkspaceMemberStore::new(self.db, self.flavor);
        let mut member = member_store
            .read_member(&scope, &input.user_id)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        let revision =
            resolve_revision(&profile_store, &scope, input.context.expected_revision).await?;
        let command = attach_receipt_authority(
            mutation_command(
                &input.context,
                scope.clone(),
                WorkspaceMutationAction::UpdateMemberRole,
                revision,
                canonical_hash(json!({
                    "action": "update_member_role",
                    "tenant_id": &input.context.tenant_id,
                    "project_id": &input.context.project_id,
                    "workspace_id": &input.context.workspace_id,
                    "actor_id": &input.context.user_id,
                    "user_id": &input.user_id,
                    "role": input.role.as_str(),
                }))?,
            )?,
            self.receipt_authority.as_ref(),
        );
        let now = Utc::now();
        let persisted_at = now.to_rfc3339_opts(SecondsFormat::Micros, false);
        let response_at = now.to_rfc3339_opts(SecondsFormat::Micros, true);
        member.role = input.role;
        member.updated_at = Some(persisted_at.clone());
        let response = member_response(&member, Some(response_at.as_str()));
        let event_payload = member_event_payload(
            &member,
            Some(input.context.user_id.as_str()),
            response_at.as_str(),
        );
        let plan = WorkspaceMutationPlanner::new(self.flavor).plan_existing(
            &command,
            member_store.update_role_mutations(
                &scope,
                &profile,
                &member,
                input.context.user_id.as_str(),
                &persisted_at,
            ),
            response,
            event_payload,
        )?;
        execute_member(self.db, &command, plan, profile.is_deleted(), None).await
    }

    /// Remove one Workspace ACL and BCS human roster participant.
    ///
    /// # Errors
    ///
    /// Returns a structured validation, permission, conflict, or persistence error.
    pub async fn remove(
        &self,
        input: &PublicRemoveWorkspaceMemberInput,
    ) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
        let _ = UserId::parse(input.user_id.clone())?;
        let scope = parse_scope(&input.context)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let profile = profile_store
            .read_profile(&scope)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        let member_store = WorkspaceMemberStore::new(self.db, self.flavor);
        let revision =
            resolve_revision(&profile_store, &scope, input.context.expected_revision).await?;
        let command = attach_receipt_authority(
            mutation_command(
                &input.context,
                scope.clone(),
                WorkspaceMutationAction::RemoveMember,
                revision,
                canonical_hash(json!({
                    "action": "remove_member",
                    "tenant_id": &input.context.tenant_id,
                    "project_id": &input.context.project_id,
                    "workspace_id": &input.context.workspace_id,
                    "actor_id": &input.context.user_id,
                    "user_id": &input.user_id,
                }))?,
            )?,
            self.receipt_authority.as_ref(),
        );
        let replay_lookup = WorkspaceMutationPlanner::new(self.flavor).replay_lookup(&command);
        if let Some(outcome) = WorkspaceMutationStore::new(self.db)
            .replay_committed(&command, &replay_lookup)
            .await?
        {
            return Ok(public_outcome(outcome));
        }
        let member = member_store
            .read_member(&scope, &input.user_id)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        let event_payload = json!({
            "workspace_id": &member.workspace_id,
            "member_id": &member.member_id,
            "user_id": &member.user_id,
            "role": member.role.as_str(),
            "invited_by": &member.invited_by,
            "member": member_response(&member, member.updated_at.as_deref()),
            "removed_by": &input.context.user_id,
        });
        let plan = WorkspaceMutationPlanner::new(self.flavor).plan_existing(
            &command,
            member_store.remove_mutations(
                &scope,
                &profile,
                &member,
                input.context.user_id.as_str(),
            ),
            json!({"workspace_id": &member.workspace_id, "user_id": &member.user_id}),
            event_payload,
        )?;
        execute_member(self.db, &command, plan, profile.is_deleted(), None).await
    }
}

fn member_identifier(input: &PublicAddWorkspaceMemberInput) -> String {
    let Some(idempotency_key) = &input.context.idempotency_key else {
        return Uuid::new_v4().to_string();
    };
    let mut digest = Sha256::new();
    for part in [
        input.context.tenant_id.as_str(),
        input.context.project_id.as_str(),
        input.context.workspace_id.as_str(),
        input.context.user_id.as_str(),
        input.user_id.as_str(),
        idempotency_key.as_str(),
    ] {
        let part_len = u64::try_from(part.len()).map_or(u64::MAX, |length| length);
        digest.update(part_len.to_be_bytes());
        digest.update(part.as_bytes());
    }
    Uuid::new_v5(&PUBLIC_MEMBER_NAMESPACE, &digest.finalize()).to_string()
}

fn member_response(
    member: &WorkspaceMemberSnapshot,
    updated_at: Option<&str>,
) -> serde_json::Value {
    json!({
        "id": &member.member_id,
        "workspace_id": &member.workspace_id,
        "user_id": &member.user_id,
        "user_email": null,
        "role": member.role.as_str(),
        "invited_by": &member.invited_by,
        "created_at": &member.created_at,
        "updated_at": updated_at,
    })
}

fn member_event_payload(
    member: &WorkspaceMemberSnapshot,
    updated_by: Option<&str>,
    response_at: &str,
) -> serde_json::Value {
    let mut payload = json!({
        "workspace_id": &member.workspace_id,
        "member_id": &member.member_id,
        "user_id": &member.user_id,
        "role": member.role.as_str(),
        "invited_by": &member.invited_by,
        "member": member_response(member, Some(response_at)),
    });
    if let Some(updated_by) = updated_by {
        payload["updated_by"] = serde_json::Value::String(updated_by.to_string());
    }
    payload
}

async fn execute_member(
    db: &dyn DbPlugin,
    command: &memstack_workspace_service_api::WorkspaceMutationCommand,
    plan: memstack_workspace_store::WorkspaceMutationPlan,
    was_deleted: bool,
    has_project_membership: Option<bool>,
) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
    let outcome = WorkspaceMutationStore::new(db).execute(command, plan).await;
    let outcome = match outcome {
        Err(WorkspaceMutationStoreError::AccessDenied) if was_deleted => {
            return Err(PublicWorkspaceMutationError::NotFound);
        }
        Err(WorkspaceMutationStoreError::DomainConflict)
            if has_project_membership == Some(false) =>
        {
            return Err(PublicWorkspaceMutationError::Forbidden);
        }
        Err(WorkspaceMutationStoreError::DomainConflict) => {
            return Err(PublicWorkspaceMutationError::InvalidRequest);
        }
        result => result?,
    };
    Ok(PublicWorkspaceMutationOutcome {
        receipt_id: outcome.receipt_id,
        committed_revision: outcome.committed_revision,
        response: outcome.response,
        replayed: outcome.replayed,
    })
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
