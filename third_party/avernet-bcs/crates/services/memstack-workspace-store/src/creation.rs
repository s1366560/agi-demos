//! Atomic first-time Workspace creation plans.

use bcs_db_api::{
    DbCountExpectation, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStep,
};
use memstack_workspace_service_api::{
    WorkspaceCreateOwner, WorkspaceCreateProfile, WorkspaceMutationAction, WorkspaceMutationCommand,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{LegacyWorkspaceEvent, LegacyWorkspaceEventError};

const INITIAL_COMMITTED_REVISION: u64 = 1;

/// Invalid first-time Workspace creation plan input.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceCreationPlanError {
    #[error("Workspace creation requires the create_workspace action")]
    InvalidAction,

    #[error("Workspace creation requires expected_revision=0")]
    InvalidExpectedRevision,

    #[error("Workspace creation owner must match the authenticated actor")]
    OwnerActorMismatch,

    #[error("Workspace creation event payload does not match the owner roster write")]
    OwnerEventMismatch,

    #[error("Workspace creation plans currently support only PostgreSQL and SQLite")]
    UnsupportedSqlFlavor,

    #[error("Workspace creation timestamps must not be blank")]
    InvalidTimestamp,

    #[error("Workspace creation owner email must not be blank")]
    InvalidOwnerEmail,

    #[error("Workspace autonomous bootstrap snapshot is invalid")]
    InvalidAutonomyBootstrap,

    #[error(transparent)]
    LegacyEvent(#[from] LegacyWorkspaceEventError),
}

/// Stable timestamps shared by the profile, owner membership, response, and
/// durable legacy event for one atomic creation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceCreationTimestamps {
    created_at: String,
    updated_at: String,
}

impl WorkspaceCreationTimestamps {
    /// Construct timestamps already formatted for the selected database.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCreationPlanError::InvalidTimestamp`] when either
    /// timestamp is blank.
    pub fn new(
        created_at: impl Into<String>,
        updated_at: impl Into<String>,
    ) -> Result<Self, WorkspaceCreationPlanError> {
        let created_at = created_at.into();
        let updated_at = updated_at.into();
        if created_at.trim().is_empty() || updated_at.trim().is_empty() {
            return Err(WorkspaceCreationPlanError::InvalidTimestamp);
        }
        Ok(Self {
            created_at,
            updated_at,
        })
    }

    #[must_use]
    pub fn created_at(&self) -> &str {
        &self.created_at
    }

    #[must_use]
    pub fn updated_at(&self) -> &str {
        &self.updated_at
    }
}

/// Authenticated owner identity projection sharing the creation timestamps.
#[derive(Debug, Clone, Copy)]
pub struct WorkspaceCreationOwnerIdentity<'a> {
    email: &'a str,
    timestamps: &'a WorkspaceCreationTimestamps,
}

impl<'a> WorkspaceCreationOwnerIdentity<'a> {
    /// Construct an identity projection from an authenticated non-blank email.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCreationPlanError::InvalidOwnerEmail`] for a blank email.
    pub fn new(
        email: &'a str,
        timestamps: &'a WorkspaceCreationTimestamps,
    ) -> Result<Self, WorkspaceCreationPlanError> {
        if email.trim().is_empty() {
            return Err(WorkspaceCreationPlanError::InvalidOwnerEmail);
        }
        Ok(Self { email, timestamps })
    }
}

/// Immutable durable snapshot used to bootstrap one autonomous root Objective.
#[derive(Debug, Clone, Copy)]
pub struct WorkspaceAutonomyBootstrapCreation<'a> {
    objective_title: &'a str,
    objective_description: Option<&'a str>,
    created_at_ms: i64,
}

impl<'a> WorkspaceAutonomyBootstrapCreation<'a> {
    /// Validate the snapshot before it is embedded in the creation transaction.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCreationPlanError::InvalidAutonomyBootstrap`] for an
    /// empty or oversized title or a negative creation timestamp.
    pub fn new(
        objective_title: &'a str,
        objective_description: Option<&'a str>,
        created_at_ms: i64,
    ) -> Result<Self, WorkspaceCreationPlanError> {
        if objective_title.trim().is_empty()
            || objective_title.chars().count() > 255
            || created_at_ms < 0
        {
            return Err(WorkspaceCreationPlanError::InvalidAutonomyBootstrap);
        }
        Ok(Self {
            objective_title,
            objective_description,
            created_at_ms,
        })
    }
}

/// Validated identity and Objective snapshot for one autonomous Workspace creation.
#[derive(Debug, Clone, Copy)]
pub struct WorkspaceAutonomousCreation<'a> {
    owner_identity: WorkspaceCreationOwnerIdentity<'a>,
    autonomy_bootstrap: WorkspaceAutonomyBootstrapCreation<'a>,
}

impl<'a> WorkspaceAutonomousCreation<'a> {
    #[must_use]
    pub const fn new(
        owner_identity: WorkspaceCreationOwnerIdentity<'a>,
        autonomy_bootstrap: WorkspaceAutonomyBootstrapCreation<'a>,
    ) -> Self {
        Self {
            owner_identity,
            autonomy_bootstrap,
        }
    }
}

#[derive(Debug, Clone, Copy)]
struct WorkspaceCreationPersistence<'a> {
    timestamps: Option<&'a WorkspaceCreationTimestamps>,
    owner_email: Option<&'a str>,
    autonomy_bootstrap: Option<WorkspaceAutonomyBootstrapCreation<'a>>,
}

impl WorkspaceCreationPersistence<'_> {
    const DATABASE_DEFAULTS: Self = Self {
        timestamps: None,
        owner_email: None,
        autonomy_bootstrap: None,
    };

    const fn with_timestamps(
        timestamps: &WorkspaceCreationTimestamps,
    ) -> WorkspaceCreationPersistence<'_> {
        WorkspaceCreationPersistence {
            timestamps: Some(timestamps),
            owner_email: None,
            autonomy_bootstrap: None,
        }
    }

    const fn with_owner_identity(
        owner_identity: WorkspaceCreationOwnerIdentity<'_>,
    ) -> WorkspaceCreationPersistence<'_> {
        WorkspaceCreationPersistence {
            timestamps: Some(owner_identity.timestamps),
            owner_email: Some(owner_identity.email),
            autonomy_bootstrap: None,
        }
    }

    const fn with_autonomous_creation<'a>(
        autonomous_creation: WorkspaceAutonomousCreation<'a>,
    ) -> WorkspaceCreationPersistence<'a> {
        WorkspaceCreationPersistence {
            timestamps: Some(autonomous_creation.owner_identity.timestamps),
            owner_email: Some(autonomous_creation.owner_identity.email),
            autonomy_bootstrap: Some(autonomous_creation.autonomy_bootstrap),
        }
    }
}

/// Ordered atomic transaction for a Workspace that does not yet exist.
#[derive(Debug, Clone)]
pub struct WorkspaceCreationPlan {
    receipt_id: String,
    outbox_id: String,
    receipt_lookup: DbStatement,
    steps: Vec<DbTransactionStep>,
    access_step: usize,
    absence_step: usize,
    receipt_insert_step: usize,
    domain_steps: Vec<usize>,
}

impl WorkspaceCreationPlan {
    #[must_use]
    pub fn receipt_id(&self) -> &str {
        &self.receipt_id
    }

    #[must_use]
    pub fn outbox_id(&self) -> &str {
        &self.outbox_id
    }

    #[must_use]
    pub const fn committed_revision(&self) -> u64 {
        INITIAL_COMMITTED_REVISION
    }

    #[must_use]
    pub const fn receipt_lookup(&self) -> &DbStatement {
        &self.receipt_lookup
    }

    #[must_use]
    pub fn steps(&self) -> &[DbTransactionStep] {
        &self.steps
    }

    #[must_use]
    pub fn into_steps(self) -> Vec<DbTransactionStep> {
        self.steps
    }

    pub(crate) const fn access_step(&self) -> usize {
        self.access_step
    }

    pub(crate) const fn absence_step(&self) -> usize {
        self.absence_step
    }

    pub(crate) const fn receipt_insert_step(&self) -> usize {
        self.receipt_insert_step
    }

    pub(crate) fn is_domain_step(&self, step: usize) -> bool {
        self.domain_steps.contains(&step)
    }
}

/// Builds first-time creation statements for PostgreSQL or SQLite.
#[derive(Debug, Clone, Copy)]
pub struct WorkspaceCreationPlanner {
    flavor: DbSqlFlavor,
}

impl WorkspaceCreationPlanner {
    #[must_use]
    pub const fn new(flavor: DbSqlFlavor) -> Self {
        Self { flavor }
    }

    /// Build Group, Profile, owner roster, authority, receipt, and outbox
    /// writes as one transaction.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCreationPlanError`] when the command is not a
    /// zero-revision create, the owner differs from the authenticated actor,
    /// the SQL flavor is unsupported, or the legacy event is invalid.
    pub fn plan(
        self,
        command: &WorkspaceMutationCommand,
        profile: WorkspaceCreateProfile,
        owner: WorkspaceCreateOwner,
        response: Value,
        event_payload: Value,
    ) -> Result<WorkspaceCreationPlan, WorkspaceCreationPlanError> {
        self.plan_inner(
            command,
            profile,
            owner,
            response,
            event_payload,
            WorkspaceCreationPersistence::DATABASE_DEFAULTS,
        )
    }

    /// Build the creation transaction with explicit profile/member timestamps.
    ///
    /// This is the compatibility path used by the application service so the
    /// committed response and durable owner event describe the same instant as
    /// the persisted rows. [`Self::plan`] remains available for upstream BCS
    /// callers that rely on database defaults.
    ///
    /// # Errors
    ///
    /// Returns the same structured errors as [`Self::plan`].
    pub fn plan_with_timestamps(
        self,
        command: &WorkspaceMutationCommand,
        profile: WorkspaceCreateProfile,
        owner: WorkspaceCreateOwner,
        response: Value,
        event_payload: Value,
        timestamps: &WorkspaceCreationTimestamps,
    ) -> Result<WorkspaceCreationPlan, WorkspaceCreationPlanError> {
        self.plan_inner(
            command,
            profile,
            owner,
            response,
            event_payload,
            WorkspaceCreationPersistence::with_timestamps(timestamps),
        )
    }

    /// Build the public creation transaction with an authenticated owner identity mirror.
    ///
    /// # Errors
    ///
    /// Returns the same structured errors as [`Self::plan_with_timestamps`].
    pub fn plan_with_owner_identity(
        self,
        command: &WorkspaceMutationCommand,
        profile: WorkspaceCreateProfile,
        owner: WorkspaceCreateOwner,
        response: Value,
        event_payload: Value,
        owner_identity: WorkspaceCreationOwnerIdentity<'_>,
    ) -> Result<WorkspaceCreationPlan, WorkspaceCreationPlanError> {
        self.plan_inner(
            command,
            profile,
            owner,
            response,
            event_payload,
            WorkspaceCreationPersistence::with_owner_identity(owner_identity),
        )
    }

    /// Build public creation plus a durable autonomous bootstrap request in
    /// the same transaction as the Workspace profile and initial authority.
    ///
    /// # Errors
    ///
    /// Returns the same structured errors as [`Self::plan_with_owner_identity`].
    pub fn plan_with_owner_identity_and_autonomy_bootstrap(
        self,
        command: &WorkspaceMutationCommand,
        profile: WorkspaceCreateProfile,
        owner: WorkspaceCreateOwner,
        response: Value,
        event_payload: Value,
        autonomous_creation: WorkspaceAutonomousCreation<'_>,
    ) -> Result<WorkspaceCreationPlan, WorkspaceCreationPlanError> {
        self.plan_inner(
            command,
            profile,
            owner,
            response,
            event_payload,
            WorkspaceCreationPersistence::with_autonomous_creation(autonomous_creation),
        )
    }

    fn plan_inner(
        self,
        command: &WorkspaceMutationCommand,
        profile: WorkspaceCreateProfile,
        owner: WorkspaceCreateOwner,
        response: Value,
        event_payload: Value,
        persistence: WorkspaceCreationPersistence<'_>,
    ) -> Result<WorkspaceCreationPlan, WorkspaceCreationPlanError> {
        if command.action() != WorkspaceMutationAction::CreateWorkspace {
            return Err(WorkspaceCreationPlanError::InvalidAction);
        }
        if command.expected_revision().get() != 0 {
            return Err(WorkspaceCreationPlanError::InvalidExpectedRevision);
        }
        if command.actor().actor_id().as_str() != owner.participant_actor_id().as_str() {
            return Err(WorkspaceCreationPlanError::OwnerActorMismatch);
        }
        if self.flavor == DbSqlFlavor::Mysql {
            return Err(WorkspaceCreationPlanError::UnsupportedSqlFlavor);
        }

        validate_owner_event_payload(command, &owner, &event_payload)?;
        let event = LegacyWorkspaceEvent::for_action(
            WorkspaceMutationAction::CreateWorkspace,
            command.scope().workspace_id().as_str(),
            event_payload,
        )?;
        let receipt_id = deterministic_creation_id("receipt", command);
        let outbox_id = deterministic_creation_id("outbox", command);
        let response_json = response.to_string();
        let payload_json = event.payload().to_string();
        let metadata_json = json!({
            "action": command.action().as_str(),
            "contract_version": command.contract_version().as_str(),
            "receipt_id": &receipt_id,
            "request_hash": command.request_hash().as_str(),
        })
        .to_string();
        let profile_metadata_json = profile.metadata().to_string();
        let receipt_lookup = self.receipt_lookup(command);

        let access_step = 0;
        let absence_step = 1;
        let group_step = 2;
        let profile_step = 3;
        let receipt_insert_step = 4;
        let member_step = 5;
        let mut steps = vec![
            DbTransactionStep::query_checked(
                self.project_access_check(command, &owner),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::query_checked(
                self.workspace_absence_check(command, &profile),
                DbCountExpectation::exactly(0),
            ),
            DbTransactionStep::execute_checked(
                self.group_insert(command, &profile, &owner),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                self.profile_insert(
                    command,
                    &profile,
                    &owner,
                    &profile_metadata_json,
                    persistence.timestamps,
                ),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                self.receipt_insert(command, &receipt_id),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                self.member_insert(command, &owner, persistence.timestamps),
                DbCountExpectation::exactly(1),
            ),
        ];
        let mut domain_steps = vec![group_step, profile_step, member_step];
        if let Some(owner_email) = persistence.owner_email {
            domain_steps.push(steps.len());
            steps.push(DbTransactionStep::execute_checked(
                self.owner_identity_insert(command, &owner, owner_email, persistence.timestamps),
                DbCountExpectation::exactly(1),
            ));
        }
        domain_steps.push(steps.len());
        steps.push(DbTransactionStep::execute_checked(
            self.participant_insert(&profile, &owner),
            DbCountExpectation::exactly(1),
        ));
        domain_steps.push(steps.len());
        steps.push(DbTransactionStep::execute_checked(
            self.authority_insert(command),
            DbCountExpectation::exactly(1),
        ));
        if let Some(bootstrap) = persistence.autonomy_bootstrap {
            domain_steps.push(steps.len());
            steps.push(DbTransactionStep::execute_checked(
                self.autonomy_bootstrap_insert(command, &bootstrap),
                DbCountExpectation::exactly(1),
            ));
        }
        steps.extend([
            DbTransactionStep::execute_checked(
                self.outbox_insert(
                    command,
                    &outbox_id,
                    event.event_type(),
                    &payload_json,
                    &metadata_json,
                ),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                self.receipt_finalize(command, &receipt_id, &response_json),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::query_checked(
                self.receipt_lookup(command),
                DbCountExpectation::exactly(1),
            ),
        ]);

        Ok(WorkspaceCreationPlan {
            receipt_id,
            outbox_id,
            receipt_lookup,
            steps,
            access_step,
            absence_step,
            receipt_insert_step,
            domain_steps,
        })
    }

    fn project_access_check(
        self,
        command: &WorkspaceMutationCommand,
        owner: &WorkspaceCreateOwner,
    ) -> DbStatement {
        if command.actor().is_superuser() {
            return DbStatementBuilder::new(self.flavor)
                .push_static("SELECT ")
                .bind(owner.user_id().as_str())
                .push_static(" AS user_id")
                .build();
        }
        DbStatementBuilder::new(self.flavor)
            .push_static("SELECT user_id FROM project_principal_memberships WHERE tenant_id = ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(command.scope().project_id().as_str())
            .push_static(" AND user_id = ")
            .bind(owner.user_id().as_str())
            .push_static(" AND participant_actor_id = ")
            .bind(owner.participant_actor_id().as_str())
            .push_static(" AND is_active = ")
            .bind(true)
            .build()
    }

    fn workspace_absence_check(
        self,
        command: &WorkspaceMutationCommand,
        profile: &WorkspaceCreateProfile,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("SELECT workspace_id FROM workspace_profiles WHERE workspace_id = ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(" OR group_id = ")
            .bind(profile.group_id().as_str())
            .build()
    }

    fn group_insert(
        self,
        command: &WorkspaceMutationCommand,
        profile: &WorkspaceCreateProfile,
        owner: &WorkspaceCreateOwner,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_groups (group_id, label, status, driver_bot, originator, env, context, created_by, visibility) VALUES (",
            )
            .bind(profile.group_id().as_str())
            .push_static(", ")
            .bind(profile.name().as_str())
            .push_static(", 'active', ")
            .bind(owner.participant_actor_id().as_str())
            .push_static(", ")
            .bind(owner.participant_actor_id().as_str())
            .push_static(", ")
            .bind(profile.bcs_environment().as_str())
            .push_static(", ")
            .bind(profile.description())
            .push_static(", ")
            .bind(command.actor().actor_id().as_str())
            .push_static(", 'private')")
            .build()
    }

    fn profile_insert(
        self,
        command: &WorkspaceMutationCommand,
        profile: &WorkspaceCreateProfile,
        owner: &WorkspaceCreateOwner,
        metadata_json: &str,
        timestamps: Option<&WorkspaceCreationTimestamps>,
    ) -> DbStatement {
        let mut statement = DbStatementBuilder::new(self.flavor);
        statement = if timestamps.is_some() {
            statement.push_static(
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, description, created_by, metadata_json, created_at, updated_at) VALUES (",
            )
        } else {
            statement.push_static(
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, description, created_by, metadata_json) VALUES (",
            )
        };
        let mut statement = statement
            .bind(command.scope().workspace_id().as_str())
            .push_static(", ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(", ")
            .bind(command.scope().project_id().as_str())
            .push_static(", ")
            .bind(profile.group_id().as_str())
            .push_static(", ")
            .bind(profile.name().as_str())
            .push_static(", ")
            .bind(profile.description())
            .push_static(", ")
            .bind(owner.user_id().as_str())
            .push_static(", ")
            .bind(metadata_json);
        if let Some(timestamps) = timestamps {
            statement = statement
                .push_static(", ")
                .bind(timestamps.created_at())
                .push_static(", ")
                .bind(timestamps.updated_at());
        }
        statement.push_static(")").build()
    }

    fn member_insert(
        self,
        command: &WorkspaceMutationCommand,
        owner: &WorkspaceCreateOwner,
        timestamps: Option<&WorkspaceCreationTimestamps>,
    ) -> DbStatement {
        let mut statement = DbStatementBuilder::new(self.flavor);
        statement = if timestamps.is_some() {
            statement.push_static(
                "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role, invited_by, created_at, updated_at) VALUES (",
            )
        } else {
            statement.push_static(
                "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role, invited_by) VALUES (",
            )
        };
        let mut statement = statement
            .bind(owner.member_id().as_str())
            .push_static(", ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(", ")
            .bind(command.scope().project_id().as_str())
            .push_static(", ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(", ")
            .bind(owner.user_id().as_str())
            .push_static(", ")
            .bind(owner.participant_actor_id().as_str())
            .push_static(", 'owner', ")
            .bind(owner.user_id().as_str());
        if let Some(timestamps) = timestamps {
            statement = statement
                .push_static(", ")
                .bind(timestamps.created_at())
                .push_static(", ")
                .bind(timestamps.updated_at());
        }
        statement.push_static(")").build()
    }

    fn participant_insert(
        self,
        profile: &WorkspaceCreateProfile,
        owner: &WorkspaceCreateOwner,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_group_participants (group_id, bot_uuid, role, env, actor_kind, mode) VALUES (",
            )
            .bind(profile.group_id().as_str())
            .push_static(", ")
            .bind(owner.participant_actor_id().as_str())
            .push_static(", 'owner', ")
            .bind(profile.bcs_environment().as_str())
            .push_static(", 'human', 'auto')")
            .build()
    }

    fn autonomy_bootstrap_insert(
        self,
        command: &WorkspaceMutationCommand,
        bootstrap: &WorkspaceAutonomyBootstrapCreation<'_>,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_autonomy_bootstrap_outbox (bootstrap_id, tenant_id, \
                 project_id, workspace_id, actor_id, objective_title, objective_description, \
                 created_at_ms) VALUES (",
            )
            .bind(deterministic_creation_id("autonomy-bootstrap", command))
            .push_static(", ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(", ")
            .bind(command.scope().project_id().as_str())
            .push_static(", ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(", ")
            .bind(command.actor().actor_id().as_str())
            .push_static(", ")
            .bind(bootstrap.objective_title)
            .push_static(", ")
            .bind(bootstrap.objective_description)
            .push_static(", ")
            .bind(bootstrap.created_at_ms)
            .push_static(")")
            .build()
    }

    fn owner_identity_insert(
        self,
        command: &WorkspaceMutationCommand,
        owner: &WorkspaceCreateOwner,
        owner_email: &str,
        timestamps: Option<&WorkspaceCreationTimestamps>,
    ) -> DbStatement {
        let mut statement = DbStatementBuilder::new(self.flavor).push_static(
            "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, participant_actor_id, email, display_name, is_active, identity_authority, source_created_at, source_updated_at) VALUES (",
        );
        statement = statement
            .bind(command.scope().tenant_id().as_str())
            .push_static(", ")
            .bind(command.scope().project_id().as_str())
            .push_static(", ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(", ")
            .bind(owner.user_id().as_str())
            .push_static(", ")
            .bind(owner.participant_actor_id().as_str())
            .push_static(", ")
            .bind(owner_email)
            .push_static(", NULL, ")
            .bind(true)
            .push_static(", 'memstack', ");
        if let Some(timestamps) = timestamps {
            statement = statement
                .bind(timestamps.created_at())
                .push_static(", ")
                .bind(timestamps.updated_at());
        } else {
            statement = statement.push_static("CURRENT_TIMESTAMP, CURRENT_TIMESTAMP");
        }
        statement.push_static(")").build()
    }

    fn authority_insert(self, command: &WorkspaceMutationCommand) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES (",
            )
            .bind(command.scope().workspace_id().as_str())
            .push_static(", ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(", ")
            .bind(command.scope().project_id().as_str())
            .push_static(", ")
            .bind(INITIAL_COMMITTED_REVISION)
            .push_static(")")
            .build()
    }

    fn receipt_lookup(self, command: &WorkspaceMutationCommand) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT receipt_id, request_hash, committed_revision, response_json FROM workspace_mutation_receipts WHERE tenant_id = ",
            )
            .bind(command.scope().tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(command.scope().project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(" AND actor_id = ")
            .bind(command.actor().actor_id().as_str())
            .push_static(" AND idempotency_key = ")
            .bind(command.idempotency_key().as_str())
            .build()
    }

    fn receipt_insert(self, command: &WorkspaceMutationCommand, receipt_id: &str) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_mutation_receipts (receipt_id, tenant_id, project_id, workspace_id, actor_id, contract_version, surface, action, idempotency_key, request_hash, expected_revision) VALUES (",
            )
            .bind(receipt_id)
            .push_static(", ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(", ")
            .bind(command.scope().project_id().as_str())
            .push_static(", ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(", ")
            .bind(command.actor().actor_id().as_str())
            .push_static(", ")
            .bind(command.contract_version().as_str())
            .push_static(", ")
            .bind(command.action().surface().as_str())
            .push_static(", ")
            .bind(command.action().as_str())
            .push_static(", ")
            .bind(command.idempotency_key().as_str())
            .push_static(", ")
            .bind(command.request_hash().as_str())
            .push_static(", 0)")
            .build()
    }

    fn outbox_insert(
        self,
        command: &WorkspaceMutationCommand,
        outbox_id: &str,
        event_type: &str,
        payload_json: &str,
        metadata_json: &str,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, correlation_id, idempotency_key) VALUES (",
            )
            .bind(outbox_id)
            .push_static(", ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(", ")
            .bind(command.scope().project_id().as_str())
            .push_static(", ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(", 'workspace', ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(", ")
            .bind(event_type)
            .push_static(", ")
            .bind(format!("workspace:{}", command.scope().workspace_id().as_str()))
            .push_static(", ")
            .bind(INITIAL_COMMITTED_REVISION)
            .push_static(", ")
            .bind(payload_json)
            .push_static(", ")
            .bind(metadata_json)
            .push_static(", ")
            .bind(outbox_id)
            .push_static(", ")
            .bind(command.idempotency_key().as_str())
            .push_static(")")
            .build()
    }

    fn receipt_finalize(
        self,
        command: &WorkspaceMutationCommand,
        receipt_id: &str,
        response_json: &str,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE workspace_mutation_receipts SET committed_revision = ")
            .bind(INITIAL_COMMITTED_REVISION)
            .push_static(", response_json = ")
            .bind(response_json)
            .push_static(", committed_at = ")
            .push_static(self.flavor.now())
            .push_static(" WHERE receipt_id = ")
            .bind(receipt_id)
            .push_static(" AND tenant_id = ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(command.scope().project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(" AND request_hash = ")
            .bind(command.request_hash().as_str())
            .push_static(" AND committed_revision IS NULL")
            .build()
    }
}

fn validate_owner_event_payload(
    command: &WorkspaceMutationCommand,
    owner: &WorkspaceCreateOwner,
    payload: &Value,
) -> Result<(), WorkspaceCreationPlanError> {
    let Some(object) = payload.as_object() else {
        return Err(WorkspaceCreationPlanError::OwnerEventMismatch);
    };
    let Some(member) = object.get("member").and_then(Value::as_object) else {
        return Err(WorkspaceCreationPlanError::OwnerEventMismatch);
    };
    let matches_owner = object.get("workspace_id").and_then(Value::as_str)
        == Some(command.scope().workspace_id().as_str())
        && object.get("member_id").and_then(Value::as_str) == Some(owner.member_id().as_str())
        && object.get("user_id").and_then(Value::as_str) == Some(owner.user_id().as_str())
        && object.get("role").and_then(Value::as_str) == Some("owner")
        && object.get("invited_by").and_then(Value::as_str) == Some(owner.user_id().as_str())
        && member.get("id").and_then(Value::as_str) == Some(owner.member_id().as_str())
        && member.get("workspace_id").and_then(Value::as_str)
            == Some(command.scope().workspace_id().as_str())
        && member.get("user_id").and_then(Value::as_str) == Some(owner.user_id().as_str())
        && member.get("role").and_then(Value::as_str) == Some("owner")
        && member.get("invited_by").and_then(Value::as_str) == Some(owner.user_id().as_str());
    if matches_owner {
        Ok(())
    } else {
        Err(WorkspaceCreationPlanError::OwnerEventMismatch)
    }
}

fn deterministic_creation_id(namespace: &str, command: &WorkspaceMutationCommand) -> String {
    let mut digest = Sha256::new();
    for part in [
        namespace,
        command.scope().tenant_id().as_str(),
        command.scope().project_id().as_str(),
        command.scope().workspace_id().as_str(),
        command.actor().actor_id().as_str(),
        command.contract_version().as_str(),
        command.action().as_str(),
        command.idempotency_key().as_str(),
        command.request_hash().as_str(),
    ] {
        let part_len = u64::try_from(part.len()).map_or(u64::MAX, |length| length);
        digest.update(part_len.to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("{}-{}", namespace, hex::encode(digest.finalize()))
}
