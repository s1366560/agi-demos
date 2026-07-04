use serde_json::Value;

use agistack_core::ports::{CoreError, CoreResult};

use super::read::{row_to_member, PROJECT_MEMBERS_SQL};
use super::{
    is_python_uuid_like, PgProjectReadRepository, ProjectMemberMutationRecord,
    ProjectMembersLookup, ProjectMembersRecord,
};

impl PgProjectReadRepository {
    pub async fn members_for_user(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> CoreResult<ProjectMembersLookup> {
        let exists = sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM projects WHERE id = $1")
            .bind(project_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        if exists.0 == 0 {
            if !is_python_uuid_like(project_id) {
                return Ok(ProjectMembersLookup::InvalidId);
            }
            return Ok(ProjectMembersLookup::NotFound);
        }

        let membership = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects WHERE user_id = $1 AND project_id = $2",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        if membership.0 == 0 {
            return Ok(ProjectMembersLookup::Forbidden);
        }

        let rows = sqlx::query(PROJECT_MEMBERS_SQL)
            .bind(project_id)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let members = rows
            .into_iter()
            .map(row_to_member)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(ProjectMembersLookup::Found(ProjectMembersRecord {
            total: members.len() as i64,
            members,
        }))
    }

    pub async fn user_is_project_admin(&self, user_id: &str, project_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects \
             WHERE user_id = $1 AND project_id = $2 AND role IN ('owner', 'admin')",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn user_is_project_owner(&self, user_id: &str, project_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects \
             WHERE user_id = $1 AND project_id = $2 AND role = 'owner'",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn user_is_tenant_project_admin(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants \
             WHERE user_id = $1 AND tenant_id = $2 AND role IN ('owner', 'admin')",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn project_exists(&self, project_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM projects WHERE id = $1")
            .bind(project_id)
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

    pub async fn project_member_role(
        &self,
        project_id: &str,
        user_id: &str,
    ) -> CoreResult<Option<ProjectMemberMutationRecord>> {
        let row = sqlx::query_as::<_, (String,)>(
            "SELECT COALESCE(role, 'member') FROM user_projects \
             WHERE project_id = $1 AND user_id = $2",
        )
        .bind(project_id)
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.map(|(role,)| ProjectMemberMutationRecord { role }))
    }

    pub async fn add_project_member(
        &self,
        id: &str,
        project_id: &str,
        user_id: &str,
        role: &str,
        permissions: &Value,
    ) -> CoreResult<()> {
        sqlx::query(
            "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
             VALUES ($1, $2, $3, $4, $5)",
        )
        .bind(id)
        .bind(user_id)
        .bind(project_id)
        .bind(role)
        .bind(permissions)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }

    pub async fn update_project_member(
        &self,
        project_id: &str,
        user_id: &str,
        role: &str,
        permissions: &Value,
    ) -> CoreResult<bool> {
        let result = sqlx::query(
            "UPDATE user_projects SET role = $1, permissions = $2 \
             WHERE project_id = $3 AND user_id = $4",
        )
        .bind(role)
        .bind(permissions)
        .bind(project_id)
        .bind(user_id)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn remove_project_member(&self, project_id: &str, user_id: &str) -> CoreResult<bool> {
        let result =
            sqlx::query("DELETE FROM user_projects WHERE project_id = $1 AND user_id = $2")
                .bind(project_id)
                .bind(user_id)
                .execute(&self.pool)
                .await
                .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }
}
