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

use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::{CoreError, CoreResult};

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
    let (id, name, slug, description, owner_id, plan, max_projects, max_users, max_storage, created_at, updated_at) =
        row;
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
}
