//! Adapter over Python-owned `graph_stores` and `retrieval_stores`.
//!
//! The Rust strangler owns list/detail projections plus metadata CRUD. Live
//! connection tests remain Python-owned because they probe provider backends.

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_adapters_secrets::{
    try_decrypt_python_aes256_gcm, try_encrypt_python_aes256_gcm, try_generate_uuid_v4,
};
use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const STORE_COLS: &str = "id, tenant_id, name, engine_type, connection_config_encrypted, \
    index_config, status, health_status, detected_version, created_at, updated_at";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BackendStoreKind {
    Graph,
    Retrieval,
}

impl BackendStoreKind {
    fn table(self) -> &'static str {
        match self {
            Self::Graph => "graph_stores",
            Self::Retrieval => "retrieval_stores",
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Graph => "graph store",
            Self::Retrieval => "retrieval store",
        }
    }

    fn project_binding_column(self) -> &'static str {
        match self {
            Self::Graph => "graph_store_id",
            Self::Retrieval => "retrieval_store_id",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BackendStoreRecord {
    pub id: String,
    pub tenant_id: String,
    pub name: String,
    pub engine_type: String,
    pub connection_config_json: serde_json::Value,
    pub index_config_json: serde_json::Value,
    pub status: String,
    pub health_status: Option<String>,
    pub detected_version: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BackendStoreCreate {
    pub tenant_id: String,
    pub name: String,
    pub engine_type: String,
    pub connection_config_json: serde_json::Value,
    pub index_config_json: serde_json::Value,
    pub created_by: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BackendStoreUpdate {
    pub name: Option<String>,
    pub connection_config_json: Option<serde_json::Value>,
    pub index_config_json: Option<serde_json::Value>,
}

pub struct PgGraphStoreRepository {
    inner: PgBackendStoreRepository,
}

impl PgGraphStoreRepository {
    pub fn new(pool: PgPool) -> Self {
        Self {
            inner: PgBackendStoreRepository::new(pool, BackendStoreKind::Graph),
        }
    }

    pub async fn list_stores(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<BackendStoreRecord>> {
        self.inner.list_stores(tenant_id, limit, offset).await
    }

    pub async fn get_store(
        &self,
        tenant_id: &str,
        store_id: &str,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        self.inner.get_store(tenant_id, store_id).await
    }

    pub async fn find_by_name(
        &self,
        tenant_id: &str,
        name: &str,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        self.inner.find_by_name(tenant_id, name).await
    }

    pub async fn create_store(&self, input: BackendStoreCreate) -> CoreResult<BackendStoreRecord> {
        self.inner.create_store(input).await
    }

    pub async fn update_store(
        &self,
        tenant_id: &str,
        store_id: &str,
        patch: BackendStoreUpdate,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        self.inner.update_store(tenant_id, store_id, patch).await
    }

    pub async fn count_projects_bound(&self, store_id: &str) -> CoreResult<i64> {
        self.inner.count_projects_bound(store_id).await
    }

    pub async fn soft_delete(&self, tenant_id: &str, store_id: &str) -> CoreResult<bool> {
        self.inner.soft_delete(tenant_id, store_id).await
    }

    pub async fn resolve_selected_tenant(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> CoreResult<Result<String, BackendStoreAccessError>> {
        self.inner.resolve_selected_tenant(user_id, tenant_id).await
    }

    pub async fn resolve_selected_tenant_for_admin(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> CoreResult<Result<String, BackendStoreAccessError>> {
        self.inner
            .resolve_selected_tenant_for_admin(user_id, tenant_id)
            .await
    }
}

pub struct PgRetrievalStoreRepository {
    inner: PgBackendStoreRepository,
}

impl PgRetrievalStoreRepository {
    pub fn new(pool: PgPool) -> Self {
        Self {
            inner: PgBackendStoreRepository::new(pool, BackendStoreKind::Retrieval),
        }
    }

    pub async fn list_stores(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<BackendStoreRecord>> {
        self.inner.list_stores(tenant_id, limit, offset).await
    }

    pub async fn get_store(
        &self,
        tenant_id: &str,
        store_id: &str,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        self.inner.get_store(tenant_id, store_id).await
    }

    pub async fn find_by_name(
        &self,
        tenant_id: &str,
        name: &str,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        self.inner.find_by_name(tenant_id, name).await
    }

    pub async fn create_store(&self, input: BackendStoreCreate) -> CoreResult<BackendStoreRecord> {
        self.inner.create_store(input).await
    }

    pub async fn update_store(
        &self,
        tenant_id: &str,
        store_id: &str,
        patch: BackendStoreUpdate,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        self.inner.update_store(tenant_id, store_id, patch).await
    }

    pub async fn count_projects_bound(&self, store_id: &str) -> CoreResult<i64> {
        self.inner.count_projects_bound(store_id).await
    }

    pub async fn soft_delete(&self, tenant_id: &str, store_id: &str) -> CoreResult<bool> {
        self.inner.soft_delete(tenant_id, store_id).await
    }

    pub async fn resolve_selected_tenant(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> CoreResult<Result<String, BackendStoreAccessError>> {
        self.inner.resolve_selected_tenant(user_id, tenant_id).await
    }

    pub async fn resolve_selected_tenant_for_admin(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> CoreResult<Result<String, BackendStoreAccessError>> {
        self.inner
            .resolve_selected_tenant_for_admin(user_id, tenant_id)
            .await
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BackendStoreAccessError {
    TenantNotFound,
    TenantAccessRequired,
    AdminAccessRequired,
    UserHasNoTenant,
}

struct PgBackendStoreRepository {
    pool: PgPool,
    kind: BackendStoreKind,
}

impl PgBackendStoreRepository {
    fn new(pool: PgPool, kind: BackendStoreKind) -> Self {
        Self { pool, kind }
    }

    async fn list_stores(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<BackendStoreRecord>> {
        let sql = format!(
            "SELECT {STORE_COLS} \
             FROM {} \
             WHERE tenant_id = $1 AND deleted_at IS NULL \
             ORDER BY created_at DESC, id ASC \
             OFFSET $2 LIMIT $3",
            self.kind.table()
        );
        let rows = sqlx::query(&sql)
            .bind(tenant_id)
            .bind(offset)
            .bind(limit)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list {}s: {e}", self.kind.label())))?;
        rows.into_iter()
            .map(|row| self.record_from_row(row))
            .collect()
    }

    async fn get_store(
        &self,
        tenant_id: &str,
        store_id: &str,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        let sql = format!(
            "SELECT {STORE_COLS} \
             FROM {} \
             WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL \
             LIMIT 1",
            self.kind.table()
        );
        let row = sqlx::query(&sql)
            .bind(store_id)
            .bind(tenant_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get {}: {e}", self.kind.label())))?;
        row.map(|row| self.record_from_row(row)).transpose()
    }

    async fn find_by_name(
        &self,
        tenant_id: &str,
        name: &str,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        let sql = format!(
            "SELECT {STORE_COLS} \
             FROM {} \
             WHERE tenant_id = $1 AND name = $2 AND deleted_at IS NULL \
             LIMIT 1",
            self.kind.table()
        );
        let row = sqlx::query(&sql)
            .bind(tenant_id)
            .bind(name)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("find {} by name: {e}", self.kind.label())))?;
        row.map(|row| self.record_from_row(row)).transpose()
    }

    async fn create_store(&self, input: BackendStoreCreate) -> CoreResult<BackendStoreRecord> {
        let id = try_generate_uuid_v4()
            .map_err(|e| CoreError::Storage(format!("generate {} id: {e}", self.kind.label())))?;
        let encrypted_config = encrypt_connection_config(&input.connection_config_json)?;
        let sql = format!(
            "INSERT INTO {} \
             (id, tenant_id, name, engine_type, connection_config_encrypted, index_config, \
              status, created_by) \
             VALUES ($1, $2, $3, $4, $5, $6, 'disconnected', $7) \
             RETURNING {STORE_COLS}",
            self.kind.table()
        );
        let row = sqlx::query(&sql)
            .bind(id)
            .bind(input.tenant_id)
            .bind(input.name)
            .bind(input.engine_type)
            .bind(encrypted_config)
            .bind(input.index_config_json)
            .bind(input.created_by)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("create {}: {e}", self.kind.label())))?;
        self.record_from_row(row)
    }

    async fn update_store(
        &self,
        tenant_id: &str,
        store_id: &str,
        patch: BackendStoreUpdate,
    ) -> CoreResult<Option<BackendStoreRecord>> {
        let update_connection_config = patch.connection_config_json.is_some();
        let encrypted_config = patch
            .connection_config_json
            .as_ref()
            .map(encrypt_connection_config)
            .transpose()?
            .flatten();
        let update_index_config = patch.index_config_json.is_some();
        let sql = format!(
            "UPDATE {} SET \
                name = CASE WHEN $3 THEN $4 ELSE name END, \
                connection_config_encrypted = CASE WHEN $5 THEN $6 ELSE connection_config_encrypted END, \
                index_config = CASE WHEN $7 THEN $8 ELSE index_config END, \
                updated_at = now() \
             WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL \
             RETURNING {STORE_COLS}",
            self.kind.table()
        );
        let row = sqlx::query(&sql)
            .bind(store_id)
            .bind(tenant_id)
            .bind(patch.name.is_some())
            .bind(patch.name)
            .bind(update_connection_config)
            .bind(encrypted_config)
            .bind(update_index_config)
            .bind(patch.index_config_json)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("update {}: {e}", self.kind.label())))?;
        row.map(|row| self.record_from_row(row)).transpose()
    }

    async fn count_projects_bound(&self, store_id: &str) -> CoreResult<i64> {
        let column = self.kind.project_binding_column();
        let sql =
            format!("SELECT count(*) FROM projects WHERE {column} = $1 AND {column} IS NOT NULL");
        sqlx::query_as::<_, (i64,)>(&sql)
            .bind(store_id)
            .fetch_one(&self.pool)
            .await
            .map(|(count,)| count)
            .map_err(|e| {
                CoreError::Storage(format!("count bound {} projects: {e}", self.kind.label()))
            })
    }

    async fn soft_delete(&self, tenant_id: &str, store_id: &str) -> CoreResult<bool> {
        let sql = format!(
            "UPDATE {} SET deleted_at = now() \
             WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
            self.kind.table()
        );
        let result = sqlx::query(&sql)
            .bind(store_id)
            .bind(tenant_id)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("delete {}: {e}", self.kind.label())))?;
        Ok(result.rows_affected() > 0)
    }

    async fn resolve_selected_tenant(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> CoreResult<Result<String, BackendStoreAccessError>> {
        if let Some(tenant_id) = tenant_id.filter(|value| !value.is_empty()) {
            if !self.tenant_exists(tenant_id).await? {
                return Ok(Err(BackendStoreAccessError::TenantNotFound));
            }
            if self.user_has_global_admin(user_id).await?
                || self.user_tenant_role(user_id, tenant_id).await?.is_some()
            {
                return Ok(Ok(tenant_id.to_string()));
            }
            return Ok(Err(BackendStoreAccessError::TenantAccessRequired));
        }

        match self.default_tenant_for_user(user_id).await? {
            Some(tenant_id) => Ok(Ok(tenant_id)),
            None => Ok(Err(BackendStoreAccessError::UserHasNoTenant)),
        }
    }

    async fn resolve_selected_tenant_for_admin(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> CoreResult<Result<String, BackendStoreAccessError>> {
        let selected_tenant = match tenant_id.filter(|value| !value.is_empty()) {
            Some(tenant_id) => {
                if !self.tenant_exists(tenant_id).await? {
                    return Ok(Err(BackendStoreAccessError::TenantNotFound));
                }
                tenant_id.to_string()
            }
            None => match self.default_tenant_for_user(user_id).await? {
                Some(tenant_id) => tenant_id,
                None => return Ok(Err(BackendStoreAccessError::UserHasNoTenant)),
            },
        };

        if self.user_has_global_admin(user_id).await? {
            return Ok(Ok(selected_tenant));
        }

        match self.user_tenant_role(user_id, &selected_tenant).await? {
            Some(role) if role == "admin" || role == "owner" => Ok(Ok(selected_tenant)),
            Some(_) => Ok(Err(BackendStoreAccessError::AdminAccessRequired)),
            None => Ok(Err(BackendStoreAccessError::TenantAccessRequired)),
        }
    }

    async fn tenant_exists(&self, tenant_id: &str) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM tenants WHERE id = $1")
            .bind(tenant_id)
            .fetch_one(&self.pool)
            .await
            .map(|(count,)| count > 0)
            .map_err(|e| CoreError::Storage(format!("read backend store tenant: {e}")))
    }

    async fn user_has_global_admin(&self, user_id: &str) -> CoreResult<bool> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(is_superuser,)| is_superuser).unwrap_or(false))
        .map_err(|e| CoreError::Storage(format!("read backend store user superuser: {e}")))?;
        if is_superuser {
            return Ok(true);
        }

        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM user_roles \
             JOIN roles ON roles.id = user_roles.role_id \
             WHERE user_roles.user_id = $1 \
               AND user_roles.tenant_id IS NULL \
               AND roles.name = $2",
        )
        .bind(user_id)
        .bind("system_admin")
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read backend store user roles: {e}")))
    }

    async fn user_tenant_role(&self, user_id: &str, tenant_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT role FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(role,)| role))
        .map_err(|e| CoreError::Storage(format!("read backend store tenant role: {e}")))
    }

    async fn default_tenant_for_user(&self, user_id: &str) -> CoreResult<Option<String>> {
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
        .map_err(|e| CoreError::Storage(format!("read backend store default tenant: {e}")))
    }

    fn record_from_row(&self, row: sqlx::postgres::PgRow) -> CoreResult<BackendStoreRecord> {
        let encrypted_config: Option<String> =
            row.try_get("connection_config_encrypted").map_err(|e| {
                CoreError::Storage(format!("read {} encrypted config: {e}", self.kind.label()))
            })?;
        let connection_config_json = decrypt_connection_config(encrypted_config.as_deref());
        Ok(BackendStoreRecord {
            id: row.try_get("id").map_err(row_error)?,
            tenant_id: row.try_get("tenant_id").map_err(row_error)?,
            name: row.try_get("name").map_err(row_error)?,
            engine_type: row.try_get("engine_type").map_err(row_error)?,
            connection_config_json,
            index_config_json: row
                .try_get::<Option<serde_json::Value>, _>("index_config")
                .map_err(row_error)?
                .unwrap_or_else(|| serde_json::json!({})),
            status: row.try_get("status").map_err(row_error)?,
            health_status: row.try_get("health_status").map_err(row_error)?,
            detected_version: row.try_get("detected_version").map_err(row_error)?,
            created_at: row.try_get("created_at").map_err(row_error)?,
            updated_at: row.try_get("updated_at").map_err(row_error)?,
        })
    }
}

fn decrypt_connection_config(encrypted: Option<&str>) -> serde_json::Value {
    let Some(encrypted) = encrypted.filter(|value| !value.is_empty()) else {
        return serde_json::json!({});
    };
    let Ok(key) = std::env::var("LLM_ENCRYPTION_KEY") else {
        return serde_json::json!({});
    };
    let Ok(plaintext) = try_decrypt_python_aes256_gcm(encrypted, &key) else {
        return serde_json::json!({});
    };
    serde_json::from_str(&plaintext).unwrap_or_else(|_| serde_json::json!({}))
}

fn encrypt_connection_config(config: &serde_json::Value) -> CoreResult<Option<String>> {
    let empty_object = matches!(config, serde_json::Value::Object(values) if values.is_empty());
    if config.is_null() || empty_object {
        return Ok(None);
    }
    let key = std::env::var("LLM_ENCRYPTION_KEY").map_err(|_| {
        CoreError::Storage(
            "LLM_ENCRYPTION_KEY is required to encrypt backend store config".to_string(),
        )
    })?;
    let plaintext = serde_json::to_string(config)
        .map_err(|e| CoreError::Storage(format!("serialize backend store config: {e}")))?;
    try_encrypt_python_aes256_gcm(&plaintext, &key)
        .map(Some)
        .map_err(|e| CoreError::Storage(format!("encrypt backend store config: {e}")))
}

fn row_error(err: sqlx::Error) -> CoreError {
    CoreError::Storage(format!("read backend store row: {err}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decrypt_config_matches_python_shape() {
        std::env::set_var(
            "LLM_ENCRYPTION_KEY",
            "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
        );
        let encrypted = concat!(
            "AAECAwQFBgcICQoLPCCjaazH+DnvLvv/i8ZXCeH44kyRFi8QXV3SsyVeIp4jYM+P",
            "3LZ96hCGRc/74ktKiy1CoXi4xqlL8k47IpjXj4BVmRG2qARbPj+IE5IaTk/sVMQFT2DgtWaO9PXs"
        );
        let value = decrypt_connection_config(Some(encrypted));
        assert_eq!(value["uri"], "bolt://db.example:7687");
        assert_eq!(value["password"], "secret");
    }

    #[test]
    fn decrypt_config_falls_back_to_empty_object_like_python_repo() {
        std::env::remove_var("LLM_ENCRYPTION_KEY");
        assert_eq!(decrypt_connection_config(None), serde_json::json!({}));
        assert_eq!(decrypt_connection_config(Some("")), serde_json::json!({}));
        assert_eq!(
            decrypt_connection_config(Some("not-base64")),
            serde_json::json!({})
        );
    }

    #[test]
    fn encrypt_config_matches_python_decrypt_shape() {
        std::env::set_var(
            "LLM_ENCRYPTION_KEY",
            "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
        );
        let value = serde_json::json!({
            "uri": "bolt://db.example:7687",
            "password": "secret"
        });
        let encrypted = encrypt_connection_config(&value)
            .expect("encrypt succeeds")
            .expect("non-empty config encrypts");
        assert_eq!(decrypt_connection_config(Some(&encrypted)), value);
        assert_eq!(
            encrypt_connection_config(&serde_json::json!({})).unwrap(),
            None
        );
    }
}
