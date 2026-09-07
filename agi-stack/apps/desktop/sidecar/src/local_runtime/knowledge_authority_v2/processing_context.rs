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
    if !operation.writable
        || operation.actor_id != authenticated.user.user_id
        || operation.scope.tenant_id != authenticated.workspace.tenant_id
        || operation.scope.project_id != authenticated.workspace.project_id
    {
        return Err(KnowledgeAuthorityErrorV2::Forbidden);
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
           AND m.role IN ('owner','admin','member','contributor')",
        params![authenticated.session_id,authenticated.user.user_id,chrono::Utc::now().timestamp_millis(),
            operation.scope.tenant_id,operation.scope.project_id,authenticated.workspace.revision,expected_updated],
        |row|row.get(0),
    ).optional().map_err(|_|KnowledgeAuthorityErrorV2::Forbidden)?;
    let Some(expires_at_ms) = expires_at_ms else {
        return Err(KnowledgeAuthorityErrorV2::Forbidden);
    };
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
