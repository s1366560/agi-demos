//! Shared-DB adapter for Python-owned trust governance tables.
//!
//! P2 trust routes live under `/tenants/{tenant_id}/trust/*` in Python. This
//! repository mirrors the same `trust_policies`, `decision_records`,
//! `workspaces`, `tenants`, `users`, and `user_tenants` access pattern while
//! keeping `sqlx` out of the portable core.

use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TenantAccessStatus {
    Authorized,
    TenantNotFound,
    NotMember,
    NotAdmin,
}

#[derive(Debug, Clone)]
pub struct TrustPolicyRecord {
    pub id: String,
    pub tenant_id: String,
    pub workspace_id: String,
    pub agent_instance_id: String,
    pub action_type: String,
    pub granted_by: String,
    pub grant_type: String,
    pub created_at: DateTime<Utc>,
    pub deleted_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct NewTrustPolicyRecord {
    pub id: String,
    pub tenant_id: String,
    pub workspace_id: String,
    pub agent_instance_id: String,
    pub action_type: String,
    pub granted_by: String,
    pub grant_type: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct DecisionRecordRecord {
    pub id: String,
    pub tenant_id: String,
    pub workspace_id: String,
    pub agent_instance_id: String,
    pub decision_type: String,
    pub context_summary: Option<String>,
    pub proposal: serde_json::Value,
    pub outcome: String,
    pub reviewer_id: Option<String>,
    pub review_type: Option<String>,
    pub review_comment: Option<String>,
    pub resolved_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub deleted_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct NewDecisionRecordRecord {
    pub id: String,
    pub tenant_id: String,
    pub workspace_id: String,
    pub agent_instance_id: String,
    pub decision_type: String,
    pub context_summary: Option<String>,
    pub proposal: serde_json::Value,
    pub outcome: String,
    pub created_at: DateTime<Utc>,
}

pub struct PgTrustRepository {
    pool: PgPool,
}

impl PgTrustRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn tenant_access_status(
        &self,
        user_id: &str,
        tenant_id: &str,
        require_admin: bool,
    ) -> CoreResult<TenantAccessStatus> {
        let tenant_exists =
            sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM tenants WHERE id = $1")
                .bind(tenant_id)
                .fetch_one(&self.pool)
                .await
                .map_err(storage_err)?
                .0
                > 0;
        if !tenant_exists {
            return Ok(TenantAccessStatus::TenantNotFound);
        }

        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage_err)?
        .map(|(is_superuser,)| is_superuser)
        .unwrap_or(false);
        if is_superuser {
            return Ok(TenantAccessStatus::Authorized);
        }

        let role = sqlx::query_as::<_, (String,)>(
            "SELECT role FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage_err)?
        .map(|(role,)| role);

        match role.as_deref() {
            Some("owner" | "admin") => Ok(TenantAccessStatus::Authorized),
            Some(_) if require_admin => Ok(TenantAccessStatus::NotAdmin),
            Some(_) => Ok(TenantAccessStatus::Authorized),
            None => Ok(TenantAccessStatus::NotMember),
        }
    }

    pub async fn workspace_exists_in_tenant(
        &self,
        tenant_id: &str,
        workspace_id: &str,
    ) -> CoreResult<bool> {
        let (exists,): (bool,) = sqlx::query_as(
            "SELECT EXISTS(\
                SELECT 1 FROM workspaces WHERE id = $1 AND tenant_id = $2\
            )",
        )
        .bind(workspace_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(exists)
    }

    pub async fn list_policies(
        &self,
        workspace_id: &str,
        agent_instance_id: Option<&str>,
    ) -> CoreResult<Vec<TrustPolicyRecord>> {
        let rows = match agent_instance_id {
            Some(agent_instance_id) => sqlx::query_as::<_, TrustPolicyRow>(
                "SELECT id, tenant_id, workspace_id, agent_instance_id, action_type, \
                            granted_by, grant_type, created_at, deleted_at \
                     FROM trust_policies \
                     WHERE workspace_id = $1 AND agent_instance_id = $2 AND deleted_at IS NULL \
                     ORDER BY created_at DESC",
            )
            .bind(workspace_id)
            .bind(agent_instance_id)
            .fetch_all(&self.pool)
            .await
            .map_err(storage_err)?,
            None => sqlx::query_as::<_, TrustPolicyRow>(
                "SELECT id, tenant_id, workspace_id, agent_instance_id, action_type, \
                            granted_by, grant_type, created_at, deleted_at \
                     FROM trust_policies \
                     WHERE workspace_id = $1 AND deleted_at IS NULL \
                     ORDER BY created_at DESC",
            )
            .bind(workspace_id)
            .fetch_all(&self.pool)
            .await
            .map_err(storage_err)?,
        };
        Ok(rows.into_iter().map(TrustPolicyRow::into_record).collect())
    }

    pub async fn create_policy(
        &self,
        policy: NewTrustPolicyRecord,
    ) -> CoreResult<TrustPolicyRecord> {
        let row = sqlx::query_as::<_, TrustPolicyRow>(
            "INSERT INTO trust_policies \
                (id, tenant_id, workspace_id, agent_instance_id, action_type, \
                 granted_by, grant_type, created_at, deleted_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NULL) \
             RETURNING id, tenant_id, workspace_id, agent_instance_id, action_type, \
                       granted_by, grant_type, created_at, deleted_at",
        )
        .bind(policy.id)
        .bind(policy.tenant_id)
        .bind(policy.workspace_id)
        .bind(policy.agent_instance_id)
        .bind(policy.action_type)
        .bind(policy.granted_by)
        .bind(policy.grant_type)
        .bind(policy.created_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(row.into_record())
    }

    pub async fn check_always_trust(
        &self,
        workspace_id: &str,
        agent_instance_id: &str,
        action_type: &str,
    ) -> CoreResult<bool> {
        let (exists,): (bool,) = sqlx::query_as(
            "SELECT EXISTS(\
                SELECT 1 FROM trust_policies \
                WHERE workspace_id = $1 AND agent_instance_id = $2 \
                  AND action_type = $3 AND grant_type = 'always' \
                  AND deleted_at IS NULL\
            )",
        )
        .bind(workspace_id)
        .bind(agent_instance_id)
        .bind(action_type)
        .fetch_one(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(exists)
    }

    pub async fn create_decision(
        &self,
        record: NewDecisionRecordRecord,
    ) -> CoreResult<DecisionRecordRecord> {
        let proposal_json = serde_json::to_string(&record.proposal)
            .map_err(|e| CoreError::Storage(format!("encode decision proposal: {e}")))?;
        let row = sqlx::query_as::<_, DecisionRecordRow>(
            "INSERT INTO decision_records \
                (id, tenant_id, workspace_id, agent_instance_id, decision_type, \
                 context_summary, proposal, outcome, reviewer_id, review_type, \
                 review_comment, resolved_at, created_at, updated_at, deleted_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7::json, $8, NULL, NULL, NULL, NULL, $9, NULL, NULL) \
             RETURNING id, tenant_id, workspace_id, agent_instance_id, decision_type, \
                       context_summary, proposal::text AS proposal_text, outcome, \
                       reviewer_id, review_type, review_comment, resolved_at, \
                       created_at, updated_at, deleted_at",
        )
        .bind(record.id)
        .bind(record.tenant_id)
        .bind(record.workspace_id)
        .bind(record.agent_instance_id)
        .bind(record.decision_type)
        .bind(record.context_summary)
        .bind(proposal_json)
        .bind(record.outcome)
        .bind(record.created_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(row.into_record())
    }

    pub async fn find_decision(&self, record_id: &str) -> CoreResult<Option<DecisionRecordRecord>> {
        let row = sqlx::query_as::<_, DecisionRecordRow>(
            "SELECT id, tenant_id, workspace_id, agent_instance_id, decision_type, \
                    context_summary, proposal::text AS proposal_text, outcome, \
                    reviewer_id, review_type, review_comment, resolved_at, \
                    created_at, updated_at, deleted_at \
             FROM decision_records \
             WHERE id = $1 AND deleted_at IS NULL",
        )
        .bind(record_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage_err)?;
        Ok(row.map(DecisionRecordRow::into_record))
    }

    pub async fn list_decisions(
        &self,
        workspace_id: &str,
        agent_id: Option<&str>,
        decision_type: Option<&str>,
    ) -> CoreResult<Vec<DecisionRecordRecord>> {
        let rows = match (agent_id, decision_type) {
            (Some(agent_id), Some(decision_type)) => {
                let sql = decision_select(
                    "WHERE workspace_id = $1 AND agent_instance_id = $2 \
                         AND decision_type = $3 AND deleted_at IS NULL",
                );
                sqlx::query_as::<_, DecisionRecordRow>(&sql)
                    .bind(workspace_id)
                    .bind(agent_id)
                    .bind(decision_type)
                    .fetch_all(&self.pool)
                    .await
                    .map_err(storage_err)?
            }
            (Some(agent_id), None) => {
                let sql = decision_select(
                    "WHERE workspace_id = $1 AND agent_instance_id = $2 \
                         AND deleted_at IS NULL",
                );
                sqlx::query_as::<_, DecisionRecordRow>(&sql)
                    .bind(workspace_id)
                    .bind(agent_id)
                    .fetch_all(&self.pool)
                    .await
                    .map_err(storage_err)?
            }
            (None, Some(decision_type)) => {
                let sql = decision_select(
                    "WHERE workspace_id = $1 AND decision_type = $2 AND deleted_at IS NULL",
                );
                sqlx::query_as::<_, DecisionRecordRow>(&sql)
                    .bind(workspace_id)
                    .bind(decision_type)
                    .fetch_all(&self.pool)
                    .await
                    .map_err(storage_err)?
            }
            (None, None) => {
                let sql = decision_select("WHERE workspace_id = $1 AND deleted_at IS NULL");
                sqlx::query_as::<_, DecisionRecordRow>(&sql)
                    .bind(workspace_id)
                    .fetch_all(&self.pool)
                    .await
                    .map_err(storage_err)?
            }
        };
        Ok(rows
            .into_iter()
            .map(DecisionRecordRow::into_record)
            .collect())
    }

    pub async fn resolve_decision(
        &self,
        record_id: &str,
        reviewer_id: &str,
        review_type: &str,
        review_comment: &str,
        outcome: &str,
        resolved_at: DateTime<Utc>,
        new_policy: Option<NewTrustPolicyRecord>,
    ) -> CoreResult<Option<DecisionRecordRecord>> {
        let mut tx = self.pool.begin().await.map_err(storage_err)?;

        if let Some(policy) = new_policy {
            sqlx::query(
                "INSERT INTO trust_policies \
                    (id, tenant_id, workspace_id, agent_instance_id, action_type, \
                     granted_by, grant_type, created_at, deleted_at) \
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NULL)",
            )
            .bind(policy.id)
            .bind(policy.tenant_id)
            .bind(policy.workspace_id)
            .bind(policy.agent_instance_id)
            .bind(policy.action_type)
            .bind(policy.granted_by)
            .bind(policy.grant_type)
            .bind(policy.created_at)
            .execute(&mut *tx)
            .await
            .map_err(storage_err)?;
        }

        let row = sqlx::query_as::<_, DecisionRecordRow>(
            "UPDATE decision_records \
             SET outcome = $2, reviewer_id = $3, review_type = $4, \
                 review_comment = $5, resolved_at = $6, updated_at = $6 \
             WHERE id = $1 AND deleted_at IS NULL \
             RETURNING id, tenant_id, workspace_id, agent_instance_id, decision_type, \
                       context_summary, proposal::text AS proposal_text, outcome, \
                       reviewer_id, review_type, review_comment, resolved_at, \
                       created_at, updated_at, deleted_at",
        )
        .bind(record_id)
        .bind(outcome)
        .bind(reviewer_id)
        .bind(review_type)
        .bind(review_comment)
        .bind(resolved_at)
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage_err)?;

        tx.commit().await.map_err(storage_err)?;
        Ok(row.map(DecisionRecordRow::into_record))
    }
}

#[derive(sqlx::FromRow)]
struct TrustPolicyRow {
    id: String,
    tenant_id: String,
    workspace_id: String,
    agent_instance_id: String,
    action_type: String,
    granted_by: String,
    grant_type: String,
    created_at: DateTime<Utc>,
    deleted_at: Option<DateTime<Utc>>,
}

impl TrustPolicyRow {
    fn into_record(self) -> TrustPolicyRecord {
        TrustPolicyRecord {
            id: self.id,
            tenant_id: self.tenant_id,
            workspace_id: self.workspace_id,
            agent_instance_id: self.agent_instance_id,
            action_type: self.action_type,
            granted_by: self.granted_by,
            grant_type: self.grant_type,
            created_at: self.created_at,
            deleted_at: self.deleted_at,
        }
    }
}

#[derive(sqlx::FromRow)]
struct DecisionRecordRow {
    id: String,
    tenant_id: String,
    workspace_id: String,
    agent_instance_id: String,
    decision_type: String,
    context_summary: Option<String>,
    proposal_text: Option<String>,
    outcome: String,
    reviewer_id: Option<String>,
    review_type: Option<String>,
    review_comment: Option<String>,
    resolved_at: Option<DateTime<Utc>>,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
    deleted_at: Option<DateTime<Utc>>,
}

impl DecisionRecordRow {
    fn into_record(self) -> DecisionRecordRecord {
        DecisionRecordRecord {
            id: self.id,
            tenant_id: self.tenant_id,
            workspace_id: self.workspace_id,
            agent_instance_id: self.agent_instance_id,
            decision_type: self.decision_type,
            context_summary: self.context_summary,
            proposal: parse_json_or(self.proposal_text, serde_json::json!({})),
            outcome: self.outcome,
            reviewer_id: self.reviewer_id,
            review_type: self.review_type,
            review_comment: self.review_comment,
            resolved_at: self.resolved_at,
            created_at: self.created_at,
            updated_at: self.updated_at,
            deleted_at: self.deleted_at,
        }
    }
}

fn decision_select(where_clause: &str) -> String {
    format!(
        "SELECT id, tenant_id, workspace_id, agent_instance_id, decision_type, \
                context_summary, proposal::text AS proposal_text, outcome, \
                reviewer_id, review_type, review_comment, resolved_at, \
                created_at, updated_at, deleted_at \
         FROM decision_records {where_clause} ORDER BY created_at DESC"
    )
}

fn parse_json_or(raw: Option<String>, default: serde_json::Value) -> serde_json::Value {
    raw.and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(default)
}

fn storage_err(err: sqlx::Error) -> CoreError {
    CoreError::Storage(err.to_string())
}
