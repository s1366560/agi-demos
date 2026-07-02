//! Repository over Python-owned P2 invitation tables.
//!
//! This mirrors `SqlInvitationRepository` plus the tenant-admin access check used
//! by `routers/invitations.py`: tenant existence first, then membership/admin
//! role. It writes the existing `invitations` and `user_tenants` tables directly
//! so the strangler can flip invitation routes without data migration.

use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone)]
pub struct InvitationRecord {
    pub id: String,
    pub tenant_id: String,
    pub email: String,
    pub role: String,
    pub token: String,
    pub status: String,
    pub invited_by: String,
    pub accepted_by: Option<String>,
    pub expires_at: DateTime<Utc>,
    pub created_at: DateTime<Utc>,
    pub deleted_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TenantAdminStatus {
    Authorized,
    TenantNotFound,
    NotMember,
    NotAdmin,
}

type InvitationRow = (
    String,
    String,
    String,
    String,
    String,
    String,
    String,
    Option<String>,
    DateTime<Utc>,
    DateTime<Utc>,
    Option<DateTime<Utc>>,
);

fn to_record(row: InvitationRow) -> InvitationRecord {
    let (
        id,
        tenant_id,
        email,
        role,
        token,
        status,
        invited_by,
        accepted_by,
        expires_at,
        created_at,
        deleted_at,
    ) = row;
    InvitationRecord {
        id,
        tenant_id,
        email,
        role,
        token,
        status,
        invited_by,
        accepted_by,
        expires_at,
        created_at,
        deleted_at,
    }
}

const INVITATION_COLS: &str = "id, tenant_id, email, role, token, status, invited_by, \
     accepted_by, expires_at, created_at, deleted_at";

pub struct PgInvitationRepository {
    pool: PgPool,
}

impl PgInvitationRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn tenant_admin_status(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> CoreResult<TenantAdminStatus> {
        let tenant_exists =
            sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM tenants WHERE id = $1")
                .bind(tenant_id)
                .fetch_one(&self.pool)
                .await
                .map_err(|e| CoreError::Storage(e.to_string()))?
                .0
                > 0;
        if !tenant_exists {
            return Ok(TenantAdminStatus::TenantNotFound);
        }

        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?
        .map(|(is_superuser,)| is_superuser)
        .unwrap_or(false);
        if is_superuser {
            return Ok(TenantAdminStatus::Authorized);
        }

        let role = sqlx::query_as::<_, (String,)>(
            "SELECT role FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?
        .map(|(role,)| role);

        match role.as_deref() {
            Some("owner" | "admin") => Ok(TenantAdminStatus::Authorized),
            Some(_) => Ok(TenantAdminStatus::NotAdmin),
            None => Ok(TenantAdminStatus::NotMember),
        }
    }

    pub async fn create(&self, invitation: &InvitationRecord) -> CoreResult<InvitationRecord> {
        sqlx::query(
            "INSERT INTO invitations \
             (id, tenant_id, email, role, token, status, invited_by, accepted_by, expires_at, created_at, deleted_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
        )
        .bind(&invitation.id)
        .bind(&invitation.tenant_id)
        .bind(&invitation.email)
        .bind(&invitation.role)
        .bind(&invitation.token)
        .bind(&invitation.status)
        .bind(&invitation.invited_by)
        .bind(&invitation.accepted_by)
        .bind(invitation.expires_at)
        .bind(invitation.created_at)
        .bind(invitation.deleted_at)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(invitation.clone())
    }

    pub async fn find_by_id(&self, invitation_id: &str) -> CoreResult<Option<InvitationRecord>> {
        let row = sqlx::query_as::<_, InvitationRow>(&format!(
            "SELECT {INVITATION_COLS} FROM invitations WHERE id = $1"
        ))
        .bind(invitation_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.map(to_record))
    }

    pub async fn find_by_token(&self, token: &str) -> CoreResult<Option<InvitationRecord>> {
        let row = sqlx::query_as::<_, InvitationRow>(&format!(
            "SELECT {INVITATION_COLS} FROM invitations WHERE token = $1"
        ))
        .bind(token)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.map(to_record))
    }

    pub async fn find_pending_by_email_and_tenant(
        &self,
        email: &str,
        tenant_id: &str,
    ) -> CoreResult<Option<InvitationRecord>> {
        let row = sqlx::query_as::<_, InvitationRow>(&format!(
            "SELECT {INVITATION_COLS} FROM invitations \
             WHERE email = $1 AND tenant_id = $2 AND status = 'pending' AND deleted_at IS NULL"
        ))
        .bind(normalize_email(email))
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.map(to_record))
    }

    pub async fn list_pending_by_tenant(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<InvitationRecord>> {
        let rows = sqlx::query_as::<_, InvitationRow>(&format!(
            "SELECT {INVITATION_COLS} FROM invitations \
             WHERE tenant_id = $1 AND status = 'pending' AND deleted_at IS NULL \
             ORDER BY created_at DESC LIMIT $2 OFFSET $3"
        ))
        .bind(tenant_id)
        .bind(limit)
        .bind(offset)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(rows.into_iter().map(to_record).collect())
    }

    pub async fn count_pending_by_tenant(&self, tenant_id: &str) -> CoreResult<i64> {
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM invitations \
             WHERE tenant_id = $1 AND status = 'pending' AND deleted_at IS NULL",
        )
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.0)
    }

    pub async fn soft_delete(
        &self,
        invitation_id: &str,
        deleted_at: DateTime<Utc>,
    ) -> CoreResult<()> {
        sqlx::query("UPDATE invitations SET deleted_at = $2, status = 'cancelled' WHERE id = $1")
            .bind(invitation_id)
            .bind(deleted_at)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }

    pub async fn update_status(
        &self,
        invitation_id: &str,
        status: &str,
        accepted_by: Option<&str>,
    ) -> CoreResult<()> {
        sqlx::query(
            "UPDATE invitations SET status = $2, accepted_by = COALESCE($3, accepted_by) WHERE id = $1",
        )
        .bind(invitation_id)
        .bind(status)
        .bind(accepted_by)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }

    pub async fn ensure_user_tenant_membership(
        &self,
        id: &str,
        user_id: &str,
        tenant_id: &str,
        role: &str,
    ) -> CoreResult<()> {
        sqlx::query(
            "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
             SELECT $1, $2, $3, $4 \
             WHERE NOT EXISTS (\
                 SELECT 1 FROM user_tenants WHERE user_id = $2 AND tenant_id = $3\
             )",
        )
        .bind(id)
        .bind(user_id)
        .bind(tenant_id)
        .bind(role)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }
}

pub fn normalize_email(email: &str) -> String {
    email.trim().to_lowercase()
}

#[cfg(test)]
mod unit {
    use super::*;

    #[test]
    fn normalizes_email_like_python_service() {
        assert_eq!(normalize_email(" Ada@Example.TEST "), "ada@example.test");
    }
}
