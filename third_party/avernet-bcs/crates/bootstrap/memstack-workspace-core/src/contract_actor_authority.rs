//! Server-owned Workspace contract actor resolution and immutable audit replay.

use std::sync::Arc;

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::{Extension, Json};
use bcs_db_api::{DbRow, DbSqlFlavor, DbStatementBuilder, DbValue};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::WorkspaceCoreState;

const CONTRACT_VERSION: &str = "2.0.0";
const POLICY_VERSION: &str = "workspace-contract-actor-owner.v1";
const AUDIT_NAMESPACE: Uuid = Uuid::from_u128(0x4e79_95a2_c69e_4f8d_a2be_0baf_a2c8_6f85);
const MAX_SCOPE_ID_BYTES: usize = 128;
const MAX_OPERATION_ID_BYTES: usize = 256;

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum ContractActorPurpose {
    PlannerTurn,
    SupervisorTurn,
    VerifierTurn,
    WorktreeTurn,
    IterationReviewTurn,
}

impl ContractActorPurpose {
    const fn as_str(self) -> &'static str {
        match self {
            Self::PlannerTurn => "planner_turn",
            Self::SupervisorTurn => "supervisor_turn",
            Self::VerifierTurn => "verifier_turn",
            Self::WorktreeTurn => "worktree_turn",
            Self::IterationReviewTurn => "iteration_review_turn",
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ContractActorResolveRequest {
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    purpose: ContractActorPurpose,
    operation_id: String,
}

impl ContractActorResolveRequest {
    fn validate(mut self) -> Result<Self, ContractActorError> {
        self.tenant_id = normalized_id(self.tenant_id, "tenant_id", MAX_SCOPE_ID_BYTES)?;
        self.project_id = normalized_id(self.project_id, "project_id", MAX_SCOPE_ID_BYTES)?;
        self.workspace_id = normalized_id(self.workspace_id, "workspace_id", MAX_SCOPE_ID_BYTES)?;
        self.operation_id =
            normalized_id(self.operation_id, "operation_id", MAX_OPERATION_ID_BYTES)?;
        Ok(self)
    }
}

#[derive(Debug, Serialize)]
struct ContractActorResolveResponse {
    contract_version: &'static str,
    actor_user_id: String,
    participant_actor_id: String,
    authority_revision: u64,
    policy_version: &'static str,
    duplicate: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ResolutionReason {
    Resolved,
    ScopeUnavailable,
    WorkspaceInactive,
    OwnerUnavailable,
    OwnerAmbiguous,
}

impl ResolutionReason {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Resolved => "resolved",
            Self::ScopeUnavailable => "scope_unavailable",
            Self::WorkspaceInactive => "workspace_inactive",
            Self::OwnerUnavailable => "owner_unavailable",
            Self::OwnerAmbiguous => "owner_ambiguous",
        }
    }

    fn parse(value: &str) -> Result<Self, ContractActorError> {
        match value {
            "resolved" => Ok(Self::Resolved),
            "scope_unavailable" => Ok(Self::ScopeUnavailable),
            "workspace_inactive" => Ok(Self::WorkspaceInactive),
            "owner_unavailable" => Ok(Self::OwnerUnavailable),
            "owner_ambiguous" => Ok(Self::OwnerAmbiguous),
            _ => Err(ContractActorError::AuthorityUnavailable),
        }
    }

    const fn error_code(self) -> &'static str {
        match self {
            Self::Resolved => "workspace_contract_actor_authority_unavailable",
            Self::ScopeUnavailable => "workspace_contract_actor_scope_unavailable",
            Self::WorkspaceInactive => "workspace_contract_actor_workspace_inactive",
            Self::OwnerUnavailable => "workspace_contract_actor_owner_unavailable",
            Self::OwnerAmbiguous => "workspace_contract_actor_owner_ambiguous",
        }
    }

    const fn status(self) -> StatusCode {
        match self {
            Self::Resolved => StatusCode::SERVICE_UNAVAILABLE,
            Self::ScopeUnavailable => StatusCode::NOT_FOUND,
            Self::WorkspaceInactive | Self::OwnerUnavailable | Self::OwnerAmbiguous => {
                StatusCode::CONFLICT
            }
        }
    }
}

#[derive(Debug)]
enum ResolutionDecision {
    Resolved {
        actor_user_id: String,
        participant_actor_id: String,
        authority_revision: u64,
    },
    Rejected {
        reason: ResolutionReason,
        authority_revision: Option<u64>,
    },
}

impl ResolutionDecision {
    const fn outcome(&self) -> &'static str {
        match self {
            Self::Resolved { .. } => "resolved",
            Self::Rejected { .. } => "rejected",
        }
    }

    const fn reason(&self) -> ResolutionReason {
        match self {
            Self::Resolved { .. } => ResolutionReason::Resolved,
            Self::Rejected { reason, .. } => *reason,
        }
    }

    fn actor_user_id(&self) -> Option<&str> {
        match self {
            Self::Resolved { actor_user_id, .. } => Some(actor_user_id.as_str()),
            Self::Rejected { .. } => None,
        }
    }

    fn participant_actor_id(&self) -> Option<&str> {
        match self {
            Self::Resolved {
                participant_actor_id,
                ..
            } => Some(participant_actor_id.as_str()),
            Self::Rejected { .. } => None,
        }
    }

    const fn authority_revision(&self) -> Option<u64> {
        match self {
            Self::Resolved {
                authority_revision, ..
            } => Some(*authority_revision),
            Self::Rejected {
                authority_revision, ..
            } => *authority_revision,
        }
    }
}

#[derive(Debug)]
struct WorkspaceScope {
    created_by: String,
    is_archived: bool,
    is_deleted: bool,
    authority_revision: u64,
}

#[derive(Debug)]
struct EligibleOwner {
    actor_user_id: String,
    participant_actor_id: String,
}

#[derive(Debug)]
struct AuditRecord {
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    purpose: String,
    request_hash: String,
    policy_version: String,
    decision: ResolutionDecision,
}

#[derive(Debug)]
enum ContractActorError {
    CapabilityDenied,
    InvalidRequest(String),
    IdempotencyConflict,
    AuthorityUnavailable,
}

impl IntoResponse for ContractActorError {
    fn into_response(self) -> Response {
        let (status, code, detail) = match self {
            Self::CapabilityDenied => (
                StatusCode::FORBIDDEN,
                "workspace_contract_actor_capability_denied",
                "Workspace contract actor resolution is not available to this service principal",
            ),
            Self::InvalidRequest(detail) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(json!({
                        "code": "workspace_contract_actor_invalid_request",
                        "detail": detail,
                    })),
                )
                    .into_response();
            }
            Self::IdempotencyConflict => (
                StatusCode::CONFLICT,
                "workspace_contract_actor_idempotency_conflict",
                "Workspace contract actor operation conflicts with its immutable audit",
            ),
            Self::AuthorityUnavailable => (
                StatusCode::SERVICE_UNAVAILABLE,
                "workspace_contract_actor_authority_unavailable",
                "Workspace contract actor authority is unavailable",
            ),
        };
        (status, Json(json!({ "code": code, "detail": detail }))).into_response()
    }
}

pub(super) async fn resolve_contract_actor(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Json(request): Json<ContractActorResolveRequest>,
) -> Response {
    match resolve_contract_actor_inner(state.as_ref(), request).await {
        Ok((decision, duplicate)) => decision_response(decision, duplicate),
        Err(error) => error.into_response(),
    }
}

async fn resolve_contract_actor_inner(
    state: &WorkspaceCoreState,
    request: ContractActorResolveRequest,
) -> Result<(ResolutionDecision, bool), ContractActorError> {
    let service_principal_id = state
        .contract_actor_resolver_principal_id
        .as_deref()
        .ok_or(ContractActorError::CapabilityDenied)?;
    let request = request.validate()?;
    let request_hash = request_hash(&request)?;

    if let Some(audit) = read_audit(state, service_principal_id, &request.operation_id).await? {
        return replay_audit(audit, &request, &request_hash).map(|decision| (decision, true));
    }

    let decision = resolve_current_authority(state, &request).await?;
    append_audit(
        state,
        service_principal_id,
        &request,
        &request_hash,
        &decision,
    )
    .await?;
    let audit = read_audit(state, service_principal_id, &request.operation_id)
        .await?
        .ok_or(ContractActorError::AuthorityUnavailable)?;
    let persisted = replay_audit(audit, &request, &request_hash)?;
    Ok((persisted, false))
}

async fn resolve_current_authority(
    state: &WorkspaceCoreState,
    request: &ContractActorResolveRequest,
) -> Result<ResolutionDecision, ContractActorError> {
    let Some(scope) = read_workspace_scope(state, request).await? else {
        return Ok(ResolutionDecision::Rejected {
            reason: ResolutionReason::ScopeUnavailable,
            authority_revision: None,
        });
    };
    if scope.is_archived || scope.is_deleted {
        return Ok(ResolutionDecision::Rejected {
            reason: ResolutionReason::WorkspaceInactive,
            authority_revision: Some(scope.authority_revision),
        });
    }

    let owners = read_eligible_owners(state, request).await?;
    if let Some(owner) = owners
        .iter()
        .find(|owner| owner.actor_user_id == scope.created_by)
    {
        return Ok(ResolutionDecision::Resolved {
            actor_user_id: owner.actor_user_id.clone(),
            participant_actor_id: owner.participant_actor_id.clone(),
            authority_revision: scope.authority_revision,
        });
    }
    match owners.as_slice() {
        [owner] => Ok(ResolutionDecision::Resolved {
            actor_user_id: owner.actor_user_id.clone(),
            participant_actor_id: owner.participant_actor_id.clone(),
            authority_revision: scope.authority_revision,
        }),
        [] => Ok(ResolutionDecision::Rejected {
            reason: ResolutionReason::OwnerUnavailable,
            authority_revision: Some(scope.authority_revision),
        }),
        _ => Ok(ResolutionDecision::Rejected {
            reason: ResolutionReason::OwnerAmbiguous,
            authority_revision: Some(scope.authority_revision),
        }),
    }
}

async fn read_workspace_scope(
    state: &WorkspaceCoreState,
    request: &ContractActorResolveRequest,
) -> Result<Option<WorkspaceScope>, ContractActorError> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT p.created_by, p.is_archived, p.deleted_at, \
             COALESCE(a.revision, 0) AS authority_revision FROM workspace_profiles p \
             LEFT JOIN workspace_authorities a ON a.tenant_id = p.tenant_id \
              AND a.project_id = p.project_id AND a.workspace_id = p.workspace_id \
             WHERE p.tenant_id = ",
        )
        .bind(request.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(request.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(request.workspace_id.as_str())
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(database_unavailable)?;
    let Some(row) = rows.first() else {
        return Ok(None);
    };
    if rows.len() != 1 {
        return Err(ContractActorError::AuthorityUnavailable);
    }
    Ok(Some(WorkspaceScope {
        created_by: required_string(row, "created_by")?,
        is_archived: required_bool(row, "is_archived")?,
        is_deleted: row
            .get_string("deleted_at")
            .map_err(database_unavailable)?
            .is_some(),
        authority_revision: required_revision(row, "authority_revision")?,
    }))
}

async fn read_eligible_owners(
    state: &WorkspaceCoreState,
    request: &ContractActorResolveRequest,
) -> Result<Vec<EligibleOwner>, ContractActorError> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT m.user_id, i.participant_actor_id FROM workspace_members m \
             JOIN workspace_principal_identities i ON i.tenant_id = m.tenant_id \
              AND i.project_id = m.project_id AND i.workspace_id = m.workspace_id \
              AND i.user_id = m.user_id \
             JOIN project_principal_memberships pm ON pm.tenant_id = m.tenant_id \
              AND pm.project_id = m.project_id AND pm.user_id = m.user_id \
             WHERE m.tenant_id = ",
        )
        .bind(request.tenant_id.as_str())
        .push_static(" AND m.project_id = ")
        .bind(request.project_id.as_str())
        .push_static(" AND m.workspace_id = ")
        .bind(request.workspace_id.as_str())
        .push_static(" AND m.role = ")
        .bind("owner")
        .push_static(" AND i.is_active = ")
        .bind(true)
        .push_static(" AND pm.is_active = ")
        .bind(true)
        .push_static(" ORDER BY m.user_id")
        .build();
    state
        .db
        .query(statement)
        .await
        .map_err(database_unavailable)?
        .iter()
        .map(|row| {
            Ok(EligibleOwner {
                actor_user_id: required_string(row, "user_id")?,
                participant_actor_id: required_string(row, "participant_actor_id")?,
            })
        })
        .collect()
}

async fn read_audit(
    state: &WorkspaceCoreState,
    service_principal_id: &str,
    operation_id: &str,
) -> Result<Option<AuditRecord>, ContractActorError> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT tenant_id, project_id, workspace_id, purpose, request_hash, outcome, reason, \
             resolved_actor_user_id, resolved_participant_actor_id, authority_revision, \
             policy_version FROM workspace_contract_actor_resolution_audits \
             WHERE service_principal_id = ",
        )
        .bind(service_principal_id)
        .push_static(" AND operation_id = ")
        .bind(operation_id)
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(database_unavailable)?;
    let Some(row) = rows.first() else {
        return Ok(None);
    };
    if rows.len() != 1 {
        return Err(ContractActorError::AuthorityUnavailable);
    }
    let outcome = required_string(row, "outcome")?;
    let reason = ResolutionReason::parse(required_string(row, "reason")?.as_str())?;
    let authority_revision = optional_revision(row, "authority_revision")?;
    let decision = match (outcome.as_str(), reason) {
        ("resolved", ResolutionReason::Resolved) => ResolutionDecision::Resolved {
            actor_user_id: required_string(row, "resolved_actor_user_id")?,
            participant_actor_id: required_string(row, "resolved_participant_actor_id")?,
            authority_revision: authority_revision
                .ok_or(ContractActorError::AuthorityUnavailable)?,
        },
        ("rejected", reason) if reason != ResolutionReason::Resolved => {
            if optional_string(row, "resolved_actor_user_id")?.is_some()
                || optional_string(row, "resolved_participant_actor_id")?.is_some()
            {
                return Err(ContractActorError::AuthorityUnavailable);
            }
            ResolutionDecision::Rejected {
                reason,
                authority_revision,
            }
        }
        _ => return Err(ContractActorError::AuthorityUnavailable),
    };
    Ok(Some(AuditRecord {
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        purpose: required_string(row, "purpose")?,
        request_hash: required_string(row, "request_hash")?,
        policy_version: required_string(row, "policy_version")?,
        decision,
    }))
}

async fn append_audit(
    state: &WorkspaceCoreState,
    service_principal_id: &str,
    request: &ContractActorResolveRequest,
    request_hash: &str,
    decision: &ResolutionDecision,
) -> Result<(), ContractActorError> {
    let audit_id = Uuid::new_v5(
        &AUDIT_NAMESPACE,
        format!("{service_principal_id}\0{}", request.operation_id).as_bytes(),
    )
    .to_string();
    let revision = decision
        .authority_revision()
        .map(DbValue::from)
        .unwrap_or(DbValue::Null);
    let on_conflict = match state.sql_flavor {
        DbSqlFlavor::Sqlite | DbSqlFlavor::Postgres => {
            "ON CONFLICT(service_principal_id, operation_id) DO NOTHING"
        }
        DbSqlFlavor::Mysql => return Err(ContractActorError::AuthorityUnavailable),
    };
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "INSERT INTO workspace_contract_actor_resolution_audits (audit_id, \
             service_principal_id, operation_id, tenant_id, project_id, workspace_id, purpose, \
             request_hash, outcome, reason, resolved_actor_user_id, \
             resolved_participant_actor_id, authority_revision, policy_version) VALUES (",
        )
        .bind(audit_id)
        .push_static(", ")
        .bind(service_principal_id)
        .push_static(", ")
        .bind(request.operation_id.as_str())
        .push_static(", ")
        .bind(request.tenant_id.as_str())
        .push_static(", ")
        .bind(request.project_id.as_str())
        .push_static(", ")
        .bind(request.workspace_id.as_str())
        .push_static(", ")
        .bind(request.purpose.as_str())
        .push_static(", ")
        .bind(request_hash)
        .push_static(", ")
        .bind(decision.outcome())
        .push_static(", ")
        .bind(decision.reason().as_str())
        .push_static(", ")
        .bind(decision.actor_user_id())
        .push_static(", ")
        .bind(decision.participant_actor_id())
        .push_static(", ")
        .bind(revision)
        .push_static(", ")
        .bind(POLICY_VERSION)
        .push_static(") ")
        .push_static(on_conflict)
        .build();
    state
        .db
        .execute(statement)
        .await
        .map_err(database_unavailable)?;
    Ok(())
}

fn replay_audit(
    audit: AuditRecord,
    request: &ContractActorResolveRequest,
    request_hash: &str,
) -> Result<ResolutionDecision, ContractActorError> {
    if audit.request_hash != request_hash {
        return Err(ContractActorError::IdempotencyConflict);
    }
    if audit.tenant_id != request.tenant_id
        || audit.project_id != request.project_id
        || audit.workspace_id != request.workspace_id
        || audit.purpose != request.purpose.as_str()
        || audit.policy_version != POLICY_VERSION
    {
        return Err(ContractActorError::AuthorityUnavailable);
    }
    Ok(audit.decision)
}

fn decision_response(decision: ResolutionDecision, duplicate: bool) -> Response {
    match decision {
        ResolutionDecision::Resolved {
            actor_user_id,
            participant_actor_id,
            authority_revision,
        } => Json(ContractActorResolveResponse {
            contract_version: CONTRACT_VERSION,
            actor_user_id,
            participant_actor_id,
            authority_revision,
            policy_version: POLICY_VERSION,
            duplicate,
        })
        .into_response(),
        ResolutionDecision::Rejected { reason, .. } => (
            reason.status(),
            Json(json!({
                "code": reason.error_code(),
                "detail": "Workspace contract actor resolution was rejected",
                "duplicate": duplicate,
            })),
        )
            .into_response(),
    }
}

fn request_hash(request: &ContractActorResolveRequest) -> Result<String, ContractActorError> {
    let bytes = serde_json::to_vec(request).map_err(|error| {
        tracing::error!(error = %error, "Workspace contract actor request hashing failed");
        ContractActorError::AuthorityUnavailable
    })?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn normalized_id(
    value: String,
    field: &'static str,
    max_bytes: usize,
) -> Result<String, ContractActorError> {
    let value = value.trim();
    if value.is_empty() || value.len() > max_bytes || value.chars().any(char::is_control) {
        return Err(ContractActorError::InvalidRequest(format!(
            "{field} is invalid"
        )));
    }
    Ok(value.to_string())
}

fn required_string(row: &DbRow, column: &'static str) -> Result<String, ContractActorError> {
    optional_string(row, column)?
        .filter(|value| !value.trim().is_empty())
        .ok_or(ContractActorError::AuthorityUnavailable)
}

fn optional_string(
    row: &DbRow,
    column: &'static str,
) -> Result<Option<String>, ContractActorError> {
    row.get_string(column).map_err(database_unavailable)
}

fn required_bool(row: &DbRow, column: &'static str) -> Result<bool, ContractActorError> {
    row.get_bool(column)
        .map_err(database_unavailable)?
        .ok_or(ContractActorError::AuthorityUnavailable)
}

fn required_revision(row: &DbRow, column: &'static str) -> Result<u64, ContractActorError> {
    optional_revision(row, column)?.ok_or(ContractActorError::AuthorityUnavailable)
}

fn optional_revision(row: &DbRow, column: &'static str) -> Result<Option<u64>, ContractActorError> {
    row.get_i64(column)
        .map_err(database_unavailable)?
        .map(|value| u64::try_from(value).map_err(|_| ContractActorError::AuthorityUnavailable))
        .transpose()
}

fn database_unavailable(error: bcs_db_api::DbError) -> ContractActorError {
    tracing::error!(error = %error, "Workspace contract actor database operation failed");
    ContractActorError::AuthorityUnavailable
}
