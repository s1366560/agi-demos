//! Read-only stores over the **Python-owned** `api_keys` and `projects` tables —
//! the data source for the production auth + multi-tenancy middleware (Foundation
//! F2, plan.md Section 14.2).
//!
//! These are deliberately **read-only**: identity issuance stays in Python during
//! the strangler migration; the Rust server only needs to *verify* an incoming
//! `ms_sk_` key and resolve its project/tenant scope. Both structs are plain
//! adapters — the caller (a tower middleware) turns a verified record into 401 or
//! a scoped request, keeping the actual policy in the request pipeline.

use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::{CoreError, CoreResult};

use crate::{sha256_hex, PgPool};

/// A verified API-key record, mirroring the columns of the Python `api_keys`
/// table that the auth path reads.
#[derive(Debug, Clone)]
pub struct ApiKeyRecord {
    pub id: String,
    pub user_id: String,
    pub is_active: bool,
    pub expires_at: Option<DateTime<Utc>>,
}

impl ApiKeyRecord {
    /// True when the key may be used *right now*: active and unexpired at `now_ms`.
    /// Mirrors the Python check (`is_active` + optional `expires_at` in the future).
    pub fn is_usable_at(&self, now_ms: i64) -> bool {
        if !self.is_active {
            return false;
        }
        match self.expires_at {
            Some(exp) => exp.timestamp_millis() > now_ms,
            None => true,
        }
    }
}

/// Read-only lookup over the Python `api_keys` table. `Clone` is cheap (the
/// pool is `Arc`'d internally) so callers can hand a copy to a spawned task.
#[derive(Clone)]
pub struct PgApiKeyStore {
    pool: PgPool,
}

impl PgApiKeyStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Look up a raw `ms_sk_...` key by hashing it (SHA-256, byte-identical to
    /// Python) and matching `api_keys.key_hash`. Returns `None` when no row
    /// matches; the caller decides 401 vs. scope. Does **not** enforce
    /// active/expiry — use [`ApiKeyRecord::is_usable_at`] so the middleware owns
    /// that policy explicitly.
    pub async fn find_by_raw_key(&self, raw_key: &str) -> CoreResult<Option<ApiKeyRecord>> {
        let key_hash = sha256_hex(raw_key);
        let row = sqlx::query_as::<_, (String, String, bool, Option<DateTime<Utc>>)>(
            "SELECT id, user_id, is_active, expires_at FROM api_keys WHERE key_hash = $1",
        )
        .bind(&key_hash)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(
            row.map(|(id, user_id, is_active, expires_at)| ApiKeyRecord {
                id,
                user_id,
                is_active,
                expires_at,
            }),
        )
    }

    /// Best-effort `last_used_at = now()` touch, mirroring the Python auth path.
    /// Errors are swallowed by the caller (a failed audit touch must not fail the
    /// request), so this returns the raw sqlx result for the caller to log.
    pub async fn touch_last_used(&self, id: &str) -> CoreResult<()> {
        sqlx::query("UPDATE api_keys SET last_used_at = now() WHERE id = $1")
            .bind(id)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }
}

/// A project row projection for tenant-scope resolution.
#[derive(Debug, Clone)]
pub struct ProjectRecord {
    pub id: String,
    pub tenant_id: String,
    pub owner_id: String,
    pub is_public: bool,
}

/// Read-only lookup over the Python `projects` table — resolves the `tenant_id`
/// and ownership a request is scoped to (multi-tenancy invariant).
pub struct PgProjectStore {
    pool: PgPool,
}

impl PgProjectStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Fetch a project by id, or `None` if absent.
    pub async fn find_by_id(&self, project_id: &str) -> CoreResult<Option<ProjectRecord>> {
        let row = sqlx::query_as::<_, (String, String, String, bool)>(
            "SELECT id, tenant_id, owner_id, is_public FROM projects WHERE id = $1",
        )
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(
            row.map(|(id, tenant_id, owner_id, is_public)| ProjectRecord {
                id,
                tenant_id,
                owner_id,
                is_public,
            }),
        )
    }

    /// Whether `user_id` may read `project`: owner, public, or an explicit
    /// `user_projects` membership row. Mirrors the Python read predicates in
    /// `_verify_memory_read_access` / `list_memories` (owner / public /
    /// UserProject membership).
    pub async fn user_can_access(
        &self,
        user_id: &str,
        project: &ProjectRecord,
    ) -> CoreResult<bool> {
        if project.is_public || project.owner_id == user_id {
            return Ok(true);
        }
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects WHERE user_id = $1 AND project_id = $2",
        )
        .bind(user_id)
        .bind(&project.id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.0 > 0)
    }

    /// Whether a user may receive project runtime events. Unlike ordinary
    /// project reads, public visibility is insufficient because sandbox events
    /// can contain tenant-private execution details.
    pub async fn user_can_subscribe_project_events(
        &self,
        user_id: &str,
        project: &ProjectRecord,
    ) -> CoreResult<bool> {
        let (tenant_member, project_member) = sqlx::query_as::<_, (bool, bool)>(
            "SELECT \
                 EXISTS(SELECT 1 FROM user_tenants \
                        WHERE user_id = $1 AND tenant_id = $2), \
                 EXISTS(SELECT 1 FROM user_projects \
                        WHERE user_id = $1 AND project_id = $3)",
        )
        .bind(user_id)
        .bind(&project.tenant_id)
        .bind(&project.id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(tenant_member && project_member)
    }

    /// Whether `user_id` may write memories/episodes in `project`. Mirrors
    /// Python `_load_project_for_create`: owners and non-viewer project members
    /// may create; public visibility never grants writes.
    pub async fn user_can_write(&self, user_id: &str, project: &ProjectRecord) -> CoreResult<bool> {
        if project.owner_id == user_id {
            return Ok(true);
        }
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects \
             WHERE user_id = $1 AND project_id = $2 AND role <> 'viewer'",
        )
        .bind(user_id)
        .bind(&project.id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.0 > 0)
    }

    /// Whether `user_id` may administer `project`. Mirrors Python
    /// `_has_project_admin_access`: project owner, project owner/admin role,
    /// tenant owner/admin role, or a superuser may delete/administer memories.
    pub async fn user_can_admin(&self, user_id: &str, project: &ProjectRecord) -> CoreResult<bool> {
        if project.owner_id == user_id {
            return Ok(true);
        }

        let project_role = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects \
             WHERE user_id = $1 AND project_id = $2 AND role IN ('owner', 'admin')",
        )
        .bind(user_id)
        .bind(&project.id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        if project_role.0 > 0 {
            return Ok(true);
        }

        let tenant_role = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants \
             WHERE user_id = $1 AND tenant_id = $2 AND role IN ('owner', 'admin')",
        )
        .bind(user_id)
        .bind(&project.tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        if tenant_role.0 > 0 {
            return Ok(true);
        }

        let superuser =
            sqlx::query_as::<_, (Option<bool>,)>("SELECT is_superuser FROM users WHERE id = $1")
                .bind(user_id)
                .fetch_optional(&self.pool)
                .await
                .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(superuser
            .and_then(|(is_superuser,)| is_superuser)
            .unwrap_or(false))
    }
}

#[cfg(test)]
mod unit {
    use super::ApiKeyRecord;
    use sqlx::types::chrono::{DateTime, Utc};

    fn rec(is_active: bool, exp_offset_ms: Option<i64>) -> ApiKeyRecord {
        let now_ms = Utc::now().timestamp_millis();
        ApiKeyRecord {
            id: "k1".into(),
            user_id: "u1".into(),
            is_active,
            expires_at: exp_offset_ms
                .and_then(|off| DateTime::<Utc>::from_timestamp_millis(now_ms + off)),
        }
    }

    #[test]
    fn usability_respects_active_and_expiry() {
        let now = Utc::now().timestamp_millis();
        assert!(rec(true, None).is_usable_at(now));
        assert!(rec(true, Some(60_000)).is_usable_at(now));
        assert!(!rec(false, None).is_usable_at(now));
        assert!(!rec(true, Some(-60_000)).is_usable_at(now));
    }
}
