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
use sqlx::{Postgres, Row};

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

#[derive(Debug)]
struct ForeignKeyRef {
    table_name: String,
    column_name: String,
}

async fn delete_tenant_dependents(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    tenant_id: &str,
) -> CoreResult<()> {
    let tenant_ids = vec![tenant_id.to_string()];
    let project_ids = select_ids_by_eq(tx, "projects", "id", "tenant_id", tenant_id).await?;

    let mut conversation_ids =
        select_ids_by_any(tx, "conversations", "id", "project_id", &project_ids).await?;
    append_unique(
        &mut conversation_ids,
        select_ids_by_eq(tx, "conversations", "id", "tenant_id", tenant_id).await?,
    );
    let message_ids =
        select_ids_by_any(tx, "messages", "id", "conversation_id", &conversation_ids).await?;

    let mut workspace_ids =
        select_ids_by_any(tx, "workspaces", "id", "project_id", &project_ids).await?;
    append_unique(
        &mut workspace_ids,
        select_ids_by_eq(tx, "workspaces", "id", "tenant_id", tenant_id).await?,
    );

    if table_exists(tx, "messages").await? {
        update_null_by_any(tx, "messages", "reply_to_id", &message_ids).await?;
        delete_rows_referencing(tx, "messages", "id", &message_ids, vec!["messages".into()])
            .await?;
        delete_by_any(tx, "messages", "conversation_id", &conversation_ids).await?;
    }

    if table_exists(tx, "conversations").await? {
        update_null_by_any(
            tx,
            "conversations",
            "parent_conversation_id",
            &conversation_ids,
        )
        .await?;
        update_null_by_any(tx, "conversations", "fork_source_id", &conversation_ids).await?;
        delete_rows_referencing(
            tx,
            "conversations",
            "id",
            &conversation_ids,
            vec!["conversations".into(), "messages".into()],
        )
        .await?;
        delete_by_any(tx, "conversations", "id", &conversation_ids).await?;
    }

    delete_rows_referencing(
        tx,
        "workspaces",
        "id",
        &workspace_ids,
        vec!["workspaces".into(), "conversations".into()],
    )
    .await?;
    delete_by_any(tx, "workspaces", "id", &workspace_ids).await?;

    delete_rows_referencing(
        tx,
        "projects",
        "id",
        &project_ids,
        vec![
            "projects".into(),
            "conversations".into(),
            "messages".into(),
            "workspaces".into(),
        ],
    )
    .await?;
    delete_by_any(tx, "projects", "id", &project_ids).await?;

    delete_rows_referencing(tx, "tenants", "id", &tenant_ids, vec!["tenants".into()]).await
}

async fn delete_rows_referencing(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    target_table: &str,
    target_column: &str,
    target_ids: &[String],
    skip_tables: Vec<String>,
) -> CoreResult<()> {
    if target_ids.is_empty() || !table_exists(tx, target_table).await? {
        return Ok(());
    }

    let mut references = foreign_key_references(tx, target_table, target_column).await?;
    if let Some(fallback_column) = fallback_reference_column(target_table) {
        for reference in tables_with_column(tx, fallback_column).await? {
            if reference.table_name == target_table {
                continue;
            }
            if !references.iter().any(|existing| {
                existing.table_name == reference.table_name
                    && existing.column_name == reference.column_name
            }) {
                references.push(reference);
            }
        }
    }

    for reference in references {
        if skip_tables
            .iter()
            .any(|skip| skip.as_str() == reference.table_name)
        {
            continue;
        }

        if table_has_column(tx, &reference.table_name, "id").await? {
            let source_ids = select_ids_by_any(
                tx,
                &reference.table_name,
                "id",
                &reference.column_name,
                target_ids,
            )
            .await?;
            if !source_ids.is_empty() {
                let mut nested_skip = skip_tables.clone();
                nested_skip.push(reference.table_name.clone());
                Box::pin(delete_rows_referencing(
                    tx,
                    &reference.table_name,
                    "id",
                    &source_ids,
                    nested_skip,
                ))
                .await?;
            }
        }

        delete_by_any(
            tx,
            &reference.table_name,
            &reference.column_name,
            target_ids,
        )
        .await?;
    }

    Ok(())
}

fn fallback_reference_column(target_table: &str) -> Option<&'static str> {
    match target_table {
        "tenants" => Some("tenant_id"),
        "projects" => Some("project_id"),
        "conversations" => Some("conversation_id"),
        "workspaces" => Some("workspace_id"),
        "messages" => Some("message_id"),
        _ => None,
    }
}

async fn foreign_key_references(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    target_table: &str,
    target_column: &str,
) -> CoreResult<Vec<ForeignKeyRef>> {
    let rows = sqlx::query(
        "SELECT source_table.relname AS table_name, source_attr.attname AS column_name \
         FROM pg_constraint c \
         JOIN pg_class source_table ON source_table.oid = c.conrelid \
         JOIN pg_namespace source_ns ON source_ns.oid = source_table.relnamespace \
         JOIN pg_class target_table ON target_table.oid = c.confrelid \
         JOIN pg_namespace target_ns ON target_ns.oid = target_table.relnamespace \
         JOIN unnest(c.conkey) WITH ORDINALITY AS source_key(attnum, ord) ON true \
         JOIN unnest(c.confkey) WITH ORDINALITY AS target_key(attnum, ord) \
              ON source_key.ord = target_key.ord \
         JOIN pg_attribute source_attr \
              ON source_attr.attrelid = source_table.oid AND source_attr.attnum = source_key.attnum \
         JOIN pg_attribute target_attr \
              ON target_attr.attrelid = target_table.oid AND target_attr.attnum = target_key.attnum \
         WHERE c.contype = 'f' \
           AND source_ns.nspname = ANY(current_schemas(false)) \
           AND target_ns.nspname = ANY(current_schemas(false)) \
           AND target_table.relname = $1 \
           AND target_attr.attname = $2 \
         ORDER BY source_table.relname, source_attr.attname",
    )
    .bind(target_table)
    .bind(target_column)
    .fetch_all(&mut **tx)
    .await
    .map_err(|e| CoreError::Storage(e.to_string()))?;

    rows.into_iter()
        .map(|row| {
            Ok(ForeignKeyRef {
                table_name: row.try_get("table_name")?,
                column_name: row.try_get("column_name")?,
            })
        })
        .collect::<Result<Vec<_>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn tables_with_column(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    column: &str,
) -> CoreResult<Vec<ForeignKeyRef>> {
    let rows = sqlx::query(
        "SELECT c.table_name, c.column_name \
         FROM information_schema.columns c \
         JOIN information_schema.tables t \
           ON t.table_schema = c.table_schema AND t.table_name = c.table_name \
         WHERE c.table_schema = ANY(current_schemas(false)) \
           AND c.column_name = $1 \
           AND t.table_type = 'BASE TABLE' \
         ORDER BY c.table_name",
    )
    .bind(column)
    .fetch_all(&mut **tx)
    .await
    .map_err(|e| CoreError::Storage(e.to_string()))?;

    rows.into_iter()
        .map(|row| {
            Ok(ForeignKeyRef {
                table_name: row.try_get("table_name")?,
                column_name: row.try_get("column_name")?,
            })
        })
        .collect::<Result<Vec<_>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn table_exists(tx: &mut sqlx::Transaction<'_, Postgres>, table: &str) -> CoreResult<bool> {
    sqlx::query_as::<_, (bool,)>("SELECT to_regclass($1) IS NOT NULL")
        .bind(table)
        .fetch_one(&mut **tx)
        .await
        .map(|row| row.0)
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn table_has_column(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
) -> CoreResult<bool> {
    sqlx::query_as::<_, (bool,)>(
        "SELECT EXISTS ( \
             SELECT 1 FROM information_schema.columns \
             WHERE table_schema = ANY(current_schemas(false)) \
               AND table_name = $1 \
               AND column_name = $2 \
         )",
    )
    .bind(table)
    .bind(column)
    .fetch_one(&mut **tx)
    .await
    .map(|row| row.0)
    .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn select_ids_by_eq(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    id_column: &str,
    filter_column: &str,
    filter_value: &str,
) -> CoreResult<Vec<String>> {
    select_ids_by_any(
        tx,
        table,
        id_column,
        filter_column,
        &[filter_value.to_string()],
    )
    .await
}

async fn select_ids_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    id_column: &str,
    filter_column: &str,
    filter_values: &[String],
) -> CoreResult<Vec<String>> {
    if filter_values.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, id_column).await?
        || !table_has_column(tx, table, filter_column).await?
    {
        return Ok(Vec::new());
    }
    let sql = format!(
        "SELECT {}::text AS id FROM {} WHERE {} IS NOT NULL AND {}::text = ANY($1::text[])",
        quote_ident(id_column),
        quote_ident(table),
        quote_ident(id_column),
        quote_ident(filter_column)
    );
    let rows = sqlx::query(&sql)
        .bind(filter_values.to_vec())
        .fetch_all(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    rows.into_iter()
        .map(|row| row.try_get("id"))
        .collect::<Result<Vec<String>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn update_null_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
    ids: &[String],
) -> CoreResult<()> {
    if ids.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, column).await?
    {
        return Ok(());
    }
    let sql = format!(
        "UPDATE {} SET {} = NULL WHERE {}::text = ANY($1::text[])",
        quote_ident(table),
        quote_ident(column),
        quote_ident(column)
    );
    sqlx::query(&sql)
        .bind(ids.to_vec())
        .execute(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    Ok(())
}

async fn delete_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
    ids: &[String],
) -> CoreResult<()> {
    if ids.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, column).await?
    {
        return Ok(());
    }
    let sql = format!(
        "DELETE FROM {} WHERE {}::text = ANY($1::text[])",
        quote_ident(table),
        quote_ident(column)
    );
    sqlx::query(&sql)
        .bind(ids.to_vec())
        .execute(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    Ok(())
}

fn append_unique(values: &mut Vec<String>, extra: Vec<String>) {
    for value in extra {
        if !values.contains(&value) {
            values.push(value);
        }
    }
}

fn quote_ident(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
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
