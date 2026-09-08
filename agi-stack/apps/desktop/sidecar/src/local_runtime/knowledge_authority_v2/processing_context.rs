//! Serialize final processing admission with local session/membership changes.

use rusqlite::{params, OptionalExtension};
use std::cell::Cell;

use super::*;
use crate::local_runtime::LocalRuntimeState;

pub(super) fn with_current<T>(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    action: impl FnOnce(
        &dyn Fn() -> agistack_core::knowledge::KnowledgeResult<i64>,
    ) -> agistack_core::knowledge::KnowledgeResult<T>,
) -> Result<T, KnowledgeAuthorityErrorV2> {
    with_access(operation, state, authenticated, true, |_| Ok(()), action)
}

pub(super) fn with_read_current<T>(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    action: impl FnOnce(
        &dyn Fn() -> agistack_core::knowledge::KnowledgeResult<i64>,
    ) -> agistack_core::knowledge::KnowledgeResult<T>,
) -> Result<T, KnowledgeAuthorityErrorV2> {
    with_read_current_checked(operation, state, authenticated, false, |_| Ok(()), action)
}

/// Extra durable configuration validation executes under the existing auth
/// connection lock. Callers may hold the Provider runtime lock outside this
/// wrapper, but must never reacquire auth or runtime locks from `check`.
pub(super) fn with_read_current_checked<T>(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    write: bool,
    check: impl FnOnce(&rusqlite::Connection) -> agistack_core::knowledge::KnowledgeResult<()>,
    action: impl FnOnce(
        &dyn Fn() -> agistack_core::knowledge::KnowledgeResult<i64>,
    ) -> agistack_core::knowledge::KnowledgeResult<T>,
) -> Result<T, KnowledgeAuthorityErrorV2> {
    ensure_current_generation(operation, state)?;
    let mut generation_error = None;
    let result = with_access(operation, state, authenticated, write, check, |clock| {
        if write {
            // Auth precedes generation, matching read finalization. Hold the
            // generation read lock until the storage transaction has committed;
            // detecting retirement afterwards could not undo a published vector.
            return match state
                .platform_plugin_authority_v2
                .with_current_generation(operation._lease.descriptor(), || action(clock))
            {
                Some(result) => result,
                None => {
                    generation_error = Some(KnowledgeAuthorityErrorV2::GenerationMismatch);
                    Err(KnowledgeError::Conflict)
                }
            };
        }
        let value = action(clock)?;
        if let Err(error) = ensure_current_generation(operation, state) {
            generation_error = Some(error);
            return Err(KnowledgeError::Conflict);
        }
        // Generation acquisition may wait; keep auth stable and recheck its
        // time deadline after that final generation check too.
        clock()?;
        Ok(value)
    });
    match generation_error {
        Some(error) => Err(error),
        None => result,
    }
}

fn ensure_current_generation(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
) -> Result<(), KnowledgeAuthorityErrorV2> {
    let generation = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .map_err(|_| KnowledgeAuthorityErrorV2::GenerationMismatch)?;
    if generation.descriptor() != operation._lease.descriptor() {
        return Err(KnowledgeAuthorityErrorV2::GenerationMismatch);
    }
    Ok(())
}

fn with_access<T>(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    write: bool,
    check: impl FnOnce(&rusqlite::Connection) -> agistack_core::knowledge::KnowledgeResult<()>,
    action: impl FnOnce(
        &dyn Fn() -> agistack_core::knowledge::KnowledgeResult<i64>,
    ) -> agistack_core::knowledge::KnowledgeResult<T>,
) -> Result<T, KnowledgeAuthorityErrorV2> {
    if (write && !operation.writable)
        || operation.actor_id != authenticated.user.user_id
        || operation.scope.tenant_id != authenticated.workspace.tenant_id
        || operation.scope.project_id != authenticated.workspace.project_id
    {
        return Err(KnowledgeAuthorityErrorV2::Forbidden);
    }
    if operation.admitted_session_id != authenticated.session_id
        || operation.admitted_context_revision != authenticated.workspace.revision
        || operation.admitted_context_updated_at != authenticated.workspace.updated_at
    {
        return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
    }
    operation.authority.repository()?;
    let connection = state
        .session_store
        .connection()
        .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?;
    let expected_updated =
        chrono::DateTime::parse_from_rfc3339(&authenticated.workspace.updated_at)
            .map_err(|_| KnowledgeAuthorityErrorV2::ScopeMismatch)?
            .timestamp_millis();
    let expires_at_ms: Option<i64> = connection.query_row(
        "SELECT s.expires_at_ms FROM desktop_user_sessions s
         JOIN desktop_users u ON u.id=s.user_id AND u.status='active'
         JOIN desktop_workspace_contexts c ON c.user_id=u.id
         JOIN desktop_tenants t ON t.id=c.tenant_id AND t.status='active'
         JOIN desktop_projects p ON p.id=c.project_id AND p.tenant_id=t.id AND p.status='active'
         JOIN desktop_tenant_memberships m ON m.user_id=u.id AND m.tenant_id=t.id AND m.status='active'
         WHERE s.id=?1 AND s.user_id=?2 AND s.status='active' AND s.expires_at_ms>?3
           AND c.tenant_id=?4 AND c.project_id=?5 AND c.revision=?6 AND c.updated_at_ms=?7
           AND (m.role IN ('owner','admin','member','contributor') OR (?8=0 AND m.role='viewer'))",
        params![authenticated.session_id,authenticated.user.user_id,chrono::Utc::now().timestamp_millis(),
            operation.scope.tenant_id,operation.scope.project_id,authenticated.workspace.revision,expected_updated,write],
        |row|row.get(0),
    ).optional().map_err(|_|KnowledgeAuthorityErrorV2::Forbidden)?;
    let Some(expires_at_ms) = expires_at_ms else {
        return Err(KnowledgeAuthorityErrorV2::Forbidden);
    };
    check(&connection)?;
    // Status, membership and context cannot change while this outer auth lock
    // is held. Time still advances while waiting on knowledge storage, so its
    // transaction invokes this clock after lock acquisition and before commit.
    // The callback never takes the auth mutex again (no reverse lock order).
    let admission_expired = Cell::new(false);
    let clock = || {
        let current = chrono::Utc::now().timestamp_millis();
        if current >= expires_at_ms {
            admission_expired.set(true);
            return Err(KnowledgeError::Conflict);
        }
        Ok(current)
    };
    let result = action(&clock);
    if admission_expired.get() {
        return Err(KnowledgeAuthorityErrorV2::Forbidden);
    }
    Ok(result?)
}
