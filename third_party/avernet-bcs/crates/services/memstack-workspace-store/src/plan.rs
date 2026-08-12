//! Dialect-aware Workspace mutation transaction plans.

use std::ops::Range;

use bcs_db_api::{
    DbCountExpectation, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStep,
};
use memstack_workspace_service_api::{WorkspaceMutationAction, WorkspaceMutationCommand};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{LegacyWorkspaceEvent, LegacyWorkspaceEventError};

const MAX_SIGNED_REVISION: u64 = i64::MAX as u64;

/// A domain write that must affect the declared number of rows.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceDomainMutation {
    statement: DbStatement,
    expected_affected_rows: DbCountExpectation,
}

impl WorkspaceDomainMutation {
    /// Construct a checked domain mutation.
    #[must_use]
    pub const fn new(statement: DbStatement, expected_affected_rows: DbCountExpectation) -> Self {
        Self {
            statement,
            expected_affected_rows,
        }
    }

    fn into_step(self) -> DbTransactionStep {
        DbTransactionStep::execute_checked(self.statement, self.expected_affected_rows)
    }
}

/// Invalid transaction-plan input.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceMutationPlanError {
    #[error("expected Workspace revision exceeds the signed database range")]
    RevisionOutOfRange,

    #[error("Workspace mutation requires at least one checked domain write")]
    EmptyDomainMutation,

    #[error("create_workspace requires the separate new-Workspace transaction contract")]
    CreateRequiresNewWorkspacePlan,

    #[error("Workspace mutation plans currently support only PostgreSQL and SQLite")]
    UnsupportedSqlFlavor,

    #[error(transparent)]
    LegacyEvent(#[from] LegacyWorkspaceEventError),
}

/// Fully ordered first-attempt transaction for an existing Workspace.
#[derive(Debug, Clone)]
pub struct WorkspaceMutationPlan {
    receipt_id: String,
    outbox_id: String,
    committed_revision: u64,
    receipt_lookup: DbStatement,
    steps: Vec<DbTransactionStep>,
    access_step: usize,
    receipt_insert_step: usize,
    revision_check_step: usize,
    domain_steps: Range<usize>,
    authority_cas_step: usize,
}

impl WorkspaceMutationPlan {
    /// Deterministic mutation receipt identifier.
    #[must_use]
    pub fn receipt_id(&self) -> &str {
        &self.receipt_id
    }

    /// Deterministic durable outbox identifier.
    #[must_use]
    pub fn outbox_id(&self) -> &str {
        &self.outbox_id
    }

    /// Revision committed when the transaction succeeds.
    #[must_use]
    pub const fn committed_revision(&self) -> u64 {
        self.committed_revision
    }

    /// Read-only receipt lookup used before execution and after a race.
    #[must_use]
    pub const fn receipt_lookup(&self) -> &DbStatement {
        &self.receipt_lookup
    }

    /// Ordered transaction steps for inspection and contract tests.
    #[must_use]
    pub fn steps(&self) -> &[DbTransactionStep] {
        &self.steps
    }

    /// Consume the plan into executable transaction steps.
    #[must_use]
    pub fn into_steps(self) -> Vec<DbTransactionStep> {
        self.steps
    }

    pub(crate) const fn access_step(&self) -> usize {
        self.access_step
    }

    pub(crate) const fn receipt_insert_step(&self) -> usize {
        self.receipt_insert_step
    }

    pub(crate) const fn revision_check_step(&self) -> usize {
        self.revision_check_step
    }

    pub(crate) fn is_domain_step(&self, step: usize) -> bool {
        self.domain_steps.contains(&step)
    }

    pub(crate) const fn authority_cas_step(&self) -> usize {
        self.authority_cas_step
    }
}

/// Builds the same transaction contract for PostgreSQL and SQLite.
#[derive(Debug, Clone, Copy)]
pub struct WorkspaceMutationPlanner {
    flavor: DbSqlFlavor,
}

impl WorkspaceMutationPlanner {
    /// Select the SQL dialect used for placeholders and lock clauses.
    #[must_use]
    pub const fn new(flavor: DbSqlFlavor) -> Self {
        Self { flavor }
    }

    /// Build the read-only idempotency lookup used before destructive replay preparation.
    #[must_use]
    pub fn replay_lookup(self, command: &WorkspaceMutationCommand) -> DbStatement {
        self.receipt_lookup(command)
    }

    /// Build the first-attempt transaction for an existing Workspace.
    ///
    /// The ordered contract is access check, checked receipt reservation,
    /// revision check, checked domain writes, authority CAS, durable outbox,
    /// receipt finalization, and final receipt query.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceMutationPlanError`] for an unsupported revision,
    /// an empty domain write set, or an invalid legacy event payload.
    pub fn plan_existing(
        self,
        command: &WorkspaceMutationCommand,
        domain_mutations: Vec<WorkspaceDomainMutation>,
        response: Value,
        event_payload: Value,
    ) -> Result<WorkspaceMutationPlan, WorkspaceMutationPlanError> {
        if domain_mutations.is_empty() {
            return Err(WorkspaceMutationPlanError::EmptyDomainMutation);
        }
        if command.action() == WorkspaceMutationAction::CreateWorkspace {
            return Err(WorkspaceMutationPlanError::CreateRequiresNewWorkspacePlan);
        }
        if self.flavor == DbSqlFlavor::Mysql {
            return Err(WorkspaceMutationPlanError::UnsupportedSqlFlavor);
        }
        let expected_revision = command.expected_revision().get();
        if expected_revision >= MAX_SIGNED_REVISION {
            return Err(WorkspaceMutationPlanError::RevisionOutOfRange);
        }
        let committed_revision = expected_revision + 1;
        let event = LegacyWorkspaceEvent::for_action(
            command.action(),
            command.scope().workspace_id().as_str(),
            event_payload,
        )?;
        let receipt_id = deterministic_id("receipt", command);
        let outbox_id = deterministic_id("outbox", command);
        let response_json = response.to_string();
        let payload_json = event.payload().to_string();
        let metadata_json = json!({
            "action": command.receipt_action(),
            "contract_version": command.contract_version().as_str(),
            "receipt_id": &receipt_id,
            "request_hash": command.request_hash().as_str(),
        })
        .to_string();
        let receipt_lookup = self.receipt_lookup(command);

        let access_step = 0;
        let receipt_insert_step = 1;
        let revision_check_step = 2;
        let domain_start = 3;
        let domain_end = domain_start + domain_mutations.len();
        let authority_cas_step = domain_end;
        let mut steps = Vec::with_capacity(domain_mutations.len() + 7);
        steps.push(DbTransactionStep::query_checked(
            self.access_check(command),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::execute_checked(
            self.receipt_insert(command, &receipt_id),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::query_checked(
            self.revision_check(command),
            DbCountExpectation::exactly(1),
        ));
        steps.extend(
            domain_mutations
                .into_iter()
                .map(WorkspaceDomainMutation::into_step),
        );
        steps.push(DbTransactionStep::execute_checked(
            self.authority_cas(command),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::execute_checked(
            self.outbox_insert(
                command,
                &outbox_id,
                event.event_type(),
                committed_revision,
                &payload_json,
                &metadata_json,
            ),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::execute_checked(
            self.receipt_finalize(command, &receipt_id, committed_revision, &response_json),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::query_checked(
            self.receipt_lookup(command),
            DbCountExpectation::exactly(1),
        ));

        Ok(WorkspaceMutationPlan {
            receipt_id,
            outbox_id,
            committed_revision,
            receipt_lookup,
            steps,
            access_step,
            receipt_insert_step,
            revision_check_step,
            domain_steps: domain_start..domain_end,
            authority_cas_step,
        })
    }

    fn access_check(self, command: &WorkspaceMutationCommand) -> DbStatement {
        let mut builder = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT p.workspace_id FROM workspace_profiles p WHERE p.tenant_id = ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(" AND p.project_id = ")
            .bind(command.scope().project_id().as_str())
            .push_static(" AND p.workspace_id = ")
            .bind(command.scope().workspace_id().as_str());
        builder = builder.push_static(" AND p.deleted_at IS NULL");
        if !command.actor().is_superuser() {
            if command.action() == WorkspaceMutationAction::UpdateAgentPolicy {
                return builder
                    .push_static(" AND (p.created_by = ")
                    .bind(command.actor().actor_id().as_str())
                    .push_static(
                        " OR EXISTS (SELECT 1 FROM workspace_members m WHERE m.tenant_id = \
                         p.tenant_id AND m.project_id = p.project_id AND m.workspace_id = \
                         p.workspace_id AND m.user_id = ",
                    )
                    .bind(command.actor().actor_id().as_str())
                    .push_static(
                        " AND m.role IN ('owner', 'editor')) OR EXISTS (SELECT 1 FROM \
                         project_principal_memberships pm WHERE pm.tenant_id = p.tenant_id AND \
                         pm.project_id = p.project_id AND pm.user_id = ",
                    )
                    .bind(command.actor().actor_id().as_str())
                    .push_static(" AND pm.is_active = TRUE AND pm.role IN ('owner', 'admin')))")
                    .build();
            }
            let permitted_roles = match command.action() {
                WorkspaceMutationAction::DeleteWorkspace
                | WorkspaceMutationAction::AddMember
                | WorkspaceMutationAction::UpdateMemberRole
                | WorkspaceMutationAction::RemoveMember => " AND m.role = 'owner')",
                WorkspaceMutationAction::UpdateWorkspace
                | WorkspaceMutationAction::BindAgent
                | WorkspaceMutationAction::UpdateAgentBinding
                | WorkspaceMutationAction::UnbindAgent => " AND m.role IN ('owner', 'editor'))",
                WorkspaceMutationAction::UpdateAgentPolicy => " AND m.role IN ('owner', 'editor'))",
                WorkspaceMutationAction::CreateWorkspace => " AND 1 = 0)",
            };
            builder = builder
                .push_static(
                    " AND EXISTS (SELECT 1 FROM workspace_members m WHERE m.tenant_id = p.tenant_id AND m.project_id = p.project_id AND m.workspace_id = p.workspace_id AND m.user_id = ",
                )
                .bind(command.actor().actor_id().as_str())
                .push_static(permitted_roles);
        }
        builder.build()
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
        let builder = DbStatementBuilder::new(self.flavor)
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
            .bind(command.receipt_surface())
            .push_static(", ")
            .bind(command.receipt_action())
            .push_static(", ")
            .bind(command.idempotency_key().as_str())
            .push_static(", ")
            .bind(command.request_hash().as_str())
            .push_static(", ")
            .bind(command.expected_revision().get())
            .push_static(")");
        match self.flavor {
            DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
                .push_static(" ON CONFLICT(workspace_id, actor_id, idempotency_key) DO NOTHING")
                .build(),
            DbSqlFlavor::Mysql => builder
                .push_static(" ON DUPLICATE KEY UPDATE workspace_id=workspace_id")
                .build(),
        }
    }

    fn revision_check(self, command: &WorkspaceMutationCommand) -> DbStatement {
        let builder = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(command.scope().project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(" AND revision = ")
            .bind(command.expected_revision().get());
        match self.flavor {
            DbSqlFlavor::Postgres | DbSqlFlavor::Mysql => {
                builder.push_static(" FOR UPDATE").build()
            }
            DbSqlFlavor::Sqlite => builder.build(),
        }
    }

    fn authority_cas(self, command: &WorkspaceMutationCommand) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE workspace_authorities SET revision = revision + 1, updated_at = ")
            .push_static(self.flavor.now())
            .push_static(" WHERE tenant_id = ")
            .bind(command.scope().tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(command.scope().project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(command.scope().workspace_id().as_str())
            .push_static(" AND revision = ")
            .bind(command.expected_revision().get())
            .build()
    }

    #[allow(clippy::too_many_arguments)]
    fn outbox_insert(
        self,
        command: &WorkspaceMutationCommand,
        outbox_id: &str,
        event_type: &str,
        committed_revision: u64,
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
            .bind(committed_revision)
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
        committed_revision: u64,
        response_json: &str,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE workspace_mutation_receipts SET committed_revision = ")
            .bind(committed_revision)
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

fn deterministic_id(namespace: &str, command: &WorkspaceMutationCommand) -> String {
    let mut digest = Sha256::new();
    for part in [
        namespace,
        command.scope().tenant_id().as_str(),
        command.scope().project_id().as_str(),
        command.scope().workspace_id().as_str(),
        command.actor().actor_id().as_str(),
        command.contract_version().as_str(),
        command.receipt_surface(),
        command.receipt_action(),
        command.idempotency_key().as_str(),
        command.request_hash().as_str(),
    ] {
        let part_len = u64::try_from(part.len()).map_or(u64::MAX, |length| length);
        digest.update(part_len.to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("{}-{}", namespace, hex::encode(digest.finalize()))
}
