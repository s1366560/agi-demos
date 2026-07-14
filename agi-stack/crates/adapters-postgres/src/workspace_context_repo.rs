//! Authoritative per-user tenant/project context with revision fencing.

use std::fmt;

use agistack_adapters_secrets::try_generate_uuid_v4;
use serde_json::json;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::{Postgres, Transaction};

use crate::PgPool;

const CONTEXT_LOCK_SEED: i64 = 0x41_47_49_43;
const LOCK_CONTEXT_SQL: &str = "SELECT pg_advisory_xact_lock(hashtextextended($1, $2))";
const LOAD_CONTEXT_SQL: &str = "SELECT context.tenant_id, context.project_id, \
    context.revision, context.updated_at, \
    COALESCE((SELECT membership.role FROM user_tenants AS membership \
              WHERE membership.user_id = context.user_id \
                AND membership.tenant_id = context.tenant_id \
              ORDER BY membership.created_at ASC, membership.id ASC LIMIT 1), 'member') \
        AS membership_role, \
    EXISTS(SELECT 1 FROM user_tenants AS membership \
           WHERE membership.user_id = context.user_id \
             AND membership.tenant_id = context.tenant_id) \
    AND EXISTS(SELECT 1 FROM user_projects AS access \
               JOIN projects AS project ON project.id = access.project_id \
               WHERE access.user_id = context.user_id \
                 AND access.project_id = context.project_id \
                 AND project.tenant_id = context.tenant_id) AS accessible \
    FROM agistack_desktop_workspace_contexts AS context \
    WHERE context.user_id = $1 FOR UPDATE OF context";
const LOAD_DEFAULT_SCOPE_SQL: &str = "SELECT project.tenant_id, project.id AS project_id, \
    COALESCE(membership.role, 'member') AS membership_role \
    FROM user_tenants AS membership \
    JOIN tenants AS tenant ON tenant.id = membership.tenant_id \
    JOIN projects AS project ON project.tenant_id = tenant.id \
    JOIN user_projects AS access ON access.project_id = project.id \
                                AND access.user_id = membership.user_id \
    WHERE membership.user_id = $1 \
    ORDER BY membership.created_at ASC, membership.id ASC, tenant.id ASC, \
             CASE WHEN project.name IN ('Default project', '默认项目') THEN 0 ELSE 1 END ASC, \
             project.created_at DESC, project.id ASC \
    LIMIT 1";
const LOAD_EVENT_SQL: &str = "SELECT to_tenant_id AS tenant_id, \
    to_project_id AS project_id, revision, created_at AS updated_at \
    FROM agistack_desktop_workspace_context_events \
    WHERE user_id = $1 AND idempotency_key = $2";

#[derive(Debug, Clone, PartialEq, Eq, sqlx::FromRow)]
pub struct WorkspaceContextSnapshotRecord {
    pub tenant_id: String,
    pub project_id: String,
    pub revision: i64,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextAccessRecord {
    pub context: WorkspaceContextSnapshotRecord,
    pub membership_role: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextSwitchRecord {
    pub context: WorkspaceContextSnapshotRecord,
    pub changed: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextSwitchRequest {
    pub tenant_id: String,
    pub project_id: String,
    pub expected_revision: i64,
    pub idempotency_key: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceContextRepositoryError {
    InvalidInput,
    NoAccessibleProject,
    TenantMembershipRequired,
    ProjectUnavailable,
    RevisionConflict { expected: i64, actual: i64 },
    IdempotencyConflict,
    RevisionExhausted,
    Storage(String),
}

impl fmt::Display for WorkspaceContextRepositoryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidInput => "workspace context input is invalid",
            Self::NoAccessibleProject => "no accessible workspace project exists",
            Self::TenantMembershipRequired => "workspace tenant membership is required",
            Self::ProjectUnavailable => "workspace project is unavailable",
            Self::RevisionConflict { .. } => "workspace context revision is stale",
            Self::IdempotencyConflict => "workspace context idempotency key conflicts",
            Self::RevisionExhausted => "workspace context revision is exhausted",
            Self::Storage(_) => "workspace context storage failed",
        })
    }
}

impl std::error::Error for WorkspaceContextRepositoryError {}

#[derive(Clone)]
pub struct PgWorkspaceContextRepository {
    pool: PgPool,
}

impl PgWorkspaceContextRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn get_or_initialize(
        &self,
        user_id: &str,
        observed_at: DateTime<Utc>,
    ) -> Result<WorkspaceContextAccessRecord, WorkspaceContextRepositoryError> {
        validate_user_id(user_id)?;
        let mut transaction = self.pool.begin().await.map_err(storage)?;
        lock_context(&mut transaction, user_id).await?;
        let current = load_context(&mut transaction, user_id).await?;
        if let Some(current) = current.as_ref().filter(|context| context.accessible) {
            let result = current.access_record();
            transaction.commit().await.map_err(storage)?;
            return Ok(result);
        }

        let candidate = load_default_scope(&mut transaction, user_id)
            .await?
            .ok_or(WorkspaceContextRepositoryError::NoAccessibleProject)?;
        let result = match current {
            Some(current) => {
                let revision = next_revision(current.revision)?;
                update_context(
                    &mut transaction,
                    user_id,
                    &candidate.tenant_id,
                    &candidate.project_id,
                    revision,
                    observed_at,
                )
                .await?;
                insert_event(
                    &mut transaction,
                    ContextEventInput {
                        user_id,
                        actor_api_key_id: None,
                        from_tenant_id: Some(&current.tenant_id),
                        from_project_id: Some(&current.project_id),
                        to_tenant_id: &candidate.tenant_id,
                        to_project_id: &candidate.project_id,
                        revision,
                        idempotency_key: &format!("system:workspace-context-repair:{revision}"),
                        observed_at,
                    },
                )
                .await?;
                candidate.access_record(revision, observed_at)
            }
            None => {
                let last_revision = load_last_event_revision(&mut transaction, user_id).await?;
                let revision = last_revision.map(next_revision).transpose()?.unwrap_or(0);
                insert_context(
                    &mut transaction,
                    user_id,
                    &candidate.tenant_id,
                    &candidate.project_id,
                    revision,
                    observed_at,
                )
                .await?;
                if last_revision.is_some() {
                    insert_event(
                        &mut transaction,
                        ContextEventInput {
                            user_id,
                            actor_api_key_id: None,
                            from_tenant_id: None,
                            from_project_id: None,
                            to_tenant_id: &candidate.tenant_id,
                            to_project_id: &candidate.project_id,
                            revision,
                            idempotency_key: &format!("system:workspace-context-repair:{revision}"),
                            observed_at,
                        },
                    )
                    .await?;
                }
                candidate.access_record(revision, observed_at)
            }
        };
        transaction.commit().await.map_err(storage)?;
        Ok(result)
    }

    pub async fn switch(
        &self,
        user_id: &str,
        actor_api_key_id: Option<&str>,
        request: &WorkspaceContextSwitchRequest,
        observed_at: DateTime<Utc>,
    ) -> Result<WorkspaceContextSwitchRecord, WorkspaceContextRepositoryError> {
        validate_switch(user_id, request)?;
        let mut transaction = self.pool.begin().await.map_err(storage)?;
        lock_context(&mut transaction, user_id).await?;
        if let Some(existing) =
            load_event(&mut transaction, user_id, &request.idempotency_key).await?
        {
            if existing.tenant_id != request.tenant_id || existing.project_id != request.project_id
            {
                return Err(WorkspaceContextRepositoryError::IdempotencyConflict);
            }
            transaction.commit().await.map_err(storage)?;
            return Ok(WorkspaceContextSwitchRecord {
                context: existing,
                changed: false,
            });
        }

        let current = load_context(&mut transaction, user_id).await?;
        let actual_revision = match current.as_ref() {
            Some(context) => context.revision,
            None => load_last_event_revision(&mut transaction, user_id)
                .await?
                .unwrap_or(0),
        };
        if request.expected_revision != actual_revision {
            return Err(WorkspaceContextRepositoryError::RevisionConflict {
                expected: request.expected_revision,
                actual: actual_revision,
            });
        }
        require_membership(&mut transaction, user_id, &request.tenant_id).await?;
        require_project(
            &mut transaction,
            user_id,
            &request.tenant_id,
            &request.project_id,
        )
        .await?;

        let revision = next_revision(actual_revision)?;
        match current.as_ref() {
            Some(_) => {
                update_context(
                    &mut transaction,
                    user_id,
                    &request.tenant_id,
                    &request.project_id,
                    revision,
                    observed_at,
                )
                .await?;
            }
            None => {
                insert_context(
                    &mut transaction,
                    user_id,
                    &request.tenant_id,
                    &request.project_id,
                    revision,
                    observed_at,
                )
                .await?;
            }
        }
        insert_event(
            &mut transaction,
            ContextEventInput {
                user_id,
                actor_api_key_id,
                from_tenant_id: current.as_ref().map(|context| context.tenant_id.as_str()),
                from_project_id: current.as_ref().map(|context| context.project_id.as_str()),
                to_tenant_id: &request.tenant_id,
                to_project_id: &request.project_id,
                revision,
                idempotency_key: &request.idempotency_key,
                observed_at,
            },
        )
        .await?;
        transaction.commit().await.map_err(storage)?;
        Ok(WorkspaceContextSwitchRecord {
            context: WorkspaceContextSnapshotRecord {
                tenant_id: request.tenant_id.clone(),
                project_id: request.project_id.clone(),
                revision,
                updated_at: observed_at,
            },
            changed: true,
        })
    }
}

#[derive(sqlx::FromRow)]
struct ContextRow {
    tenant_id: String,
    project_id: String,
    revision: i64,
    updated_at: DateTime<Utc>,
    membership_role: String,
    accessible: bool,
}

impl ContextRow {
    fn access_record(&self) -> WorkspaceContextAccessRecord {
        WorkspaceContextAccessRecord {
            context: WorkspaceContextSnapshotRecord {
                tenant_id: self.tenant_id.clone(),
                project_id: self.project_id.clone(),
                revision: self.revision,
                updated_at: self.updated_at,
            },
            membership_role: self.membership_role.clone(),
        }
    }
}

#[derive(sqlx::FromRow)]
struct DefaultScopeRow {
    tenant_id: String,
    project_id: String,
    membership_role: String,
}

impl DefaultScopeRow {
    fn access_record(
        &self,
        revision: i64,
        observed_at: DateTime<Utc>,
    ) -> WorkspaceContextAccessRecord {
        WorkspaceContextAccessRecord {
            context: WorkspaceContextSnapshotRecord {
                tenant_id: self.tenant_id.clone(),
                project_id: self.project_id.clone(),
                revision,
                updated_at: observed_at,
            },
            membership_role: self.membership_role.clone(),
        }
    }
}

struct ContextEventInput<'a> {
    user_id: &'a str,
    actor_api_key_id: Option<&'a str>,
    from_tenant_id: Option<&'a str>,
    from_project_id: Option<&'a str>,
    to_tenant_id: &'a str,
    to_project_id: &'a str,
    revision: i64,
    idempotency_key: &'a str,
    observed_at: DateTime<Utc>,
}

async fn lock_context(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
) -> Result<(), WorkspaceContextRepositoryError> {
    sqlx::query(LOCK_CONTEXT_SQL)
        .bind(user_id)
        .bind(CONTEXT_LOCK_SEED)
        .execute(&mut **transaction)
        .await
        .map_err(storage)?;
    Ok(())
}

async fn load_context(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
) -> Result<Option<ContextRow>, WorkspaceContextRepositoryError> {
    sqlx::query_as(LOAD_CONTEXT_SQL)
        .bind(user_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(storage)
}

async fn load_default_scope(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
) -> Result<Option<DefaultScopeRow>, WorkspaceContextRepositoryError> {
    sqlx::query_as(LOAD_DEFAULT_SCOPE_SQL)
        .bind(user_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(storage)
}

async fn load_event(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
    idempotency_key: &str,
) -> Result<Option<WorkspaceContextSnapshotRecord>, WorkspaceContextRepositoryError> {
    sqlx::query_as(LOAD_EVENT_SQL)
        .bind(user_id)
        .bind(idempotency_key)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(storage)
}

async fn load_last_event_revision(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
) -> Result<Option<i64>, WorkspaceContextRepositoryError> {
    sqlx::query_scalar(
        "SELECT max(revision) FROM agistack_desktop_workspace_context_events WHERE user_id = $1",
    )
    .bind(user_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(storage)
}

async fn require_membership(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
    tenant_id: &str,
) -> Result<(), WorkspaceContextRepositoryError> {
    let exists = sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS(SELECT 1 FROM user_tenants WHERE user_id = $1 AND tenant_id = $2)",
    )
    .bind(user_id)
    .bind(tenant_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(storage)?;
    if exists {
        Ok(())
    } else {
        Err(WorkspaceContextRepositoryError::TenantMembershipRequired)
    }
}

async fn require_project(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> Result<(), WorkspaceContextRepositoryError> {
    let exists = sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS(SELECT 1 FROM projects AS project \
         JOIN user_projects AS access ON access.project_id = project.id \
         WHERE access.user_id = $1 AND project.tenant_id = $2 AND project.id = $3)",
    )
    .bind(user_id)
    .bind(tenant_id)
    .bind(project_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(storage)?;
    if exists {
        Ok(())
    } else {
        Err(WorkspaceContextRepositoryError::ProjectUnavailable)
    }
}

async fn insert_context(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
    revision: i64,
    observed_at: DateTime<Utc>,
) -> Result<(), WorkspaceContextRepositoryError> {
    sqlx::query(
        "INSERT INTO agistack_desktop_workspace_contexts( \
         user_id, tenant_id, project_id, revision, updated_at) VALUES ($1, $2, $3, $4, $5)",
    )
    .bind(user_id)
    .bind(tenant_id)
    .bind(project_id)
    .bind(revision)
    .bind(observed_at)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn update_context(
    transaction: &mut Transaction<'_, Postgres>,
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
    revision: i64,
    observed_at: DateTime<Utc>,
) -> Result<(), WorkspaceContextRepositoryError> {
    sqlx::query(
        "UPDATE agistack_desktop_workspace_contexts \
         SET tenant_id = $2, project_id = $3, revision = $4, updated_at = $5 \
         WHERE user_id = $1",
    )
    .bind(user_id)
    .bind(tenant_id)
    .bind(project_id)
    .bind(revision)
    .bind(observed_at)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn insert_event(
    transaction: &mut Transaction<'_, Postgres>,
    input: ContextEventInput<'_>,
) -> Result<(), WorkspaceContextRepositoryError> {
    let id = try_generate_uuid_v4().map_err(|error| {
        WorkspaceContextRepositoryError::Storage(format!("event id generation: {error}"))
    })?;
    let value = json!({
        "tenant_id": input.to_tenant_id,
        "project_id": input.to_project_id,
        "revision": input.revision,
        "updated_at": input.observed_at,
    });
    sqlx::query(
        "INSERT INTO agistack_desktop_workspace_context_events( \
         id, user_id, actor_api_key_id, from_tenant_id, from_project_id, \
         to_tenant_id, to_project_id, revision, idempotency_key, value_json, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
    )
    .bind(id)
    .bind(input.user_id)
    .bind(input.actor_api_key_id)
    .bind(input.from_tenant_id)
    .bind(input.from_project_id)
    .bind(input.to_tenant_id)
    .bind(input.to_project_id)
    .bind(input.revision)
    .bind(input.idempotency_key)
    .bind(value)
    .bind(input.observed_at)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    Ok(())
}

fn validate_user_id(user_id: &str) -> Result<(), WorkspaceContextRepositoryError> {
    if user_id.trim().is_empty() {
        Err(WorkspaceContextRepositoryError::InvalidInput)
    } else {
        Ok(())
    }
}

fn validate_switch(
    user_id: &str,
    request: &WorkspaceContextSwitchRequest,
) -> Result<(), WorkspaceContextRepositoryError> {
    validate_user_id(user_id)?;
    let key = request.idempotency_key.trim();
    if request.tenant_id.trim().is_empty()
        || request.project_id.trim().is_empty()
        || request.expected_revision < 0
        || key.is_empty()
        || key.len() > 255
    {
        Err(WorkspaceContextRepositoryError::InvalidInput)
    } else {
        Ok(())
    }
}

fn next_revision(revision: i64) -> Result<i64, WorkspaceContextRepositoryError> {
    revision
        .checked_add(1)
        .ok_or(WorkspaceContextRepositoryError::RevisionExhausted)
}

fn storage(error: sqlx::Error) -> WorkspaceContextRepositoryError {
    WorkspaceContextRepositoryError::Storage(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn switch_validation_requires_revision_and_bounded_idempotency() {
        let valid = WorkspaceContextSwitchRequest {
            tenant_id: "tenant".to_string(),
            project_id: "project".to_string(),
            expected_revision: 0,
            idempotency_key: "request-1".to_string(),
        };
        assert!(validate_switch("user", &valid).is_ok());

        for invalid in [
            WorkspaceContextSwitchRequest {
                expected_revision: -1,
                ..valid.clone()
            },
            WorkspaceContextSwitchRequest {
                idempotency_key: "x".repeat(256),
                ..valid.clone()
            },
            WorkspaceContextSwitchRequest {
                project_id: " ".to_string(),
                ..valid.clone()
            },
        ] {
            assert_eq!(
                validate_switch("user", &invalid),
                Err(WorkspaceContextRepositoryError::InvalidInput)
            );
        }
    }

    #[test]
    fn context_queries_serialize_user_mutations_and_require_both_memberships() {
        assert!(LOCK_CONTEXT_SQL.contains("pg_advisory_xact_lock"));
        assert!(LOAD_CONTEXT_SQL.contains("user_tenants"));
        assert!(LOAD_CONTEXT_SQL.contains("user_projects"));
        assert!(LOAD_DEFAULT_SCOPE_SQL.contains("ORDER BY membership.created_at ASC"));
    }

    #[test]
    fn repository_errors_redact_storage_details() {
        let error = WorkspaceContextRepositoryError::Storage("secret dsn".to_string());
        assert_eq!(error.to_string(), "workspace context storage failed");
    }
}
