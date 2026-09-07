//! Locks coexist across the outer side-effect lease and inner SQL transaction.
use std::sync::Mutex;
use std::time::Duration;

use super::{storage_err, PgPool};
use agistack_core::ports::legacy_memory::{
    LegacyMemoryScope, LegacyMemoryWriteError, LegacyMemoryWriteLease,
};
use agistack_core::ports::CoreResult;
use sqlx::{Postgres, Transaction};

pub(super) struct PgWriteLease {
    scope: LegacyMemoryScope,
    // SQLx queues rollback on drop, including task cancellation.
    _transaction: Mutex<Transaction<'static, Postgres>>,
}
impl LegacyMemoryWriteLease for PgWriteLease {
    fn scope(&self) -> &LegacyMemoryScope {
        &self.scope
    }
}

pub(super) async fn admission_pool(pool: &PgPool) -> CoreResult<PgPool> {
    let (role, search_path): (String, String) =
        sqlx::query_as("SELECT current_user::text, current_setting('search_path')")
            .fetch_one(pool)
            .await
            .map_err(storage_err)?;
    sqlx::postgres::PgPoolOptions::new()
        .max_connections(4)
        .min_connections(0)
        .acquire_timeout(Duration::from_secs(30))
        .after_connect(move |connection, _| {
            let role = role.clone();
            let search_path = search_path.clone();
            Box::pin(async move {
                sqlx::query(
                    "SELECT set_config('role', $1, false), set_config('search_path', $2, false)",
                )
                .bind(role)
                .bind(search_path)
                .execute(connection)
                .await?;
                Ok(())
            })
        })
        .connect_with((*pool.connect_options()).clone())
        .await
        .map_err(storage_err)
}

pub(super) async fn lease(
    pool: &PgPool,
    project: &str,
    memory: Option<&str>,
) -> CoreResult<Box<dyn LegacyMemoryWriteLease>> {
    let mut transaction = pool
        .begin()
        .await
        .map_err(|_| LegacyMemoryWriteError::Unavailable)?;
    let scope = check(&mut transaction, Some(project), memory).await?;
    Ok(Box::new(PgWriteLease {
        scope,
        _transaction: Mutex::new(transaction),
    }))
}

pub(super) async fn check(
    transaction: &mut Transaction<'_, Postgres>,
    requested_project: Option<&str>,
    memory: Option<&str>,
) -> CoreResult<LegacyMemoryScope> {
    let actual: Option<String> = if let Some(id) = memory {
        sqlx::query_scalar("SELECT project_id FROM memories WHERE id = $1 UNION ALL SELECT project_id FROM knowledge_sync_tombstones WHERE memory_id = $1 LIMIT 1")
            .bind(id).fetch_optional(&mut **transaction).await.map_err(storage_err)?
    } else {
        None
    };
    if actual
        .as_deref()
        .zip(requested_project)
        .is_some_and(|(a, b)| a != b)
    {
        return Err(LegacyMemoryWriteError::Conflict.into());
    }
    let project = actual
        .as_deref()
        .or(requested_project)
        .ok_or(LegacyMemoryWriteError::NotFound)?;
    let tenant: String =
        sqlx::query_scalar("SELECT tenant_id FROM projects WHERE id = $1 FOR SHARE")
            .bind(project)
            .fetch_optional(&mut **transaction)
            .await
            .map_err(storage_err)?
            .ok_or(LegacyMemoryWriteError::Forbidden)?;
    let (enrollment_tenant, enabled): (String, bool) = sqlx::query_as(
        "SELECT tenant_id, enabled FROM knowledge_sync_enrollments WHERE project_id = $1 FOR SHARE",
    )
    .bind(project)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(storage_err)?
    .ok_or(LegacyMemoryWriteError::FenceMissing)?;
    if enrollment_tenant != tenant {
        return Err(LegacyMemoryWriteError::Forbidden.into());
    }
    if enabled {
        return Err(LegacyMemoryWriteError::ContextRequired.into());
    }
    if let Some(id) = memory {
        let current: Option<String> =
            sqlx::query_scalar("SELECT project_id FROM memories WHERE id = $1")
                .bind(id)
                .fetch_optional(&mut **transaction)
                .await
                .map_err(storage_err)?;
        if current.as_deref().is_some_and(|current| current != project) {
            return Err(LegacyMemoryWriteError::Conflict.into());
        }
    }
    Ok(LegacyMemoryScope {
        project_id: project.to_owned(),
        tenant_id: Some(tenant),
    })
}
