//! Adapter over Python-owned instance tables.
//!
//! Rust owns tenant-default instance list/detail reads plus instance config,
//! config writes, pending-config staging, member list/search/mutations, and
//! channel-list reads in this checkpoint. Instance creation, mutation, scaling,
//! config apply, files, channel mutations/tests, and runtime side effects remain
//! Python-owned.

use serde_json::{json, Value};
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::{postgres::PgRow, Postgres, QueryBuilder, Row};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const INSTANCE_COLS: &str = "id, name, slug, description, tenant_id, cluster_id, namespace, \
    image_version, replicas, cpu_request, cpu_limit, mem_request, mem_limit, service_type, \
    ingress_domain, proxy_token, env_vars, quota_cpu, quota_memory, quota_max_pods, \
    storage_class, storage_size, advanced_config, llm_providers, pending_config, \
    available_replicas, status, health_status, current_revision, compute_provider, runtime, \
    created_by, workspace_id, hex_position_q, hex_position_r, agent_display_name, agent_label, \
    theme_color, created_at, updated_at";

#[derive(Debug, Clone, Copy)]
pub struct InstanceListQuery<'a> {
    pub tenant_id: &'a str,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone)]
pub struct InstanceRecord {
    pub id: String,
    pub name: String,
    pub slug: String,
    pub description: Option<String>,
    pub tenant_id: String,
    pub cluster_id: Option<String>,
    pub namespace: Option<String>,
    pub image_version: String,
    pub replicas: i32,
    pub cpu_request: String,
    pub cpu_limit: String,
    pub mem_request: String,
    pub mem_limit: String,
    pub service_type: String,
    pub ingress_domain: Option<String>,
    pub proxy_token: Option<String>,
    pub env_vars: Value,
    pub quota_cpu: Option<String>,
    pub quota_memory: Option<String>,
    pub quota_max_pods: Option<i32>,
    pub storage_class: Option<String>,
    pub storage_size: Option<String>,
    pub advanced_config: Value,
    pub llm_providers: Value,
    pub pending_config: Value,
    pub available_replicas: i32,
    pub status: String,
    pub health_status: Option<String>,
    pub current_revision: i32,
    pub compute_provider: Option<String>,
    pub runtime: String,
    pub created_by: String,
    pub workspace_id: Option<String>,
    pub hex_position_q: Option<i32>,
    pub hex_position_r: Option<i32>,
    pub agent_display_name: Option<String>,
    pub agent_label: Option<String>,
    pub theme_color: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct InstanceChannelRecord {
    pub id: String,
    pub instance_id: String,
    pub channel_type: String,
    pub name: String,
    pub config: Value,
    pub status: String,
    pub last_connected_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub deleted_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy)]
pub struct InstanceMemberListQuery<'a> {
    pub instance_id: &'a str,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone)]
pub struct InstanceMemberRecord {
    pub id: String,
    pub instance_id: String,
    pub user_id: String,
    pub role: String,
    pub user_name: Option<String>,
    pub user_email: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct InstanceUserSearchRecord {
    pub id: String,
    pub email: String,
    pub full_name: Option<String>,
}

pub struct PgInstanceRepository {
    pool: PgPool,
}

impl PgInstanceRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn default_tenant_for_user(&self, user_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id \
             FROM user_tenants \
             WHERE user_id = $1 \
             ORDER BY created_at ASC, id ASC \
             LIMIT 1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(tenant_id,)| tenant_id))
        .map_err(|e| CoreError::Storage(format!("read instance default tenant: {e}")))
    }

    pub async fn list_instances(
        &self,
        query: InstanceListQuery<'_>,
    ) -> CoreResult<(Vec<InstanceRecord>, i64)> {
        let total = sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) FROM instances WHERE tenant_id = $1 AND deleted_at IS NULL",
        )
        .bind(query.tenant_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count)
        .map_err(|e| CoreError::Storage(format!("count instances: {e}")))?;

        let sql = format!(
            "SELECT {INSTANCE_COLS} \
             FROM instances \
             WHERE tenant_id = $1 AND deleted_at IS NULL \
             ORDER BY created_at DESC, id ASC \
             LIMIT $2 OFFSET $3"
        );
        let rows = sqlx::query(&sql)
            .bind(query.tenant_id)
            .bind(query.limit)
            .bind(query.offset)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list instances: {e}")))?;

        let records = rows
            .into_iter()
            .map(instance_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read instance row: {e}")))?;
        Ok((records, total))
    }

    pub async fn get_instance(
        &self,
        tenant_id: &str,
        instance_id: &str,
    ) -> CoreResult<Option<InstanceRecord>> {
        let sql = format!(
            "SELECT {INSTANCE_COLS} \
             FROM instances \
             WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL"
        );
        sqlx::query(&sql)
            .bind(tenant_id)
            .bind(instance_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get instance: {e}")))?
            .map(instance_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read instance row: {e}")))
    }

    pub async fn save_pending_config(
        &self,
        tenant_id: &str,
        instance_id: &str,
        pending_config: Value,
    ) -> CoreResult<Option<InstanceRecord>> {
        let sql = format!(
            "UPDATE instances \
             SET pending_config = $3, updated_at = NOW() \
             WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL \
             RETURNING {INSTANCE_COLS}"
        );
        sqlx::query(&sql)
            .bind(tenant_id)
            .bind(instance_id)
            .bind(pending_config)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("save instance pending config: {e}")))?
            .map(instance_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read instance row: {e}")))
    }

    pub async fn update_instance_config(
        &self,
        tenant_id: &str,
        instance_id: &str,
        env_vars: Value,
        advanced_config: Value,
        llm_providers: Value,
    ) -> CoreResult<Option<InstanceRecord>> {
        let sql = format!(
            "UPDATE instances \
             SET env_vars = $3, advanced_config = $4, llm_providers = $5, updated_at = NOW() \
             WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL \
             RETURNING {INSTANCE_COLS}"
        );
        sqlx::query(&sql)
            .bind(tenant_id)
            .bind(instance_id)
            .bind(env_vars)
            .bind(advanced_config)
            .bind(llm_providers)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("update instance config: {e}")))?
            .map(instance_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read instance row: {e}")))
    }

    pub async fn instance_tenant_id(&self, instance_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id FROM instances WHERE id = $1 AND deleted_at IS NULL",
        )
        .bind(instance_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(tenant_id,)| tenant_id))
        .map_err(|e| CoreError::Storage(format!("read instance tenant: {e}")))
    }

    pub async fn user_can_access_tenant(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        if self.user_has_global_admin(user_id).await? {
            return Ok(true);
        }

        sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read instance tenant access: {e}")))
    }

    pub async fn list_instance_channels(
        &self,
        instance_id: &str,
    ) -> CoreResult<Vec<InstanceChannelRecord>> {
        let rows = sqlx::query(
            "SELECT id, instance_id, channel_type, name, config, status, \
                    last_connected_at, created_at, updated_at, deleted_at \
             FROM instance_channel_configs \
             WHERE instance_id = $1 AND deleted_at IS NULL \
             ORDER BY created_at DESC, id ASC",
        )
        .bind(instance_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("list instance channels: {e}")))?;

        rows.into_iter()
            .map(instance_channel_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read instance channel row: {e}")))
    }

    pub async fn list_instance_members(
        &self,
        query: InstanceMemberListQuery<'_>,
    ) -> CoreResult<(Vec<InstanceMemberRecord>, i64)> {
        let total = sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) \
             FROM instance_members \
             WHERE instance_id = $1 AND deleted_at IS NULL",
        )
        .bind(query.instance_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count)
        .map_err(|e| CoreError::Storage(format!("count instance members: {e}")))?;

        let rows = sqlx::query(
            "SELECT im.id, im.instance_id, im.user_id, im.role, im.created_at, \
                    users.full_name AS user_name, users.email AS user_email \
             FROM instance_members im \
             LEFT JOIN users ON users.id = im.user_id \
             WHERE im.instance_id = $1 AND im.deleted_at IS NULL \
             ORDER BY im.created_at ASC, im.id ASC \
             LIMIT $2 OFFSET $3",
        )
        .bind(query.instance_id)
        .bind(query.limit)
        .bind(query.offset)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("list instance members: {e}")))?;

        let records = rows
            .into_iter()
            .map(instance_member_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read instance member row: {e}")))?;
        Ok((records, total))
    }

    pub async fn instance_member_exists_any(
        &self,
        instance_id: &str,
        user_id: &str,
    ) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) FROM instance_members WHERE instance_id = $1 AND user_id = $2",
        )
        .bind(instance_id)
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read instance member existence: {e}")))
    }

    pub async fn insert_instance_member(
        &self,
        id: &str,
        instance_id: &str,
        user_id: &str,
        role: &str,
    ) -> CoreResult<InstanceMemberRecord> {
        let row = sqlx::query(
            "WITH inserted AS (\
                 INSERT INTO instance_members (id, instance_id, user_id, role, created_at, deleted_at) \
                 VALUES ($1, $2, $3, $4, NOW(), NULL) \
                 RETURNING id, instance_id, user_id, role, created_at\
             ) \
             SELECT inserted.id, inserted.instance_id, inserted.user_id, inserted.role, \
                    users.full_name AS user_name, users.email AS user_email, inserted.created_at \
             FROM inserted \
             LEFT JOIN users ON users.id = inserted.user_id",
        )
        .bind(id)
        .bind(instance_id)
        .bind(user_id)
        .bind(role)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("insert instance member: {e}")))?;
        instance_member_from_row(row)
            .map_err(|e| CoreError::Storage(format!("read instance member row: {e}")))
    }

    pub async fn update_instance_member_role(
        &self,
        instance_id: &str,
        member_id: &str,
        role: &str,
    ) -> CoreResult<Option<InstanceMemberRecord>> {
        sqlx::query(
            "WITH updated AS (\
                 UPDATE instance_members \
                 SET role = $3 \
                 WHERE instance_id = $1 AND id = $2 \
                 RETURNING id, instance_id, user_id, role, created_at\
             ) \
             SELECT updated.id, updated.instance_id, updated.user_id, updated.role, \
                    users.full_name AS user_name, users.email AS user_email, updated.created_at \
             FROM updated \
             LEFT JOIN users ON users.id = updated.user_id",
        )
        .bind(instance_id)
        .bind(member_id)
        .bind(role)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("update instance member role: {e}")))?
        .map(instance_member_from_row)
        .transpose()
        .map_err(|e| CoreError::Storage(format!("read instance member row: {e}")))
    }

    pub async fn soft_delete_instance_member(
        &self,
        instance_id: &str,
        user_id: &str,
    ) -> CoreResult<bool> {
        sqlx::query(
            "UPDATE instance_members \
             SET deleted_at = NOW() \
             WHERE instance_id = $1 AND user_id = $2",
        )
        .bind(instance_id)
        .bind(user_id)
        .execute(&self.pool)
        .await
        .map(|result| result.rows_affected() > 0)
        .map_err(|e| CoreError::Storage(format!("delete instance member: {e}")))
    }

    pub async fn search_tenant_users(
        &self,
        tenant_id: &str,
        q: &str,
        limit: i64,
    ) -> CoreResult<Vec<InstanceUserSearchRecord>> {
        let mut builder = QueryBuilder::<Postgres>::new(
            "SELECT users.id, users.email, users.full_name \
             FROM users \
             WHERE users.is_active IS TRUE \
               AND users.id IN (SELECT user_id FROM user_tenants WHERE tenant_id = ",
        );
        builder.push_bind(tenant_id);
        builder.push(")");
        if !q.is_empty() {
            let pattern = format!("%{q}%");
            builder.push(" AND (users.email ILIKE ");
            builder.push_bind(pattern.clone());
            builder.push(" OR users.full_name ILIKE ");
            builder.push_bind(pattern);
            builder.push(")");
        }
        builder.push(" ORDER BY users.full_name ASC, users.email ASC LIMIT ");
        builder.push_bind(limit);

        builder
            .build()
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("search instance tenant users: {e}")))?
            .into_iter()
            .map(instance_user_search_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read instance user search row: {e}")))
    }

    async fn user_has_global_admin(&self, user_id: &str) -> CoreResult<bool> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(is_superuser,)| is_superuser).unwrap_or(false))
        .map_err(|e| CoreError::Storage(format!("read instance user superuser: {e}")))?;
        if is_superuser {
            return Ok(true);
        }

        sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) \
             FROM user_roles \
             JOIN roles ON roles.id = user_roles.role_id \
             WHERE user_roles.user_id = $1 \
               AND user_roles.tenant_id IS NULL \
               AND roles.name = 'system_admin'",
        )
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read instance user global role: {e}")))
    }
}

fn instance_from_row(row: PgRow) -> Result<InstanceRecord, sqlx::Error> {
    Ok(InstanceRecord {
        id: row.try_get("id")?,
        name: row.try_get("name")?,
        slug: row.try_get("slug")?,
        description: row.try_get("description")?,
        tenant_id: row.try_get("tenant_id")?,
        cluster_id: row.try_get("cluster_id")?,
        namespace: row.try_get("namespace")?,
        image_version: string_or_default(&row, "image_version", "latest")?,
        replicas: int_or_default(&row, "replicas", 1)?,
        cpu_request: string_or_default(&row, "cpu_request", "100m")?,
        cpu_limit: string_or_default(&row, "cpu_limit", "500m")?,
        mem_request: string_or_default(&row, "mem_request", "256Mi")?,
        mem_limit: string_or_default(&row, "mem_limit", "512Mi")?,
        service_type: string_or_default(&row, "service_type", "ClusterIP")?,
        ingress_domain: row.try_get("ingress_domain")?,
        proxy_token: row.try_get("proxy_token")?,
        env_vars: json_or_default(&row, "env_vars")?,
        quota_cpu: row.try_get("quota_cpu")?,
        quota_memory: row.try_get("quota_memory")?,
        quota_max_pods: row.try_get("quota_max_pods")?,
        storage_class: row.try_get("storage_class")?,
        storage_size: row.try_get("storage_size")?,
        advanced_config: json_or_default(&row, "advanced_config")?,
        llm_providers: json_or_default(&row, "llm_providers")?,
        pending_config: json_or_default(&row, "pending_config")?,
        available_replicas: int_or_default(&row, "available_replicas", 0)?,
        status: string_or_default(&row, "status", "creating")?,
        health_status: row.try_get("health_status")?,
        current_revision: int_or_default(&row, "current_revision", 0)?,
        compute_provider: row.try_get("compute_provider")?,
        runtime: string_or_default(&row, "runtime", "default")?,
        created_by: string_or_default(&row, "created_by", "")?,
        workspace_id: row.try_get("workspace_id")?,
        hex_position_q: row.try_get("hex_position_q")?,
        hex_position_r: row.try_get("hex_position_r")?,
        agent_display_name: row.try_get("agent_display_name")?,
        agent_label: row.try_get("agent_label")?,
        theme_color: row.try_get("theme_color")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

fn json_or_default(row: &PgRow, column: &str) -> Result<Value, sqlx::Error> {
    row.try_get::<Option<Value>, _>(column)
        .map(|value| value.unwrap_or_else(|| json!({})))
}

fn string_or_default(row: &PgRow, column: &str, default: &str) -> Result<String, sqlx::Error> {
    row.try_get::<Option<String>, _>(column)
        .map(|value| value.unwrap_or_else(|| default.to_string()))
}

fn int_or_default(row: &PgRow, column: &str, default: i32) -> Result<i32, sqlx::Error> {
    row.try_get::<Option<i32>, _>(column)
        .map(|value| value.unwrap_or(default))
}

fn instance_channel_from_row(row: PgRow) -> Result<InstanceChannelRecord, sqlx::Error> {
    Ok(InstanceChannelRecord {
        id: row.try_get("id")?,
        instance_id: row.try_get("instance_id")?,
        channel_type: row.try_get("channel_type")?,
        name: row.try_get("name")?,
        config: json_or_default(&row, "config")?,
        status: string_or_default(&row, "status", "pending")?,
        last_connected_at: row.try_get("last_connected_at")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
        deleted_at: row.try_get("deleted_at")?,
    })
}

fn instance_member_from_row(row: PgRow) -> Result<InstanceMemberRecord, sqlx::Error> {
    Ok(InstanceMemberRecord {
        id: row.try_get("id")?,
        instance_id: row.try_get("instance_id")?,
        user_id: row.try_get("user_id")?,
        role: string_or_default(&row, "role", "viewer")?,
        user_name: row.try_get("user_name")?,
        user_email: row.try_get("user_email")?,
        created_at: row.try_get("created_at")?,
    })
}

fn instance_user_search_from_row(row: PgRow) -> Result<InstanceUserSearchRecord, sqlx::Error> {
    Ok(InstanceUserSearchRecord {
        id: row.try_get("id")?,
        email: row.try_get("email")?,
        full_name: row.try_get("full_name")?,
    })
}
