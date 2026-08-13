//! MemStack Workspace domain extension mounted into Avernet BCS.

use std::collections::BTreeMap;
use std::sync::Arc;

use axum::extract::{Path, Query, Request, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use bcs_db_api::{DbIdentifier, DbPlugin, DbSqlFlavor, DbStatementBuilder};
use memstack_workspace_service::ObjectStorePort;
use memstack_workspace_service::PublicWorkspaceAutonomyJudgePort;
use memstack_workspace_service_api::{
    AgentRegistryPort, ProviderRegistryPort, WorkspaceContextJudgePort,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};

pub mod agent_registry;
mod agents;
mod authority_query;
mod autonomy;
pub mod autonomy_judge;
mod blackboard;
mod capabilities;
mod collaboration_mutations;
mod context;
pub mod context_judge;
mod creation;
pub mod desktop_legacy_import;
pub mod desktop_schema;
mod diagnostics;
mod files;
mod genes;
mod members;
pub mod message_delivery;
pub mod message_delivery_worker;
mod messages;
mod mutations;
pub mod object_store;
mod objectives;
pub mod outbox;
pub mod plan_delivery_worker;
mod plan_http_models;
pub mod plan_judge;
pub mod plans;
mod policy;
pub mod provider_registry;
mod public_api;
mod runtime;
mod runtime_recovery;
mod structured_tasks;
pub mod task_dispatch;
pub mod task_dispatch_worker;
mod task_sessions;
mod tasks;
mod topology;
pub mod workspace_provider_events;
mod workspace_scope;

const TENANT_HEADER: &str = "x-memstack-tenant-id";

const SNAPSHOT_TABLES: &[&str] = &[
    "workspace_profiles",
    "workspace_members",
    "workspace_principal_identities",
    "workspace_agent_policies",
    "workspace_agent_bindings",
    "workspace_tasks",
    "workspace_task_attempts",
    "workspace_task_receipts",
    "workspace_blackboard_posts",
    "workspace_blackboard_replies",
    "workspace_files",
    "workspace_topology_nodes",
    "workspace_topology_edges",
    "workspace_objectives",
    "workspace_genes",
    "workspace_authorities",
    "workspace_revision_credentials",
    "workspace_mutation_receipts",
    "workspace_plans",
    "workspace_plan_nodes",
    "workspace_plan_blackboard_entries",
    "workspace_plan_events",
    "workspace_outbox",
    "workspace_pipeline_contracts",
    "workspace_pipeline_runs",
    "workspace_pipeline_stage_runs",
    "workspace_deployments",
    "workspace_agent_runtime_correlations",
    "workspace_execution_terminals",
    "workspace_migration_ledger",
    "workspace_judge_audits",
    "workspace_message_delivery_outbox",
    "workspace_task_dispatch_outbox",
];

/// Deployment authority reported by Workspace collaboration contracts.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorkspaceCoreAuthority {
    /// Cloud-hosted PostgreSQL authority.
    Cloud,
    /// Desktop-local SQLite authority supervised by the Sidecar.
    Local,
}

impl WorkspaceCoreAuthority {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Cloud => "cloud",
            Self::Local => "local",
        }
    }
}

/// Runtime dependencies owned by the Workspace extension.
pub struct WorkspaceCoreState {
    db: Arc<dyn DbPlugin>,
    service_token: String,
    sql_flavor: DbSqlFlavor,
    agent_registry: Arc<dyn AgentRegistryPort>,
    provider_registry: Arc<dyn ProviderRegistryPort>,
    context_judge: Arc<dyn WorkspaceContextJudgePort>,
    autonomy_judge: Arc<dyn PublicWorkspaceAutonomyJudgePort>,
    object_store: Arc<dyn ObjectStorePort>,
    authority: WorkspaceCoreAuthority,
}

impl WorkspaceCoreState {
    /// Create state without exposing the service token through `Debug` output.
    ///
    /// # Errors
    ///
    /// Returns an error when the service token is blank.
    pub fn new(db: Arc<dyn DbPlugin>, service_token: String) -> Result<Self, &'static str> {
        Self::new_with_sql_flavor(db, service_token, DbSqlFlavor::Postgres)
    }

    /// Create Cloud or Desktop state with an explicit supported SQL flavor.
    ///
    /// # Errors
    ///
    /// Returns an error when the service token is blank or when MySQL is
    /// selected for the PostgreSQL/SQLite Workspace authority.
    pub fn new_with_sql_flavor(
        db: Arc<dyn DbPlugin>,
        service_token: String,
        sql_flavor: DbSqlFlavor,
    ) -> Result<Self, &'static str> {
        if service_token.trim().is_empty() {
            return Err("Workspace Core service token must not be blank");
        }
        if sql_flavor == DbSqlFlavor::Mysql {
            return Err("Workspace Core supports only PostgreSQL and SQLite");
        }
        Self::new_with_dependencies(
            db,
            service_token,
            sql_flavor,
            Arc::new(agent_registry::UnavailableAgentRegistryPort),
        )
    }

    /// Create state with the structured external Agent Registry authority.
    ///
    /// # Errors
    ///
    /// Returns an error for the same invalid token or SQL flavor conditions as
    /// [`Self::new_with_sql_flavor`].
    pub fn new_with_dependencies(
        db: Arc<dyn DbPlugin>,
        service_token: String,
        sql_flavor: DbSqlFlavor,
        agent_registry: Arc<dyn AgentRegistryPort>,
    ) -> Result<Self, &'static str> {
        Self::new_with_registries(
            db,
            service_token,
            sql_flavor,
            agent_registry,
            Arc::new(provider_registry::UnavailableProviderRegistryPort),
        )
    }

    /// Create state with both structured external registry authorities.
    ///
    /// # Errors
    ///
    /// Returns an error for the same invalid token or SQL flavor conditions as
    /// [`Self::new_with_sql_flavor`].
    pub fn new_with_registries(
        db: Arc<dyn DbPlugin>,
        service_token: String,
        sql_flavor: DbSqlFlavor,
        agent_registry: Arc<dyn AgentRegistryPort>,
        provider_registry: Arc<dyn ProviderRegistryPort>,
    ) -> Result<Self, &'static str> {
        Self::new_with_authorities(
            db,
            service_token,
            sql_flavor,
            agent_registry,
            provider_registry,
            Arc::new(context_judge::UnavailableWorkspaceContextJudgePort),
        )
    }

    /// Create state with all structured external authorities.
    ///
    /// # Errors
    ///
    /// Returns an error for the same invalid token or SQL flavor conditions as
    /// [`Self::new_with_sql_flavor`].
    pub fn new_with_authorities(
        db: Arc<dyn DbPlugin>,
        service_token: String,
        sql_flavor: DbSqlFlavor,
        agent_registry: Arc<dyn AgentRegistryPort>,
        provider_registry: Arc<dyn ProviderRegistryPort>,
        context_judge: Arc<dyn WorkspaceContextJudgePort>,
    ) -> Result<Self, &'static str> {
        Self::new_with_all_authorities(
            db,
            service_token,
            sql_flavor,
            agent_registry,
            provider_registry,
            context_judge,
            Arc::new(autonomy_judge::UnavailableWorkspaceAutonomyJudgePort),
        )
    }

    /// Create state with every structured external authority.
    ///
    /// # Errors
    ///
    /// Returns an error for the same invalid token or SQL flavor conditions as
    /// [`Self::new_with_sql_flavor`].
    #[allow(clippy::too_many_arguments)]
    pub fn new_with_all_authorities(
        db: Arc<dyn DbPlugin>,
        service_token: String,
        sql_flavor: DbSqlFlavor,
        agent_registry: Arc<dyn AgentRegistryPort>,
        provider_registry: Arc<dyn ProviderRegistryPort>,
        context_judge: Arc<dyn WorkspaceContextJudgePort>,
        autonomy_judge: Arc<dyn PublicWorkspaceAutonomyJudgePort>,
    ) -> Result<Self, &'static str> {
        if service_token.trim().is_empty() {
            return Err("Workspace Core service token must not be blank");
        }
        if sql_flavor == DbSqlFlavor::Mysql {
            return Err("Workspace Core supports only PostgreSQL and SQLite");
        }
        Ok(Self {
            db,
            service_token,
            sql_flavor,
            agent_registry,
            provider_registry,
            context_judge,
            autonomy_judge,
            object_store: Arc::new(object_store::UnavailableObjectStorePort),
            authority: WorkspaceCoreAuthority::Cloud,
        })
    }

    /// Install the Cloud object-store or Desktop vault adapter used by File routes.
    #[must_use]
    pub fn with_object_store(mut self, object_store: Arc<dyn ObjectStorePort>) -> Self {
        self.object_store = object_store;
        self
    }

    /// Set the deployment authority exposed by collaboration capability contracts.
    #[must_use]
    pub fn with_authority(mut self, authority: WorkspaceCoreAuthority) -> Self {
        self.authority = authority;
        self
    }
}

/// Mount internal Workspace APIs into the ready BCS router.
pub fn workspace_router(state: Arc<WorkspaceCoreState>) -> Router {
    Router::new()
        .route(
            "/internal/v1/capabilities/workspace-public-api",
            get(capabilities::read_public_api_capabilities),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
            get(public_api::list_workspaces).post(creation::create_public_workspace),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}",
            get(public_api::get_workspace)
                .patch(mutations::update_public_workspace)
                .delete(mutations::delete_public_workspace),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents",
            get(public_api::list_workspace_agents).post(agents::bind_workspace_agent),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents/{workspace_agent_id}",
            axum::routing::patch(agents::update_workspace_agent)
                .delete(agents::unbind_workspace_agent),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members",
            get(public_api::list_workspace_members).post(members::add_public_workspace_member),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
            axum::routing::patch(members::update_public_workspace_member)
                .delete(members::remove_public_workspace_member),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/messages",
            get(messages::list_workspace_messages).post(messages::send_workspace_message),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/messages/mentions/{target_id}",
            get(messages::list_workspace_mentions),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/capabilities",
            get(public_api::get_collaboration_capabilities),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/authority",
            get(public_api::get_collaboration_authority),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agent-policy",
            get(policy::get_workspace_agent_policy).patch(policy::patch_workspace_agent_policy),
        )
        .route(
            "/api/v1/llm-providers/routing-policy",
            get(policy::get_legacy_workspace_routing_policy)
                .put(policy::put_legacy_workspace_routing_policy),
        )
        .route(
            "/api/v1/workspace-context",
            get(context::get_workspace_context),
        )
        .route(
            "/api/v1/workspace-context/switch",
            post(context::switch_workspace_context),
        )
        .merge(blackboard::router())
        .merge(autonomy::router())
        .merge(collaboration_mutations::router())
        .merge(diagnostics::router())
        .merge(files::router())
        .merge(genes::router())
        .merge(objectives::router())
        .merge(tasks::router())
        .merge(topology::router())
        .route(
            "/internal/v1/workspaces/{workspace_id}/snapshot",
            get(read_snapshot),
        )
        .route(
            "/internal/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
            post(creation::create_workspace),
        )
        .route(
            "/internal/v1/tenants/{tenant_id}/projects/{project_id}/task-sessions",
            post(task_sessions::create_task_session),
        )
        .route(
            "/internal/v1/workspace-authority/query",
            post(authority_query::query_workspace_authority),
        )
        .merge(structured_tasks::router())
        .route(
            "/internal/v1/workspaces/{workspace_id}/members/{user_id}",
            get(has_workspace_access),
        )
        .route(
            "/internal/v1/runtime-correlations",
            post(runtime::record_runtime_correlation),
        )
        .route(
            "/internal/v1/runtime-correlations/{correlation_id}/terminal",
            get(runtime::read_runtime_terminal).post(runtime::record_runtime_terminal),
        )
        .route(
            "/internal/v1/runtime-recoveries/claim",
            post(runtime_recovery::claim_runtime_recoveries),
        )
        .route(
            "/internal/v1/runtime-correlations/{correlation_id}/callback-ack",
            post(runtime_recovery::acknowledge_runtime_callback),
        )
        .route(
            "/internal/v1/runtime-correlations/{correlation_id}/recovery-judgments",
            post(runtime_recovery::record_runtime_recovery_judgment),
        )
        .route_layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_service_token,
        ))
        .layer(Extension(state))
}

/// Mount Workspace APIs with Agent Runtime Provider delivery ports from the
/// completed BCS service bundle.
pub fn workspace_router_with_message_runtime(
    state: Arc<WorkspaceCoreState>,
    runtime: Arc<message_delivery::WorkspaceMessageRuntime>,
) -> Router {
    workspace_router(state).layer(Extension(runtime))
}

#[derive(Debug, Deserialize)]
struct SnapshotQuery {
    project_id: String,
}

#[derive(Debug, Serialize)]
struct WorkspaceSnapshot {
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    revision: u64,
    counts: BTreeMap<String, u64>,
    canonical_hash: String,
}

#[derive(Debug, Serialize)]
struct WorkspaceAccessResponse {
    allowed: bool,
}

async fn read_snapshot(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    Query(query): Query<SnapshotQuery>,
    headers: HeaderMap,
) -> Result<Json<WorkspaceSnapshot>, ApiError> {
    let tenant_id = required_header(&headers, TENANT_HEADER)?;
    let revision = read_revision(
        state.db.as_ref(),
        &tenant_id,
        &query.project_id,
        &workspace_id,
    )
    .await?
    .ok_or(ApiError::NotFound)?;

    let mut counts = BTreeMap::new();
    for table in SNAPSHOT_TABLES {
        let count = count_scoped_rows(
            state.db.as_ref(),
            table,
            &tenant_id,
            &query.project_id,
            &workspace_id,
        )
        .await?;
        counts.insert((*table).to_string(), count);
    }

    let canonical_payload = json!({
        "tenant_id": &tenant_id,
        "project_id": &query.project_id,
        "workspace_id": &workspace_id,
        "revision": revision,
        "counts": &counts,
    });
    let canonical_bytes = serde_json::to_vec(&canonical_payload).map_err(ApiError::Json)?;
    let canonical_hash = hex::encode(Sha256::digest(canonical_bytes));

    Ok(Json(WorkspaceSnapshot {
        tenant_id,
        project_id: query.project_id,
        workspace_id,
        revision,
        counts,
        canonical_hash,
    }))
}

async fn has_workspace_access(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, user_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> Result<Json<WorkspaceAccessResponse>, ApiError> {
    let tenant_id = required_header(&headers, TENANT_HEADER)?;
    let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "SELECT 1 AS allowed FROM workspace_members m \
             JOIN workspace_profiles p ON p.tenant_id = m.tenant_id \
              AND p.project_id = m.project_id AND p.workspace_id = m.workspace_id \
             WHERE m.tenant_id = ",
        )
        .bind(tenant_id)
        .push_static(" AND m.workspace_id = ")
        .bind(workspace_id)
        .push_static(" AND m.user_id = ")
        .bind(user_id)
        .push_static(" AND p.deleted_at IS NULL LIMIT 1")
        .build();
    let rows = state
        .db
        .query(statement)
        .await
        .map_err(ApiError::Database)?;
    Ok(Json(WorkspaceAccessResponse {
        allowed: !rows.is_empty(),
    }))
}

async fn read_revision(
    db: &dyn DbPlugin,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<Option<u64>, ApiError> {
    let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "SELECT COALESCE(a.revision, 0) AS revision \
             FROM workspace_profiles p \
             LEFT JOIN workspace_authorities a \
               ON a.tenant_id = p.tenant_id \
              AND a.project_id = p.project_id \
              AND a.workspace_id = p.workspace_id \
             WHERE p.tenant_id = ",
        )
        .bind(tenant_id)
        .push_static(" AND p.project_id = ")
        .bind(project_id)
        .push_static(" AND p.workspace_id = ")
        .bind(workspace_id)
        .build();
    let rows = db.query(statement).await.map_err(ApiError::Database)?;
    let Some(row) = rows.first() else {
        return Ok(None);
    };
    let revision = row
        .get_i64("revision")
        .map_err(ApiError::Database)?
        .ok_or_else(|| ApiError::InvalidDatabase("revision is missing".to_string()))?;
    let revision = u64::try_from(revision)
        .map_err(|_| ApiError::InvalidDatabase("revision is negative".to_string()))?;
    Ok(Some(revision))
}

async fn count_scoped_rows(
    db: &dyn DbPlugin,
    table: &'static str,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<u64, ApiError> {
    let table = DbIdentifier::new_static(table).map_err(ApiError::Database)?;
    let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static("SELECT COUNT(*) AS row_count FROM ")
        .push_identifier(table)
        .push_static(" WHERE tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND project_id = ")
        .bind(project_id)
        .push_static(" AND workspace_id = ")
        .bind(workspace_id)
        .build();
    let rows = db.query(statement).await.map_err(ApiError::Database)?;
    let row = rows
        .first()
        .ok_or_else(|| ApiError::InvalidDatabase("count row is missing".to_string()))?;
    let count = row
        .get_i64("row_count")
        .map_err(ApiError::Database)?
        .ok_or_else(|| ApiError::InvalidDatabase("row_count is missing".to_string()))?;
    u64::try_from(count).map_err(|_| ApiError::InvalidDatabase("row_count is negative".to_string()))
}

async fn require_service_token(
    State(state): State<Arc<WorkspaceCoreState>>,
    request: Request,
    next: Next,
) -> Response {
    let supplied = request
        .headers()
        .get(header::AUTHORIZATION)
        .map(axum::http::HeaderValue::as_bytes)
        .unwrap_or_default();
    let expected = format!("Bearer {}", state.service_token);
    if !digest_equal(supplied, expected.as_bytes()) {
        return ApiError::Unauthorized.into_response();
    }
    next.run(request).await
}

fn required_header(headers: &HeaderMap, name: &'static str) -> Result<String, ApiError> {
    let value = headers
        .get(name)
        .ok_or_else(|| ApiError::InvalidRequest(format!("missing {name} header")))?;
    value
        .to_str()
        .map(str::to_string)
        .map_err(|_| ApiError::InvalidRequest(format!("invalid {name} header")))
}

fn digest_equal(left: &[u8], right: &[u8]) -> bool {
    let left = Sha256::digest(left);
    let right = Sha256::digest(right);
    left.iter()
        .zip(right.iter())
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

#[derive(Debug)]
enum ApiError {
    Unauthorized,
    InvalidRequest(String),
    Validation(serde_json::Value),
    NotFound,
    Forbidden(&'static str),
    Conflict(String),
    IdempotencyConflict(&'static str),
    Database(bcs_db_api::DbError),
    InvalidDatabase(String),
    Json(serde_json::Error),
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        if let Self::Validation(detail) = self {
            return (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({ "detail": detail })),
            )
                .into_response();
        }
        if let Self::IdempotencyConflict(code) = self {
            return (
                StatusCode::CONFLICT,
                Json(json!({
                    "code": code,
                    "detail": "Task session idempotency conflict",
                })),
            )
                .into_response();
        }
        let (status, detail) = match self {
            Self::Unauthorized => (StatusCode::UNAUTHORIZED, "Unauthorized".to_string()),
            Self::InvalidRequest(detail) => (StatusCode::BAD_REQUEST, detail),
            Self::Validation(_) => unreachable!("validation responses return before this match"),
            Self::NotFound => (StatusCode::NOT_FOUND, "Workspace not found".to_string()),
            Self::Forbidden(detail) => (StatusCode::FORBIDDEN, detail.to_string()),
            Self::Conflict(detail) => (StatusCode::CONFLICT, detail),
            Self::IdempotencyConflict(_) => {
                unreachable!("idempotency conflict responses return before this match")
            }
            Self::Database(error) => {
                tracing::error!(error = %error, "Workspace database request failed");
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Workspace Core is unavailable".to_string(),
                )
            }
            Self::InvalidDatabase(error) => {
                tracing::error!(error, "Workspace database returned an invalid result");
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Workspace Core is unavailable".to_string(),
                )
            }
            Self::Json(error) => {
                tracing::error!(error = %error, "Workspace snapshot serialization failed");
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Workspace Core is unavailable".to_string(),
                )
            }
        };
        (status, Json(json!({ "detail": detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use async_trait::async_trait;
    use axum::body::{Body, to_bytes};
    use bcs_db_api::{
        DbCountExpectation, DbError, DbExecuteResult, DbHealth, DbResult, DbRow, DbStatement,
        DbTransactionStep, DbTransactionStepResult, DbValue,
    };
    use tower::ServiceExt;

    use super::*;

    #[derive(Default)]
    struct ContractDb;

    #[async_trait]
    impl DbPlugin for ContractDb {
        async fn query(&self, statement: DbStatement) -> DbResult<Vec<DbRow>> {
            if statement.sql().starts_with("SELECT COALESCE(a.revision") {
                return Ok(vec![row("revision", DbValue::I64(7))]);
            }
            if statement.sql().starts_with("SELECT 1 AS allowed") {
                let expected = ["tenant-1", "ws-1", "user-1"];
                let matches_scope = statement
                    .params()
                    .iter()
                    .zip(expected)
                    .all(|(value, expected)| value.as_str() == Some(expected));
                return Ok(if matches_scope {
                    vec![row("allowed", DbValue::I64(1))]
                } else {
                    Vec::new()
                });
            }
            if statement.sql().starts_with("SELECT workspace_id") {
                return Ok(vec![public_workspace_row()]);
            }
            if statement.sql().starts_with("SELECT p.workspace_id") {
                return Ok(vec![public_workspace_row()]);
            }
            if statement.sql().starts_with("SELECT binding_id") {
                return Ok(vec![public_agent_row()]);
            }
            if statement.sql().starts_with("SELECT m.member_id") {
                if statement.params().last().and_then(DbValue::as_i64) == Some(499) {
                    return Ok(vec![public_member_row_with_email(None)]);
                }
                return Ok(vec![public_member_row()]);
            }
            if statement.sql().starts_with("SELECT 1 AS workspace_exists") {
                let expected = ["tenant-1", "project-1", "ws-1"];
                let matches_scope = statement
                    .params()
                    .iter()
                    .zip(expected)
                    .all(|(value, expected)| value.as_str() == Some(expected));
                return Ok(if matches_scope {
                    vec![row("workspace_exists", DbValue::I64(1))]
                } else {
                    Vec::new()
                });
            }
            if statement.sql().starts_with("SELECT 1 AS member_role") {
                let expected = ["ws-1", "user-1"];
                let matches_scope = statement
                    .params()
                    .iter()
                    .zip(expected)
                    .all(|(value, expected)| value.as_str() == Some(expected));
                return Ok(if matches_scope {
                    vec![row("member_role", DbValue::I64(1))]
                } else {
                    Vec::new()
                });
            }
            if statement
                .sql()
                .starts_with("SELECT revision FROM workspace_authorities")
            {
                return Ok(vec![row("revision", DbValue::I64(11))]);
            }
            let count = i64::from(statement.sql().contains("FROM workspace_profiles "));
            Ok(vec![row("row_count", DbValue::I64(count))])
        }

        async fn execute(&self, _statement: DbStatement) -> DbResult<DbExecuteResult> {
            Ok(DbExecuteResult::default())
        }

        async fn transaction(
            &self,
            _steps: Vec<DbTransactionStep>,
        ) -> DbResult<Vec<DbTransactionStepResult>> {
            Ok(Vec::new())
        }

        async fn health_check(&self) -> DbResult<DbHealth> {
            Ok(DbHealth::healthy())
        }
    }

    #[derive(Default)]
    struct RuntimeContractDb {
        transactions: Mutex<Vec<Vec<DbTransactionStep>>>,
    }

    #[async_trait]
    impl DbPlugin for RuntimeContractDb {
        async fn query(&self, statement: DbStatement) -> DbResult<Vec<DbRow>> {
            if statement.sql().starts_with("WITH candidates AS") {
                return Ok(vec![runtime_recovery_row()]);
            }
            if statement.sql().starts_with(
                "UPDATE workspace_agent_runtime_correlations SET callback_completed_at",
            ) {
                return Ok(vec![DbRow::new(BTreeMap::from([
                    (
                        "correlation_id".to_string(),
                        DbValue::String("correlation-1".to_string()),
                    ),
                    (
                        "status".to_string(),
                        DbValue::String("completed".to_string()),
                    ),
                ]))]);
            }
            if statement.sql().contains("JOIN workspace_outbox") {
                return Ok(vec![runtime_terminal_read_row()]);
            }
            if statement
                .sql()
                .contains("FROM workspace_agent_runtime_correlations")
            {
                return Ok(vec![runtime_correlation_row()]);
            }
            Ok(Vec::new())
        }

        async fn execute(&self, _statement: DbStatement) -> DbResult<DbExecuteResult> {
            Ok(DbExecuteResult::default())
        }

        async fn transaction(
            &self,
            steps: Vec<DbTransactionStep>,
        ) -> DbResult<Vec<DbTransactionStepResult>> {
            let is_correlation = matches!(
                steps.first(),
                Some(DbTransactionStep::Execute(statement))
                    if statement.sql().starts_with(
                        "INSERT INTO workspace_agent_runtime_correlations"
                    )
            );
            let is_judgment = matches!(
                steps.first(),
                Some(DbTransactionStep::Execute(statement))
                    if statement.sql().starts_with("INSERT INTO workspace_judge_audits")
            );
            let mut results = Vec::with_capacity(steps.len());
            for (index, step) in steps.iter().enumerate() {
                match step {
                    DbTransactionStep::Execute(_) | DbTransactionStep::ExecuteChecked { .. } => {
                        results.push(DbTransactionStepResult::Executed(DbExecuteResult {
                            affected_rows: 1,
                            last_insert_id: None,
                        }));
                    }
                    DbTransactionStep::Query(_) | DbTransactionStep::QueryChecked { .. }
                        if is_correlation =>
                    {
                        results.push(DbTransactionStepResult::Rows(vec![
                            runtime_correlation_row(),
                        ]));
                    }
                    DbTransactionStep::Query(_) | DbTransactionStep::QueryChecked { .. }
                        if is_judgment =>
                    {
                        results.push(DbTransactionStepResult::Rows(vec![DbRow::new(
                            BTreeMap::from([
                                (
                                    "audit_id".to_string(),
                                    DbValue::String("audit-1".to_string()),
                                ),
                                (
                                    "agent_id".to_string(),
                                    DbValue::String("judge-agent".to_string()),
                                ),
                                (
                                    "tool_name".to_string(),
                                    DbValue::String("decide_runtime_recovery".to_string()),
                                ),
                                (
                                    "status".to_string(),
                                    DbValue::String("continue".to_string()),
                                ),
                            ]),
                        )]));
                    }
                    DbTransactionStep::Query(_) | DbTransactionStep::QueryChecked { .. }
                        if index + 1 == steps.len() =>
                    {
                        results.push(DbTransactionStepResult::Rows(vec![DbRow::new(
                            BTreeMap::from([
                                (
                                    "status".to_string(),
                                    DbValue::String("completed".to_string()),
                                ),
                                (
                                    "outbox_id".to_string(),
                                    DbValue::String("runtime-outbox-correlation-1".to_string()),
                                ),
                                (
                                    "terminal_id".to_string(),
                                    DbValue::String("runtime-terminal-correlation-1".to_string()),
                                ),
                                (
                                    "report_hash".to_string(),
                                    DbValue::String(hex::encode(Sha256::digest(
                                        br#"{"content":"done"}"#,
                                    ))),
                                ),
                            ]),
                        )]));
                    }
                    DbTransactionStep::Query(_) | DbTransactionStep::QueryChecked { .. } => {
                        results.push(DbTransactionStepResult::Rows(Vec::new()));
                    }
                }
            }
            let mut transactions = self
                .transactions
                .lock()
                .map_err(|error| DbError::Backend(format!("runtime transaction lock: {error}")))?;
            transactions.push(steps);
            Ok(results)
        }

        async fn health_check(&self) -> DbResult<DbHealth> {
            Ok(DbHealth::healthy())
        }
    }

    fn runtime_correlation_row() -> DbRow {
        DbRow::new(BTreeMap::from([
            (
                "correlation_id".to_string(),
                DbValue::String("correlation-1".to_string()),
            ),
            (
                "tenant_id".to_string(),
                DbValue::String("tenant-1".to_string()),
            ),
            (
                "project_id".to_string(),
                DbValue::String("project-1".to_string()),
            ),
            (
                "workspace_id".to_string(),
                DbValue::String("ws-1".to_string()),
            ),
            ("user_id".to_string(), DbValue::String("user-1".to_string())),
            (
                "conversation_id".to_string(),
                DbValue::String("conversation-1".to_string()),
            ),
            (
                "bcs_group_id".to_string(),
                DbValue::String("group-1".to_string()),
            ),
            (
                "delivery_request_id".to_string(),
                DbValue::String("delivery-1".to_string()),
            ),
            (
                "provider_run_id".to_string(),
                DbValue::String("provider-run-1".to_string()),
            ),
            (
                "provider_id".to_string(),
                DbValue::String("provider-1".to_string()),
            ),
            (
                "provider_bot_ref".to_string(),
                DbValue::String("agent-1".to_string()),
            ),
            (
                "bcs_session_id".to_string(),
                DbValue::String("session-1".to_string()),
            ),
            ("task_id".to_string(), DbValue::String("task-1".to_string())),
            (
                "plan_node_id".to_string(),
                DbValue::String("node-1".to_string()),
            ),
            ("status".to_string(), DbValue::String("running".to_string())),
            ("plan_id".to_string(), DbValue::String("plan-1".to_string())),
        ]))
    }

    fn runtime_recovery_row() -> DbRow {
        let mut values = runtime_correlation_row().columns().clone();
        values.insert("recovery_attempt_count".to_string(), DbValue::I64(1));
        DbRow::new(values)
    }

    fn runtime_terminal_read_row() -> DbRow {
        let report = json!({"content": "done"});
        DbRow::new(BTreeMap::from([
            (
                "correlation_id".to_string(),
                DbValue::String("correlation-1".to_string()),
            ),
            (
                "status".to_string(),
                DbValue::String("completed".to_string()),
            ),
            (
                "outbox_id".to_string(),
                DbValue::String("runtime-outbox-correlation-1".to_string()),
            ),
            (
                "terminal_id".to_string(),
                DbValue::String("runtime-terminal-correlation-1".to_string()),
            ),
            (
                "execution_status".to_string(),
                DbValue::String("completed".to_string()),
            ),
            (
                "terminal_message_id".to_string(),
                DbValue::String("message-1".to_string()),
            ),
            (
                "terminal_event_id".to_string(),
                DbValue::String("legacy-event-1".to_string()),
            ),
            (
                "report_json".to_string(),
                DbValue::String(report.to_string()),
            ),
            (
                "report_hash".to_string(),
                DbValue::String(hex::encode(Sha256::digest(br#"{"content":"done"}"#))),
            ),
        ]))
    }

    fn runtime_contract_state(
        db: Arc<RuntimeContractDb>,
    ) -> Result<Arc<WorkspaceCoreState>, &'static str> {
        Ok(Arc::new(WorkspaceCoreState::new(
            db,
            "service-secret".to_string(),
        )?))
    }

    fn row(name: &str, value: DbValue) -> DbRow {
        DbRow::new(BTreeMap::from([(name.to_string(), value)]))
    }

    fn public_workspace_row() -> DbRow {
        DbRow::new(BTreeMap::from([
            (
                "workspace_id".to_string(),
                DbValue::String("ws-1".to_string()),
            ),
            (
                "tenant_id".to_string(),
                DbValue::String("tenant-1".to_string()),
            ),
            (
                "project_id".to_string(),
                DbValue::String("project-1".to_string()),
            ),
            (
                "name".to_string(),
                DbValue::String("Workspace One".to_string()),
            ),
            (
                "created_by".to_string(),
                DbValue::String("user-1".to_string()),
            ),
            (
                "description".to_string(),
                DbValue::String("Avernet workspace".to_string()),
            ),
            ("is_archived".to_string(), DbValue::Bool(false)),
            (
                "metadata_json".to_string(),
                DbValue::String(json!({"use_case": "general"}).to_string()),
            ),
            (
                "office_status".to_string(),
                DbValue::String("active".to_string()),
            ),
            (
                "hex_layout_config_json".to_string(),
                DbValue::String(json!({"columns": 3}).to_string()),
            ),
            (
                "created_at".to_string(),
                DbValue::String("2026-08-10T00:00:00+00:00".to_string()),
            ),
            (
                "updated_at".to_string(),
                DbValue::String("2026-08-10T00:01:00+00:00".to_string()),
            ),
        ]))
    }

    fn public_agent_row() -> DbRow {
        DbRow::new(BTreeMap::from([
            (
                "binding_id".to_string(),
                DbValue::String("binding-1".to_string()),
            ),
            (
                "workspace_id".to_string(),
                DbValue::String("ws-1".to_string()),
            ),
            (
                "agent_id".to_string(),
                DbValue::String("agent-1".to_string()),
            ),
            (
                "display_name".to_string(),
                DbValue::String("Planner".to_string()),
            ),
            ("description".to_string(), DbValue::Null),
            (
                "config_json".to_string(),
                DbValue::String(json!({"temperature": 0.2}).to_string()),
            ),
            ("is_active".to_string(), DbValue::Bool(true)),
            ("hex_q".to_string(), DbValue::I64(2)),
            ("hex_r".to_string(), DbValue::I64(-1)),
            (
                "theme_color".to_string(),
                DbValue::String("#445566".to_string()),
            ),
            ("label".to_string(), DbValue::String("Lead".to_string())),
            ("status".to_string(), DbValue::String("idle".to_string())),
            (
                "created_at".to_string(),
                DbValue::String("2026-08-10T00:00:00+00:00".to_string()),
            ),
            ("updated_at".to_string(), DbValue::Null),
        ]))
    }

    fn public_member_row() -> DbRow {
        public_member_row_with_email(Some("user-1@example.com"))
    }

    fn public_member_row_with_email(email: Option<&str>) -> DbRow {
        DbRow::new(BTreeMap::from([
            (
                "member_id".to_string(),
                DbValue::String("member-1".to_string()),
            ),
            (
                "workspace_id".to_string(),
                DbValue::String("ws-1".to_string()),
            ),
            ("user_id".to_string(), DbValue::String("user-1".to_string())),
            (
                "user_email".to_string(),
                email.map_or(DbValue::Null, |value| DbValue::String(value.to_string())),
            ),
            ("role".to_string(), DbValue::String("owner".to_string())),
            ("invited_by".to_string(), DbValue::Null),
            (
                "created_at".to_string(),
                DbValue::String("2026-08-10T00:00:00+00:00".to_string()),
            ),
            ("updated_at".to_string(), DbValue::Null),
        ]))
    }

    fn contract_state() -> Result<Arc<WorkspaceCoreState>, &'static str> {
        Ok(Arc::new(WorkspaceCoreState::new(
            Arc::new(ContractDb),
            "service-secret".to_string(),
        )?))
    }

    #[tokio::test]
    async fn snapshot_requires_service_authorization() -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri("/internal/v1/workspaces/ws-1/snapshot?project_id=project-1")
            .header(TENANT_HEADER, "tenant-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;

        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
        Ok(())
    }

    #[tokio::test]
    async fn public_api_capability_is_authenticated_and_complete()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri("/internal/v1/capabilities/workspace-public-api")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["protocol_version"], 1);
        assert_eq!(payload["manifest_version"], 1);
        assert_eq!(payload["required_route_count"], 92);
        assert_eq!(payload["implemented_route_count"], 92);
        assert_eq!(
            payload["implemented_contract_sha256"],
            "a09965a43986fa5c23cc21a4f876b1e94fab475fefe1f9d679e41bf617660768"
        );
        assert_eq!(
            payload["implemented_route_keys_sha256"],
            "e4fea0501bbf438e30f55e0937246fda5709fdf4e3b7831c85147c6303bb3f07"
        );
        assert_eq!(payload["complete"], true);
        Ok(())
    }

    #[tokio::test]
    async fn public_workspace_read_preserves_legacy_response_shape()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri("/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "user-1")
            .header("x-memstack-user-is-superuser", "false")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["id"], "ws-1");
        assert_eq!(payload["tenant_id"], "tenant-1");
        assert_eq!(payload["metadata"], json!({"use_case": "general"}));
        assert_eq!(payload["hex_layout_config"], json!({"columns": 3}));
        Ok(())
    }

    #[tokio::test]
    async fn public_workspace_list_preserves_visibility_order_and_pagination_shape()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri("/api/v1/tenants/tenant-1/projects/project-1/workspaces?limit=20&offset=0")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "user-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload[0]["id"], "ws-1");
        assert_eq!(payload[0]["created_by"], "user-1");
        assert_eq!(payload[0]["is_archived"], false);
        Ok(())
    }

    #[tokio::test]
    async fn public_list_query_validation_matches_the_fastapi_422_envelope()
    -> Result<(), Box<dyn std::error::Error>> {
        let cases = [
            (
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces?limit=0",
                json!({
                    "detail": [{
                        "type": "greater_than_equal",
                        "loc": ["query", "limit"],
                        "msg": "Input should be greater than or equal to 1",
                        "input": "0",
                        "ctx": {"ge": 1},
                    }],
                }),
            ),
            (
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents\
                 ?active_only=banana",
                json!({
                    "detail": [{
                        "type": "bool_parsing",
                        "loc": ["query", "active_only"],
                        "msg": "Input should be a valid boolean, unable to interpret input",
                        "input": "banana",
                    }],
                }),
            ),
            (
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/members\
                 ?offset=-1",
                json!({
                    "detail": [{
                        "type": "greater_than_equal",
                        "loc": ["query", "offset"],
                        "msg": "Input should be greater than or equal to 0",
                        "input": "-1",
                        "ctx": {"ge": 0},
                    }],
                }),
            ),
        ];

        for (uri, expected) in cases {
            let request = Request::builder()
                .uri(uri)
                .header(header::AUTHORIZATION, "Bearer service-secret")
                .header("x-memstack-user-id", "user-1")
                .body(Body::empty())?;
            let response = workspace_router(contract_state()?).oneshot(request).await?;
            assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
            let body = to_bytes(response.into_body(), usize::MAX).await?;
            let payload: serde_json::Value = serde_json::from_slice(&body)?;
            assert_eq!(payload, expected);
        }
        Ok(())
    }

    #[tokio::test]
    async fn public_agent_list_preserves_binding_response_shape()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri(
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents\
                 ?active_only=true&limit=20&offset=0",
            )
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "user-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload[0]["id"], "binding-1");
        assert_eq!(payload[0]["agent_id"], "agent-1");
        assert_eq!(payload[0]["config"], json!({"temperature": 0.2}));
        assert_eq!(payload[0]["hex_q"], 2);
        assert_eq!(payload[0]["updated_at"], serde_json::Value::Null);
        Ok(())
    }

    #[tokio::test]
    async fn public_member_list_uses_the_scoped_principal_identity_projection()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri(
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/members\
                 ?limit=20&offset=0",
            )
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "user-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload[0]["id"], "member-1");
        assert_eq!(payload[0]["workspace_id"], "ws-1");
        assert_eq!(payload[0]["user_id"], "user-1");
        assert_eq!(payload[0]["user_email"], "user-1@example.com");
        assert_eq!(payload[0]["role"], "owner");
        assert_eq!(payload[0]["invited_by"], serde_json::Value::Null);
        Ok(())
    }

    #[tokio::test]
    async fn public_member_list_fails_closed_when_the_principal_identity_is_missing()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri(
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/members\
                 ?limit=20&offset=499",
            )
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "user-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;
        assert_eq!(payload["detail"], "Workspace Core is unavailable");
        Ok(())
    }

    #[tokio::test]
    async fn public_collaboration_capabilities_match_the_frozen_cloud_contract()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri(
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/\
                 collaboration/capabilities",
            )
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "user-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["service_version"], "0.2.0");
        assert_eq!(payload["contract_version"], "2.0.0");
        assert_eq!(payload["canonical_read"], true);
        assert_eq!(payload["mutations"]["revision_guarded"], true);
        assert_eq!(payload["allowed_actions"]["notes"], json!([]));
        assert_eq!(
            payload["allowed_actions"]["members"],
            json!(["add_member", "update_member_role", "remove_member"])
        );
        Ok(())
    }

    #[tokio::test]
    async fn public_authority_read_preserves_superuser_access_and_revision_cursor()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri(
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/\
                 collaboration/authority",
            )
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "superuser-1")
            .header("x-memstack-user-is-superuser", "true")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["revision"], 11);
        assert_eq!(payload["cursor"], "workspace:ws-1:revision:11");
        Ok(())
    }

    #[tokio::test]
    async fn public_workspace_read_preserves_legacy_membership_error()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri("/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "outsider-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;
        assert_eq!(payload, json!({"detail": "Access denied"}));
        Ok(())
    }

    #[tokio::test]
    async fn public_collaboration_read_rejects_a_cross_project_scope()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri(
                "/api/v1/tenants/tenant-1/projects/project-2/workspaces/ws-1/\
                 collaboration/capabilities",
            )
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "user-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;
        assert_eq!(payload, json!({"detail": "Workspace not found"}));
        Ok(())
    }

    #[tokio::test]
    async fn public_authority_read_preserves_legacy_membership_error()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri(
                "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/\
                 collaboration/authority",
            )
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("x-memstack-user-id", "outsider-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;
        assert_eq!(payload, json!({"detail": "Workspace access required"}));
        Ok(())
    }

    #[tokio::test]
    async fn snapshot_returns_scoped_counts_revision_and_hash()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri("/internal/v1/workspaces/ws-1/snapshot?project_id=project-1")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header(TENANT_HEADER, "tenant-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["tenant_id"], "tenant-1");
        assert_eq!(payload["project_id"], "project-1");
        assert_eq!(payload["workspace_id"], "ws-1");
        assert_eq!(payload["revision"], 7);
        assert_eq!(payload["counts"]["workspace_profiles"], 1);
        assert_eq!(
            payload["counts"].as_object().map(|counts| counts.len()),
            Some(SNAPSHOT_TABLES.len())
        );
        assert_eq!(payload["canonical_hash"].as_str().map(str::len), Some(64));
        Ok(())
    }

    #[tokio::test]
    async fn membership_check_is_scoped_by_tenant_workspace_and_user()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = Request::builder()
            .uri("/internal/v1/workspaces/ws-1/members/user-1")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header(TENANT_HEADER, "tenant-1")
            .body(Body::empty())?;

        let response = workspace_router(contract_state()?).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload, json!({ "allowed": true }));
        Ok(())
    }

    #[tokio::test]
    async fn runtime_correlation_is_idempotently_recorded() -> Result<(), Box<dyn std::error::Error>>
    {
        let db = Arc::new(RuntimeContractDb::default());
        let request = Request::builder()
            .method("POST")
            .uri("/internal/v1/runtime-correlations")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header(TENANT_HEADER, "tenant-1")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "correlation_id": "correlation-1",
                    "project_id": "project-1",
                    "workspace_id": "ws-1",
                    "user_id": "user-1",
                    "task_id": "task-1",
                    "plan_id": "plan-1",
                    "plan_node_id": "node-1",
                    "conversation_id": "conversation-1",
                    "bcs_session_id": "session-1",
                    "bcs_group_id": "group-1",
                    "delivery_request_id": "delivery-1",
                    "provider_run_id": "provider-run-1",
                    "provider_id": "provider-1",
                    "provider_bot_ref": "agent-1"
                })
                .to_string(),
            ))?;

        let response = workspace_router(runtime_contract_state(db.clone())?)
            .oneshot(request)
            .await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["correlation_id"], "correlation-1");
        assert_eq!(payload["status"], "running");
        assert_eq!(payload["created"], true);
        let transactions = db
            .transactions
            .lock()
            .map_err(|_| "runtime transactions lock poisoned")?;
        assert_eq!(transactions.len(), 1);
        assert_eq!(transactions[0].len(), 2);
        let correlation_insert = match &transactions[0][0] {
            DbTransactionStep::Execute(statement) => statement,
            _ => return Err("runtime correlation insert statement is missing".into()),
        };
        assert!(
            correlation_insert
                .sql()
                .contains("JOIN workspace_authorities authority")
        );
        Ok(())
    }

    #[tokio::test]
    async fn runtime_terminal_atomically_records_plan_event_outbox_and_terminal()
    -> Result<(), Box<dyn std::error::Error>> {
        let db = Arc::new(RuntimeContractDb::default());
        let request = Request::builder()
            .method("POST")
            .uri("/internal/v1/runtime-correlations/correlation-1/terminal")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header(TENANT_HEADER, "tenant-1")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "project_id": "project-1",
                    "workspace_id": "ws-1",
                    "execution_status": "complete",
                    "terminal_message_id": "message-1",
                    "terminal_event_id": "legacy-event-1",
                    "report": {"content": "done"}
                })
                .to_string(),
            ))?;

        let response = workspace_router(runtime_contract_state(db.clone())?)
            .oneshot(request)
            .await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["status"], "completed");
        assert_eq!(payload["terminal_id"], "runtime-terminal-correlation-1");
        assert_eq!(payload["report_hash"].as_str().map(str::len), Some(64));
        let transactions = db
            .transactions
            .lock()
            .map_err(|_| "runtime transactions lock poisoned")?;
        assert_eq!(transactions.len(), 1);
        let transaction_sql = transactions[0]
            .iter()
            .filter_map(|step| match step {
                DbTransactionStep::Execute(statement)
                | DbTransactionStep::ExecuteChecked { statement, .. } => Some(statement.sql()),
                DbTransactionStep::Query(_) | DbTransactionStep::QueryChecked { .. } => None,
            })
            .collect::<Vec<_>>()
            .join("\n");
        assert!(transaction_sql.contains("INSERT INTO workspace_plan_events"));
        assert!(transaction_sql.contains("INSERT INTO workspace_outbox"));
        assert!(transaction_sql.contains("INSERT INTO workspace_execution_terminals"));
        assert!(matches!(
            transactions[0].last(),
            Some(DbTransactionStep::QueryChecked { expected_rows, .. })
                if *expected_rows == DbCountExpectation::exactly(1)
        ));
        let terminal_insert = transactions[0]
            .iter()
            .find_map(|step| match step {
                DbTransactionStep::Execute(statement)
                    if statement
                        .sql()
                        .starts_with("INSERT INTO workspace_execution_terminals") =>
                {
                    Some(statement)
                }
                _ => None,
            })
            .ok_or("terminal insert statement is missing")?;
        assert_eq!(
            terminal_insert.params().get(3),
            Some(&DbValue::String("legacy-event-1".to_string()))
        );
        assert_eq!(
            terminal_insert.params().get(4),
            Some(&DbValue::String(
                "runtime-plan-event-correlation-1".to_string()
            ))
        );
        Ok(())
    }

    #[tokio::test]
    async fn runtime_terminal_read_replays_only_scoped_persisted_proof()
    -> Result<(), Box<dyn std::error::Error>> {
        let db = Arc::new(RuntimeContractDb::default());
        let request = Request::builder()
            .uri(
                "/internal/v1/runtime-correlations/correlation-1/terminal\
                 ?project_id=project-1&workspace_id=ws-1",
            )
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header(TENANT_HEADER, "tenant-1")
            .body(Body::empty())?;

        let response = workspace_router(runtime_contract_state(db)?)
            .oneshot(request)
            .await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["correlation_id"], "correlation-1");
        assert_eq!(payload["status"], "completed");
        assert_eq!(payload["terminal_event_id"], "legacy-event-1");
        assert_eq!(payload["report"], json!({"content": "done"}));
        assert_eq!(payload["persisted"], true);
        Ok(())
    }

    #[tokio::test]
    async fn runtime_recovery_claim_returns_only_structured_callback_context()
    -> Result<(), Box<dyn std::error::Error>> {
        let db = Arc::new(RuntimeContractDb::default());
        let request = Request::builder()
            .method("POST")
            .uri("/internal/v1/runtime-recoveries/claim")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "lease_owner": "worker-1",
                    "stale_after_seconds": 60,
                    "lease_seconds": 30,
                    "limit": 20
                })
                .to_string(),
            ))?;

        let response = workspace_router(runtime_contract_state(db)?)
            .oneshot(request)
            .await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["recoveries"][0]["correlation_id"], "correlation-1");
        assert_eq!(payload["recoveries"][0]["user_id"], "user-1");
        assert_eq!(payload["recoveries"][0]["bcs_group_id"], "group-1");
        assert_eq!(payload["recoveries"][0]["provider_id"], "provider-1");
        assert_eq!(payload["recoveries"][0]["recovery_attempt_count"], 1);
        Ok(())
    }

    #[tokio::test]
    async fn runtime_callback_ack_is_terminal_and_scope_bound()
    -> Result<(), Box<dyn std::error::Error>> {
        let db = Arc::new(RuntimeContractDb::default());
        let request = Request::builder()
            .method("POST")
            .uri("/internal/v1/runtime-correlations/correlation-1/callback-ack")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header(TENANT_HEADER, "tenant-1")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({"project_id": "project-1", "workspace_id": "ws-1"}).to_string(),
            ))?;

        let response = workspace_router(runtime_contract_state(db)?)
            .oneshot(request)
            .await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;

        assert_eq!(payload["status"], "completed");
        assert_eq!(payload["acknowledged"], true);
        Ok(())
    }

    #[tokio::test]
    async fn runtime_recovery_judgment_is_audited_before_lease_release()
    -> Result<(), Box<dyn std::error::Error>> {
        let db = Arc::new(RuntimeContractDb::default());
        let request = Request::builder()
            .method("POST")
            .uri("/internal/v1/runtime-correlations/correlation-1/recovery-judgments")
            .header(header::AUTHORIZATION, "Bearer service-secret")
            .header(TENANT_HEADER, "tenant-1")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "audit_id": "audit-1",
                    "project_id": "project-1",
                    "workspace_id": "ws-1",
                    "lease_owner": "worker-1",
                    "action": "continue",
                    "agent_id": "judge-agent",
                    "tool_name": "decide_runtime_recovery",
                    "input_json": {"has_terminal": false},
                    "output_json": {"action": "continue"},
                    "rationale": "execution may still be active",
                    "latency_ms": 12
                })
                .to_string(),
            ))?;

        let response = workspace_router(runtime_contract_state(db.clone())?)
            .oneshot(request)
            .await?;
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await?;
        let payload: serde_json::Value = serde_json::from_slice(&body)?;
        assert_eq!(payload["action"], "continue");
        assert_eq!(payload["recorded"], true);

        let transactions = db
            .transactions
            .lock()
            .map_err(|_| "runtime transactions lock poisoned")?;
        assert_eq!(transactions[0].len(), 3);
        Ok(())
    }
}
