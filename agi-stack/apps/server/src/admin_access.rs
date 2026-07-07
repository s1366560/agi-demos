//! Shared admin-access gate for exact admin-only strangler slices.

use std::sync::Arc;

use async_trait::async_trait;

use agistack_adapters_postgres::{PgAdminAccessRepository, PgPool};

pub(crate) type SharedAdminAccess = Arc<dyn AdminAccessService>;

#[async_trait]
pub(crate) trait AdminAccessService: Send + Sync {
    async fn user_has_admin_access(&self, user_id: &str) -> Result<bool, String>;
}

pub(crate) struct PgAdminAccessService {
    repo: PgAdminAccessRepository,
}

impl PgAdminAccessService {
    pub(crate) fn new(repo: PgAdminAccessRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl AdminAccessService for PgAdminAccessService {
    async fn user_has_admin_access(&self, user_id: &str) -> Result<bool, String> {
        self.repo
            .user_has_admin_access(user_id)
            .await
            .map_err(|err| err.to_string())
    }
}

pub(crate) struct DevAdminAccessService {
    admin_user_id: String,
}

impl DevAdminAccessService {
    pub(crate) fn new(admin_user_id: impl Into<String>) -> Self {
        Self {
            admin_user_id: admin_user_id.into(),
        }
    }
}

#[async_trait]
impl AdminAccessService for DevAdminAccessService {
    async fn user_has_admin_access(&self, user_id: &str) -> Result<bool, String> {
        Ok(user_id == self.admin_user_id)
    }
}

pub(crate) fn build_admin_access(pool: Option<PgPool>) -> SharedAdminAccess {
    match pool {
        Some(pool) => Arc::new(PgAdminAccessService::new(PgAdminAccessRepository::new(
            pool,
        ))),
        None => Arc::new(DevAdminAccessService::new("dev-user")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn dev_admin_access_is_exact_user_match() {
        let access = DevAdminAccessService::new("admin-user");

        assert!(access
            .user_has_admin_access("admin-user")
            .await
            .expect("admin check succeeds"));
        assert!(!access
            .user_has_admin_access("regular-user")
            .await
            .expect("regular check succeeds"));
    }
}
