//! Scope resolver for Rust-owned data export/stats/cleanup routes.
//!
//! Rust owns exact `GET /api/v1/data/stats`, `POST /api/v1/data/export`, and
//! `POST /api/v1/data/cleanup`.

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DataStatsAccess {
    AllProjects,
    ProjectIds(Vec<String>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DataStatsScopeRecord {
    pub tenant_id: Option<String>,
    pub project_id: Option<String>,
    pub access: DataStatsAccess,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DataStatsScopeError {
    ProjectNotFound,
    ProjectTenantMismatch,
    ProjectAccessRequired,
    TenantAccessRequired,
    AdminAccessRequired,
}

pub struct PgDataStatsRepository {
    pool: PgPool,
}

impl PgDataStatsRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn resolve_scope(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        project_id: Option<&str>,
    ) -> CoreResult<Result<DataStatsScopeRecord, DataStatsScopeError>> {
        self.resolve_scope_with_admin_requirement(user_id, tenant_id, project_id, false)
            .await
    }

    pub async fn resolve_scope_with_admin_requirement(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        project_id: Option<&str>,
        require_admin: bool,
    ) -> CoreResult<Result<DataStatsScopeRecord, DataStatsScopeError>> {
        let is_admin = self.user_has_global_admin(user_id).await?;
        if let Some(project_id) = project_id {
            let project_tenant_id = match self.project_tenant_id(project_id).await? {
                Some(tenant_id) => tenant_id,
                None => return Ok(Err(DataStatsScopeError::ProjectNotFound)),
            };
            if let Some(requested_tenant_id) = tenant_id {
                if requested_tenant_id != project_tenant_id.as_str() {
                    return Ok(Err(DataStatsScopeError::ProjectTenantMismatch));
                }
            }
            if !is_admin
                && !self
                    .user_has_project_access(user_id, project_id, require_admin)
                    .await?
            {
                return Ok(Err(DataStatsScopeError::ProjectAccessRequired));
            }
            return Ok(Ok(DataStatsScopeRecord {
                tenant_id: Some(project_tenant_id),
                project_id: Some(project_id.to_string()),
                access: DataStatsAccess::ProjectIds(vec![project_id.to_string()]),
            }));
        }

        if is_admin {
            let project_ids = match tenant_id {
                Some(tenant_id) => self.project_ids_for_tenant(tenant_id).await?,
                None => Vec::new(),
            };
            return Ok(Ok(DataStatsScopeRecord {
                tenant_id: tenant_id.map(str::to_string),
                project_id: None,
                access: if tenant_id.is_some() {
                    DataStatsAccess::ProjectIds(project_ids)
                } else {
                    DataStatsAccess::AllProjects
                },
            }));
        }

        let effective_tenant_id = match tenant_id {
            Some(tenant_id) => tenant_id.to_string(),
            None => match self.default_tenant_for_user(user_id).await? {
                Some(tenant_id) => tenant_id,
                None => return Ok(Err(DataStatsScopeError::TenantAccessRequired)),
            },
        };
        match self.tenant_role(user_id, &effective_tenant_id).await? {
            Some(role) if !require_admin || role == "admin" || role == "owner" => {}
            Some(_) => return Ok(Err(DataStatsScopeError::AdminAccessRequired)),
            None => return Ok(Err(DataStatsScopeError::TenantAccessRequired)),
        }
        Ok(Ok(DataStatsScopeRecord {
            project_id: None,
            access: DataStatsAccess::ProjectIds(
                self.project_ids_for_tenant(&effective_tenant_id).await?,
            ),
            tenant_id: Some(effective_tenant_id),
        }))
    }

    async fn user_has_global_admin(&self, user_id: &str) -> CoreResult<bool> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(is_superuser,)| is_superuser).unwrap_or(false))
        .map_err(|e| CoreError::Storage(format!("read data stats user superuser: {e}")))?;
        if is_superuser {
            return Ok(true);
        }

        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM user_roles \
             JOIN roles ON roles.id = user_roles.role_id \
             WHERE user_roles.user_id = $1 \
               AND roles.name = ANY($2::text[])",
        )
        .bind(user_id)
        .bind(vec!["admin", "system_admin", "super_admin"])
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read data stats user roles: {e}")))
    }

    async fn default_tenant_for_user(&self, user_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id \
             FROM user_tenants \
             WHERE user_id = $1 \
             ORDER BY created_at ASC, tenant_id ASC \
             LIMIT 1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(tenant_id,)| tenant_id))
        .map_err(|e| CoreError::Storage(format!("read data stats default tenant: {e}")))
    }

    async fn tenant_role(&self, user_id: &str, tenant_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT role FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(role,)| role))
        .map_err(|e| CoreError::Storage(format!("read data stats tenant role: {e}")))
    }

    async fn user_has_project_access(
        &self,
        user_id: &str,
        project_id: &str,
        require_admin: bool,
    ) -> CoreResult<bool> {
        let mut query =
            "SELECT count(*) FROM user_projects WHERE user_id = $1 AND project_id = $2".to_string();
        if require_admin {
            query.push_str(" AND role = ANY($3::text[])");
        }
        let mut query = sqlx::query_as::<_, (i64,)>(&query)
            .bind(user_id)
            .bind(project_id);
        if require_admin {
            query = query.bind(vec!["owner", "admin"]);
        }
        query
            .fetch_one(&self.pool)
            .await
            .map(|(count,)| count > 0)
            .map_err(|e| CoreError::Storage(format!("read data stats project access: {e}")))
    }

    async fn project_tenant_id(&self, project_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>("SELECT tenant_id FROM projects WHERE id = $1")
            .bind(project_id)
            .fetch_optional(&self.pool)
            .await
            .map(|row| row.map(|(tenant_id,)| tenant_id))
            .map_err(|e| CoreError::Storage(format!("read data stats project tenant: {e}")))
    }

    async fn project_ids_for_tenant(&self, tenant_id: &str) -> CoreResult<Vec<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT id FROM projects WHERE tenant_id = $1 ORDER BY created_at ASC, id ASC",
        )
        .bind(tenant_id)
        .fetch_all(&self.pool)
        .await
        .map(|rows| rows.into_iter().map(|(id,)| id).collect())
        .map_err(|e| CoreError::Storage(format!("read data stats tenant projects: {e}")))
    }
}
