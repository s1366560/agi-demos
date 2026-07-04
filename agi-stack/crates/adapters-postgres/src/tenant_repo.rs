//! Read-only repository over the **Python-owned** `tenants` + `user_tenants`
//! tables — the data source for the **P2 tenant read endpoints** (plan.md
//! Section 15.2). Membership-scoped: every query joins `user_tenants` so a caller
//! only ever sees tenants they belong to (the multi-tenancy invariant), exactly
//! like the Python `routers/tenants.py` list/get handlers.
//!
//! `TenantRecord` mirrors the columns of the Python `TenantResponse`
//! (`src/application/schemas/tenant.py`) 1:1, so the server layer serializes a
//! byte-compatible response. Ordering matches Python's
//! `_order_tenant_list_query` (`user_tenants.created_at, user_tenants.id,
//! tenants.id`) so pagination is stable and identical across backends.

use serde_json::Value;
use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::{CoreError, CoreResult};

mod delete;

use delete::delete_tenant_dependents;

use crate::PgPool;

/// A tenant row projection, column-for-column with the Python `TenantResponse`.
#[derive(Debug, Clone)]
pub struct TenantRecord {
    pub id: String,
    pub name: String,
    pub slug: String,
    pub description: Option<String>,
    pub owner_id: String,
    pub plan: String,
    pub max_projects: i32,
    pub max_users: i32,
    pub max_storage: i64,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Default)]
pub struct TenantUpdatePatch {
    pub name: Option<String>,
    pub description: Option<Option<String>>,
    pub plan: Option<String>,
    pub max_projects: Option<i32>,
    pub max_users: Option<i32>,
    pub max_storage: Option<i64>,
}

impl TenantUpdatePatch {
    pub fn is_empty(&self) -> bool {
        self.name.is_none()
            && self.description.is_none()
            && self.plan.is_none()
            && self.max_projects.is_none()
            && self.max_users.is_none()
            && self.max_storage.is_none()
    }
}

#[derive(Debug, Clone)]
pub struct TenantMemberMutationRecord {
    pub role: String,
}

type TenantRow = (
    String,
    String,
    String,
    Option<String>,
    String,
    String,
    i32,
    i32,
    i64,
    DateTime<Utc>,
    Option<DateTime<Utc>>,
);

fn to_record(row: TenantRow) -> TenantRecord {
    let (
        id,
        name,
        slug,
        description,
        owner_id,
        plan,
        max_projects,
        max_users,
        max_storage,
        created_at,
        updated_at,
    ) = row;
    TenantRecord {
        id,
        name,
        slug,
        description,
        owner_id,
        plan,
        max_projects,
        max_users,
        max_storage,
        created_at,
        updated_at,
    }
}

const TENANT_COLS: &str = "t.id, t.name, t.slug, t.description, t.owner_id, t.plan, \
     t.max_projects, t.max_users, t.max_storage, t.created_at, t.updated_at";

/// Outcome of a single-tenant lookup, encoding Python's 404-then-403 ordering
/// without overloading [`CoreError`].
#[derive(Debug)]
pub enum TenantLookup {
    /// Tenant exists and the caller is a member.
    Found(TenantRecord),
    /// No tenant with that id or slug (caller maps to 404).
    NotFound,
    /// Tenant exists but the caller is not a member (caller maps to 403).
    Forbidden,
}

/// Read-only, membership-scoped repository over `tenants`.
pub struct PgTenantRepository {
    pool: PgPool,
}

impl PgTenantRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Count the tenants `user_id` belongs to (optionally filtered by a `search`
    /// substring over name/description) — the `total` for the paginated list.
    pub async fn count_for_user(&self, user_id: &str, search: Option<&str>) -> CoreResult<i64> {
        let sql = format!(
            "SELECT count(*) FROM tenants t \
             JOIN user_tenants ut ON ut.tenant_id = t.id \
             WHERE ut.user_id = $1{}",
            search_clause(search.is_some())
        );
        let mut q = sqlx::query_as::<_, (i64,)>(&sql).bind(user_id);
        if let Some(term) = search {
            q = q.bind(like(term));
        }
        let row = q
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.0)
    }

    /// List the tenants `user_id` belongs to, newest-membership first, paginated.
    /// Ordering is byte-identical to Python's `_order_tenant_list_query`.
    pub async fn list_for_user(
        &self,
        user_id: &str,
        search: Option<&str>,
        offset: i64,
        limit: i64,
    ) -> CoreResult<Vec<TenantRecord>> {
        let sql = format!(
            "SELECT {TENANT_COLS} FROM tenants t \
             JOIN user_tenants ut ON ut.tenant_id = t.id \
             WHERE ut.user_id = $1{} \
             ORDER BY ut.created_at ASC, ut.id ASC, t.id ASC \
             OFFSET {offset} LIMIT {limit}",
            search_clause(search.is_some())
        );
        let mut q = sqlx::query_as::<_, TenantRow>(&sql).bind(user_id);
        if let Some(term) = search {
            q = q.bind(like(term));
        }
        let rows = q
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(rows.into_iter().map(to_record).collect())
    }

    /// Fetch a single tenant by **id or slug** (Python accepts either), scoped to
    /// `user_id`'s membership. Returns a [`TenantLookup`] encoding Python's
    /// 404-then-403 ordering: not-found wins over forbidden.
    pub async fn get_for_user(
        &self,
        user_id: &str,
        tenant_id_or_slug: &str,
    ) -> CoreResult<TenantLookup> {
        let row = sqlx::query_as::<_, TenantRow>(&format!(
            "SELECT {TENANT_COLS} FROM tenants t WHERE t.id = $1 OR t.slug = $1"
        ))
        .bind(tenant_id_or_slug)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        let Some(record) = row.map(to_record) else {
            return Ok(TenantLookup::NotFound);
        };

        let member = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(&record.id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        if member.0 > 0 {
            Ok(TenantLookup::Found(record))
        } else {
            Ok(TenantLookup::Forbidden)
        }
    }

    pub async fn create_tenant(
        &self,
        tenant_id: &str,
        membership_id: &str,
        owner_id: &str,
        name: &str,
        description: Option<&str>,
        owner_permissions: &Value,
    ) -> CoreResult<TenantRecord> {
        let slug = tenant_slug(name);
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        sqlx::query(
            "INSERT INTO tenants \
             (id, name, slug, description, owner_id, plan, max_projects, max_users, max_storage) \
             VALUES ($1, $2, $3, $4, $5, 'free', 10, 5, 1073741824)",
        )
        .bind(tenant_id)
        .bind(name)
        .bind(&slug)
        .bind(description)
        .bind(owner_id)
        .execute(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        sqlx::query(
            "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
             VALUES ($1, $2, $3, 'owner', $4)",
        )
        .bind(membership_id)
        .bind(owner_id)
        .bind(tenant_id)
        .bind(owner_permissions)
        .execute(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        let row = sqlx::query_as::<_, TenantRow>(&format!(
            "SELECT {TENANT_COLS} FROM tenants t WHERE t.id = $1"
        ))
        .bind(tenant_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(to_record(row))
    }

    pub async fn update_owned_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
        patch: &TenantUpdatePatch,
    ) -> CoreResult<Option<TenantRecord>> {
        let owned = self.user_owns_tenant(user_id, tenant_id).await?;
        if !owned {
            return Ok(None);
        }
        if !patch.is_empty() {
            sqlx::query(
                "UPDATE tenants SET \
                 name = CASE WHEN $3 THEN $4 ELSE name END, \
                 description = CASE WHEN $5 THEN $6 ELSE description END, \
                 plan = CASE WHEN $7 THEN $8 ELSE plan END, \
                 max_projects = CASE WHEN $9 THEN $10 ELSE max_projects END, \
                 max_users = CASE WHEN $11 THEN $12 ELSE max_users END, \
                 max_storage = CASE WHEN $13 THEN $14 ELSE max_storage END, \
                 updated_at = now() \
                 WHERE id = $1 AND owner_id = $2",
            )
            .bind(tenant_id)
            .bind(user_id)
            .bind(patch.name.is_some())
            .bind(patch.name.as_deref())
            .bind(patch.description.is_some())
            .bind(patch.description.as_ref().and_then(|v| v.as_deref()))
            .bind(patch.plan.is_some())
            .bind(patch.plan.as_deref())
            .bind(patch.max_projects.is_some())
            .bind(patch.max_projects)
            .bind(patch.max_users.is_some())
            .bind(patch.max_users)
            .bind(patch.max_storage.is_some())
            .bind(patch.max_storage)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        }
        self.get_by_id(tenant_id).await
    }

    pub async fn tenant_exists(&self, tenant_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM tenants WHERE id = $1")
            .bind(tenant_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn user_owns_tenant(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM tenants WHERE id = $1 AND owner_id = $2",
        )
        .bind(tenant_id)
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn user_exists(&self, user_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM users WHERE id = $1")
            .bind(user_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn tenant_member_role(
        &self,
        tenant_id: &str,
        user_id: &str,
    ) -> CoreResult<Option<TenantMemberMutationRecord>> {
        let row = sqlx::query_as::<_, (String,)>(
            "SELECT COALESCE(role, 'member') FROM user_tenants \
             WHERE tenant_id = $1 AND user_id = $2",
        )
        .bind(tenant_id)
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.map(|(role,)| TenantMemberMutationRecord { role }))
    }

    pub async fn add_tenant_member(
        &self,
        id: &str,
        tenant_id: &str,
        user_id: &str,
        role: &str,
        permissions: &Value,
    ) -> CoreResult<()> {
        sqlx::query(
            "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
             VALUES ($1, $2, $3, $4, $5)",
        )
        .bind(id)
        .bind(user_id)
        .bind(tenant_id)
        .bind(role)
        .bind(permissions)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }

    pub async fn update_tenant_member(
        &self,
        tenant_id: &str,
        user_id: &str,
        role: &str,
        permissions: &Value,
    ) -> CoreResult<bool> {
        let result = sqlx::query(
            "UPDATE user_tenants SET role = $1, permissions = $2 \
             WHERE tenant_id = $3 AND user_id = $4",
        )
        .bind(role)
        .bind(permissions)
        .bind(tenant_id)
        .bind(user_id)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn remove_tenant_member(&self, tenant_id: &str, user_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM user_tenants WHERE tenant_id = $1 AND user_id = $2")
            .bind(tenant_id)
            .bind(user_id)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn delete_owned_tenant(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        if !self.user_owns_tenant(user_id, tenant_id).await? {
            return Ok(false);
        }

        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;

        delete_tenant_dependents(&mut tx, tenant_id).await?;
        let result = sqlx::query("DELETE FROM tenants WHERE id = $1 AND owner_id = $2")
            .bind(tenant_id)
            .bind(user_id)
            .execute(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }

    async fn get_by_id(&self, tenant_id: &str) -> CoreResult<Option<TenantRecord>> {
        let row = sqlx::query_as::<_, TenantRow>(&format!(
            "SELECT {TENANT_COLS} FROM tenants t WHERE t.id = $1"
        ))
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.map(to_record))
    }
}

/// The `AND (name ILIKE $2 OR description ILIKE $2)` fragment, or empty.
fn search_clause(has_search: bool) -> &'static str {
    if has_search {
        " AND (t.name ILIKE $2 OR t.description ILIKE $2)"
    } else {
        ""
    }
}

/// Wrap a search term in `%...%` for an `ILIKE`, mirroring Python's
/// `f"%{search}%"`.
fn like(term: &str) -> String {
    format!("%{term}%")
}

fn tenant_slug(name: &str) -> String {
    name.to_lowercase().replace(' ', "-")
}

#[cfg(test)]
mod unit {
    use super::*;

    #[test]
    fn search_clause_toggles() {
        assert!(search_clause(true).contains("ILIKE"));
        assert_eq!(search_clause(false), "");
    }

    #[test]
    fn like_wraps_term() {
        assert_eq!(like("acme"), "%acme%");
    }

    #[test]
    fn tenant_slug_matches_python_create() {
        assert_eq!(tenant_slug("Acme Corporation"), "acme-corporation");
        assert_eq!(tenant_slug("  A  B  "), "--a--b--");
    }
}
