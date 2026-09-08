//! Native schema operations. Public RPC admission is separately release-gated.
//! Admission and every operation use live local authorization;
//! the storage callback never reacquires auth or generation locks.

use agistack_adapters_device::knowledge::project_schema::{
    ProjectSchemaHistoryPage, ProjectSchemaJournalPage, ProjectSchemaMutation,
    ProjectSchemaReceipt, ProjectSchemaStorageError, ProjectSchemaStorageResult,
};
use agistack_core::project_schema::ProjectSchemaDocument;

use super::*;
use crate::local_runtime::LocalRuntimeState;

#[path = "project_schema_actions_generated.rs"]
mod actions;
#[path = "project_schema_capabilities.rs"]
pub(super) mod capabilities;
#[path = "project_schema_contracts.rs"]
pub(super) mod contracts;
#[path = "project_schema_response.rs"]
pub(super) mod response;
pub(super) use actions::{SchemaAction, MAX_DOCUMENT_BYTES, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES};

// Schema errors have a dedicated HTTP mapping; Memory mapping stays unchanged.
#[allow(dead_code)]
#[derive(Debug, thiserror::Error)]
pub(super) enum ProjectSchemaOperationError {
    #[error(transparent)]
    Authority(#[from] KnowledgeAuthorityErrorV2),
    #[error(transparent)]
    Storage(#[from] ProjectSchemaStorageError),
}

type Result<T> = std::result::Result<T, ProjectSchemaOperationError>;

// The internal N1 entry remains available; RPC callers must bind a schema action.
#[allow(dead_code)]
pub(super) struct ProjectSchemaOperationV2 {
    operation: KnowledgeOperationV2,
    schema_action: Option<SchemaAction>,
}

#[allow(dead_code)]
impl ProjectSchemaOperationV2 {
    pub(super) fn admit(
        state: &LocalRuntimeState,
        lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
        authenticated: &AuthenticatedContext,
        requested: &KnowledgeOperationScopeV2,
    ) -> Result<Self> {
        Self::admit_checked(state, lease, authenticated, requested, None)
    }

    pub(super) fn admit_action(
        state: &LocalRuntimeState,
        lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
        authenticated: &AuthenticatedContext,
        requested: &KnowledgeOperationScopeV2,
        action: SchemaAction,
    ) -> Result<Self> {
        Self::admit_checked(state, lease, authenticated, requested, Some(action))
    }

    fn admit_checked(
        state: &LocalRuntimeState,
        lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
        authenticated: &AuthenticatedContext,
        requested: &KnowledgeOperationScopeV2,
        schema_action: Option<SchemaAction>,
    ) -> Result<Self> {
        // Validate live auth before admission can open knowledge storage. Hold
        // auth before generation, matching the operation/commit lock order.
        let connection = state
            .session_store
            .connection()
            .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?;
        let membership = processing_context::live_membership(&connection, authenticated, false)?;
        let descriptor = lease.descriptor().clone();
        let admitted =
            state
                .platform_plugin_authority_v2
                .with_current_generation(&descriptor, || {
                    if chrono::Utc::now().timestamp_millis() >= membership.expires_at_ms {
                        return Err(KnowledgeAuthorityErrorV2::Forbidden);
                    }
                    if let Some(action) = schema_action {
                        capabilities::authority(&lease, authenticated)?
                            .require_schema_action(&membership.role, action)?;
                    }
                    let operation = KnowledgeOperationV2::admit(lease, authenticated, requested)?;
                    if chrono::Utc::now().timestamp_millis() >= membership.expires_at_ms {
                        return Err(KnowledgeAuthorityErrorV2::Forbidden);
                    }
                    Ok(Self {
                        operation,
                        schema_action,
                    })
                });
        Ok(admitted.ok_or(KnowledgeAuthorityErrorV2::GenerationMismatch)??)
    }

    pub(super) fn read(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
    ) -> Result<Option<ProjectSchemaDocument>> {
        self.with_current(state, auth, SchemaAction::Read, |repo, current| {
            repo.read_project_schema_durable(&self.operation.scope, current)
        })
    }

    pub(super) fn bootstrap(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        command: &ProjectSchemaMutation,
    ) -> Result<ProjectSchemaReceipt> {
        self.with_current(state, auth, SchemaAction::Bootstrap, |repo, current| {
            repo.bootstrap_project_schema_durable(
                &self.operation.scope,
                &self.operation.actor_id,
                command,
                current,
            )
        })
    }

    pub(super) fn replace(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        command: &ProjectSchemaMutation,
    ) -> Result<ProjectSchemaReceipt> {
        self.with_current(state, auth, SchemaAction::Replace, |repo, current| {
            repo.replace_project_schema_durable(
                &self.operation.scope,
                &self.operation.actor_id,
                command,
                current,
            )
        })
    }

    pub(super) fn receipt(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        change_id: &str,
    ) -> Result<Option<ProjectSchemaReceipt>> {
        self.with_current(state, auth, SchemaAction::Receipt, |repo, current| {
            repo.project_schema_receipt_durable(
                &self.operation.scope,
                &self.operation.actor_id,
                change_id,
                current,
            )
        })
    }

    pub(super) fn history(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        after_revision: u32,
        limit: u32,
    ) -> Result<ProjectSchemaJournalPage> {
        self.with_current(state, auth, SchemaAction::History, |repo, current| {
            repo.project_schema_changes_durable(
                &self.operation.scope,
                after_revision,
                limit,
                current,
            )
        })
    }

    pub(super) fn bootstrap_checked(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        command: &ProjectSchemaMutation,
        check: &dyn Fn(&ProjectSchemaReceipt) -> ProjectSchemaStorageResult<()>,
    ) -> Result<ProjectSchemaReceipt> {
        self.with_current(state, auth, SchemaAction::Bootstrap, |repo, current| {
            repo.bootstrap_project_schema_checked_durable(
                &self.operation.scope,
                &self.operation.actor_id,
                command,
                current,
                check,
            )
        })
    }

    pub(super) fn replace_checked(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        command: &ProjectSchemaMutation,
        check: &dyn Fn(&ProjectSchemaReceipt) -> ProjectSchemaStorageResult<()>,
    ) -> Result<ProjectSchemaReceipt> {
        self.with_current(state, auth, SchemaAction::Replace, |repo, current| {
            repo.replace_project_schema_checked_durable(
                &self.operation.scope,
                &self.operation.actor_id,
                command,
                current,
                check,
            )
        })
    }

    pub(super) fn history_bounded(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        after_revision: u32,
        limit: u32,
        budget: &dyn Fn(&ProjectSchemaHistoryPage) -> ProjectSchemaStorageResult<usize>,
    ) -> Result<ProjectSchemaHistoryPage> {
        self.with_current(state, auth, SchemaAction::History, |repo, current| {
            repo.project_schema_history_bounded_durable(
                &self.operation.scope,
                after_revision,
                limit,
                budget,
                current,
            )
        })
    }

    fn with_current<T>(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        expected: SchemaAction,
        action: impl FnOnce(
            &SqliteKnowledgeRepository,
            &dyn Fn() -> ProjectSchemaStorageResult<()>,
        ) -> ProjectSchemaStorageResult<T>,
    ) -> Result<T> {
        if self.schema_action.is_some_and(|action| action != expected) {
            return Err(KnowledgeAuthorityErrorV2::Forbidden.into());
        }
        let schema_error = std::cell::RefCell::new(None);
        let result = processing_context::with_read_current_checked(
            &self.operation,
            state,
            auth,
            expected.is_write(),
            |connection| {
                if let Some(action) = self.schema_action {
                    let result =
                        processing_context::live_membership(connection, auth, action.is_write())
                            .and_then(|membership| {
                                self.operation
                                    .authority
                                    .require_schema_action(&membership.role, action)
                            });
                    if let Err(error) = result {
                        *schema_error.borrow_mut() = Some(error);
                        return Err(KnowledgeError::Conflict);
                    }
                }
                Ok(())
            },
            |clock| {
                // Storage invokes this inside its transaction after acquiring
                // its lock and immediately before commit, including replay.
                let current = || {
                    clock()
                        .map(|_| ())
                        .map_err(|_| ProjectSchemaStorageError::AdmissionChanged)
                };
                // Keep storage's typed error inside the outer auth result. The
                // auth wrapper takes precedence when a lease deadline expires.
                Ok(self
                    .operation
                    .authority
                    .repository()
                    .map_err(ProjectSchemaOperationError::from)
                    .and_then(|repository| {
                        action(&repository, &current).map_err(ProjectSchemaOperationError::from)
                    }))
            },
        );
        if let Some(error) = schema_error.into_inner() {
            return Err(error.into());
        }
        result?
    }

    // Tests can coordinate actual entry/final callbacks while retaining the
    // production auth/generation guards and real session deadline checks.
    #[cfg(test)]
    pub(super) fn with_current_for_test<T>(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        write: bool,
        action: impl FnOnce(
            &SqliteKnowledgeRepository,
            &dyn Fn() -> ProjectSchemaStorageResult<()>,
        ) -> ProjectSchemaStorageResult<T>,
    ) -> Result<T> {
        self.with_current(
            state,
            auth,
            if write {
                SchemaAction::Bootstrap
            } else {
                SchemaAction::Read
            },
            action,
        )
    }
}
