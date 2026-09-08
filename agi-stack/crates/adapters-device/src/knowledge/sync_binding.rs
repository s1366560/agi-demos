//! Atomic persistence for an already authenticated and enrolled remote target.
//! Network verification belongs to the caller; this adapter enforces immutable
//! scope/origin association and never migrates existing outbox identities.
use agistack_core::knowledge::sync::push::KnowledgeSyncTarget;
use agistack_core::knowledge::sync::KnowledgeSyncStatus;
use rusqlite::TransactionBehavior;

use super::*;

impl SqliteKnowledgeRepository {
    /// Data transport cannot implicitly claim a previously unbound cloud origin.
    pub fn require_verified_sync_target_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
    ) -> KnowledgeResult<()> {
        let conn = self.conn.lock().map_err(storage)?;
        push::check_target(&conn, scope, target, false)
    }

    /// The synchronous caller holds its local/cloud identity and generation
    /// fences through commit. The callback rechecks time after acquiring storage
    /// and immediately before commit, without reacquiring any outer locks.
    pub fn bind_verified_sync_target_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        check_current: &dyn Fn() -> KnowledgeResult<()>,
    ) -> KnowledgeResult<KnowledgeSyncStatus> {
        validate(scope, "verified sync binding")?;
        for identifier in [
            &target.authority,
            &target.link.remote_tenant_id,
            &target.link.remote_project_id,
            &target.link.remote_actor_id,
        ] {
            sync::validate_identifier(identifier)?;
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        check_current()?;
        let previous = sync::status(&tx, scope)?;
        match previous.link {
            Some(link) if link != target.link => return Err(KnowledgeError::Conflict),
            Some(_) => {}
            None => {
                tx.execute(
                    "INSERT INTO knowledge_sync_links(tenant_id,project_id,remote_tenant_id,remote_project_id,remote_actor_id) VALUES(?1,?2,?3,?4,?5)",
                    params![scope.tenant_id, scope.project_id, target.link.remote_tenant_id, target.link.remote_project_id, target.link.remote_actor_id],
                ).map_err(storage)?;
            }
        }
        push::check_target(&tx, scope, target, true)?;
        let result = sync::status(&tx, scope)?;
        check_current()?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }
}
