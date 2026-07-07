//! Small read-side adapter for global admin checks used by admin-only Rust
//! strangler slices.

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

pub struct PgAdminAccessRepository {
    pool: PgPool,
}

impl PgAdminAccessRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn user_has_admin_access(&self, user_id: &str) -> CoreResult<bool> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(is_superuser,)| is_superuser).unwrap_or(false))
        .map_err(|e| CoreError::Storage(format!("read admin user superuser: {e}")))?;
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
        .map_err(|e| CoreError::Storage(format!("read admin user roles: {e}")))
    }
}
