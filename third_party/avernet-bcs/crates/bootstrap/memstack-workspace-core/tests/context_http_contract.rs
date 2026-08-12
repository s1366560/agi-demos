use std::collections::BTreeSet;
use std::error::Error;
use std::sync::Arc;

use async_trait::async_trait;
use axum::body::{Body, to_bytes};
use axum::http::{Method, Request, Response, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use memstack_workspace_service_api::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, ProviderRegistryRoute,
    TenantId, WorkspaceContextJudgePort, WorkspaceContextJudgePortError, WorkspaceContextJudgment,
    WorkspaceContextJudgmentRequest,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "context-http-contract-token";

struct UnusedAgentRegistry;

#[async_trait]
impl AgentRegistryPort for UnusedAgentRegistry {
    async fn resolve(
        &self,
        _lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError> {
        Err(AgentRegistryPortError::Unavailable)
    }
}

struct UnusedProviderRegistry;

#[async_trait]
impl ProviderRegistryPort for UnusedProviderRegistry {
    async fn resolve(
        &self,
        _lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        Err(ProviderRegistryPortError::Unavailable)
    }

    async fn tenant_default(
        &self,
        _tenant_id: &TenantId,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        Err(ProviderRegistryPortError::Unavailable)
    }
}

struct SecondCandidateJudge;

#[async_trait]
impl WorkspaceContextJudgePort for SecondCandidateJudge {
    async fn select(
        &self,
        request: &WorkspaceContextJudgmentRequest,
    ) -> Result<WorkspaceContextJudgment, WorkspaceContextJudgePortError> {
        let selected = request
            .candidates()
            .get(1)
            .cloned()
            .ok_or(WorkspaceContextJudgePortError::Unavailable)?;
        WorkspaceContextJudgment::new(
            request,
            1,
            selected,
            "structured HTTP contract rationale".to_string(),
            Vec::new(),
            "judge-agent".to_string(),
            "select_workspace_context".to_string(),
            json!({"candidate_count": 2}),
            json!({"candidate_index": 1}),
            4,
        )
        .map_err(|_| WorkspaceContextJudgePortError::Unavailable)
    }
}

#[tokio::test]
async fn context_http_routes_preserve_shapes_errors_cas_replay_and_agent_judgment()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_authorities(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(UnusedAgentRegistry),
        Arc::new(UnusedProviderRegistry),
        Arc::new(SecondCandidateJudge),
    )?);

    let initialized = send(
        state.clone(),
        "GET",
        "/api/v1/workspace-context",
        "user-1",
        None,
    )
    .await?;
    assert_eq!(initialized.status(), StatusCode::OK);
    let initialized = response_json(initialized).await?;
    assert_context_access_shape(&initialized)?;
    assert_eq!(initialized["context"]["tenant_id"], "tenant-2");
    assert_eq!(initialized["context"]["project_id"], "project-2");
    assert_eq!(initialized["context"]["revision"], 0);
    assert_eq!(initialized["membership_role"], "owner");

    let switched = send(
        state.clone(),
        "POST",
        "/api/v1/workspace-context/switch",
        "user-1",
        Some(json!({
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "expected_revision": 0,
            "idempotency_key": "switch-http-1"
        })),
    )
    .await?;
    assert_eq!(switched.status(), StatusCode::OK);
    let switched = response_json(switched).await?;
    assert_context_switch_shape(&switched)?;
    assert_eq!(switched["context"]["revision"], 1);
    assert_eq!(switched["changed"], true);

    let replayed = send(
        state.clone(),
        "POST",
        "/api/v1/workspace-context/switch",
        "user-1",
        Some(json!({
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "expected_revision": 0,
            "idempotency_key": "switch-http-1"
        })),
    )
    .await?;
    assert_eq!(replayed.status(), StatusCode::OK);
    let replayed = response_json(replayed).await?;
    assert_eq!(replayed["context"], switched["context"]);
    assert_eq!(replayed["changed"], false);

    let idempotency_conflict = send(
        state.clone(),
        "POST",
        "/api/v1/workspace-context/switch",
        "user-1",
        Some(json!({
            "tenant_id": "tenant-2",
            "project_id": "project-2",
            "expected_revision": 0,
            "idempotency_key": "switch-http-1"
        })),
    )
    .await?;
    assert_eq!(idempotency_conflict.status(), StatusCode::CONFLICT);
    assert_eq!(
        response_json(idempotency_conflict).await?,
        json!({"detail": {"code": "workspace_context_idempotency_conflict"}})
    );

    let stale = send(
        state.clone(),
        "POST",
        "/api/v1/workspace-context/switch",
        "user-1",
        Some(json!({
            "tenant_id": "tenant-2",
            "project_id": "project-2",
            "expected_revision": 0,
            "idempotency_key": "switch-http-stale"
        })),
    )
    .await?;
    assert_eq!(stale.status(), StatusCode::CONFLICT);
    assert_eq!(
        response_json(stale).await?,
        json!({
            "detail": {
                "code": "workspace_context_revision_conflict",
                "expected_revision": 0,
                "actual_revision": 1
            }
        })
    );

    let forbidden = send(
        state.clone(),
        "POST",
        "/api/v1/workspace-context/switch",
        "user-1",
        Some(json!({
            "tenant_id": "tenant-missing",
            "project_id": "project-missing",
            "expected_revision": 1,
            "idempotency_key": "switch-http-forbidden"
        })),
    )
    .await?;
    assert_eq!(forbidden.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        response_json(forbidden).await?,
        json!({"detail": {"code": "workspace_context_membership_required"}})
    );

    let project_unavailable = send(
        state.clone(),
        "POST",
        "/api/v1/workspace-context/switch",
        "user-1",
        Some(json!({
            "tenant_id": "tenant-1",
            "project_id": "project-missing",
            "expected_revision": 1,
            "idempotency_key": "switch-http-project-missing"
        })),
    )
    .await?;
    assert_eq!(project_unavailable.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        response_json(project_unavailable).await?,
        json!({"detail": {"code": "workspace_context_project_unavailable"}})
    );

    let unavailable = send(
        state.clone(),
        "GET",
        "/api/v1/workspace-context",
        "user-without-memberships",
        None,
    )
    .await?;
    assert_eq!(unavailable.status(), StatusCode::NOT_FOUND);
    assert_eq!(
        response_json(unavailable).await?,
        json!({"detail": {"code": "workspace_context_unavailable"}})
    );

    let invalid = send(
        state.clone(),
        "POST",
        "/api/v1/workspace-context/switch",
        "user-1",
        Some(json!({
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "expected_revision": -1,
            "idempotency_key": "switch-http-invalid",
            "extra": true
        })),
    )
    .await?;
    assert_eq!(invalid.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(invalid).await?,
        json!({
            "detail": [
                {
                    "type": "greater_than_equal",
                    "loc": ["body", "expected_revision"],
                    "msg": "Input should be greater than or equal to 0",
                    "input": -1,
                    "ctx": {"ge": 0}
                },
                {
                    "type": "extra_forbidden",
                    "loc": ["body", "extra"],
                    "msg": "Extra inputs are not permitted",
                    "input": true
                }
            ]
        })
    );

    let missing = send(
        state,
        "POST",
        "/api/v1/workspace-context/switch",
        "user-1",
        Some(json!({})),
    )
    .await?;
    assert_eq!(missing.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(missing).await?,
        json!({
            "detail": [
                {
                    "type": "missing",
                    "loc": ["body", "tenant_id"],
                    "msg": "Field required",
                    "input": {}
                },
                {
                    "type": "missing",
                    "loc": ["body", "project_id"],
                    "msg": "Field required",
                    "input": {}
                },
                {
                    "type": "missing",
                    "loc": ["body", "expected_revision"],
                    "msg": "Field required",
                    "input": {}
                },
                {
                    "type": "missing",
                    "loc": ["body", "idempotency_key"],
                    "msg": "Field required",
                    "input": {}
                }
            ]
        })
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_context_events").await?,
        1
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_context_outbox").await?,
        2
    );
    assert_eq!(table_count(db.as_ref(), "workspace_judge_audits").await?, 1);
    Ok(())
}

async fn send(
    state: Arc<WorkspaceCoreState>,
    method: &str,
    uri: &str,
    user_id: &str,
    body: Option<Value>,
) -> Result<Response<Body>, Box<dyn Error>> {
    let method = Method::from_bytes(method.as_bytes())?;
    let mut request = Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", user_id)
        .header("x-memstack-api-key-id", "api-key-1");
    if body.is_some() {
        request = request.header(header::CONTENT_TYPE, "application/json");
    }
    let body = body.map_or_else(Body::empty, |value| Body::from(value.to_string()));
    Ok(workspace_router(state).oneshot(request.body(body)?).await?)
}

async fn response_json(response: Response<Body>) -> Result<Value, Box<dyn Error>> {
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn assert_context_access_shape(response: &Value) -> Result<(), Box<dyn Error>> {
    assert_eq!(
        object_keys(response)?,
        ["context", "membership_role"].into_iter().collect()
    );
    assert_context_shape(&response["context"])
}

fn assert_context_switch_shape(response: &Value) -> Result<(), Box<dyn Error>> {
    assert_eq!(
        object_keys(response)?,
        ["changed", "context"].into_iter().collect()
    );
    assert_context_shape(&response["context"])
}

fn assert_context_shape(response: &Value) -> Result<(), Box<dyn Error>> {
    assert_eq!(
        object_keys(response)?,
        ["project_id", "revision", "tenant_id", "updated_at"]
            .into_iter()
            .collect()
    );
    let updated_at = response["updated_at"]
        .as_str()
        .ok_or("updated_at must be a string")?;
    let timestamp = updated_at
        .strip_suffix('Z')
        .ok_or("updated_at must use the UTC Z suffix")?;
    let (_, fractional) = timestamp
        .rsplit_once('.')
        .ok_or("updated_at must include fractional seconds")?;
    assert_eq!(fractional.len(), 6);
    assert!(fractional.chars().all(|value| value.is_ascii_digit()));
    Ok(())
}

fn object_keys(response: &Value) -> Result<BTreeSet<&str>, Box<dyn Error>> {
    Ok(response
        .as_object()
        .ok_or("response must be an object")?
        .keys()
        .map(String::as_str)
        .collect())
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE workspace_contexts (user_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_context_events (event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, actor_api_key_id TEXT, from_tenant_id TEXT, from_project_id TEXT, to_tenant_id TEXT NOT NULL, to_project_id TEXT NOT NULL, revision INTEGER NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, value_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(user_id, idempotency_key), UNIQUE(user_id, revision))",
        "CREATE TABLE workspace_judge_audits (audit_id TEXT PRIMARY KEY, tenant_id TEXT, project_id TEXT, workspace_id TEXT, plan_id TEXT, plan_node_id TEXT, user_id TEXT, judgment_type TEXT NOT NULL, agent_id TEXT NOT NULL, tool_name TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL, rationale TEXT NOT NULL, latency_ms INTEGER NOT NULL, status TEXT NOT NULL, error_detail TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE workspace_context_outbox (outbox_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, actor_api_key_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 12, next_attempt_at TEXT, lease_owner TEXT, lease_expires_at TEXT, dispatched_at TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id, idempotency_key), UNIQUE(user_id, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    for statement in [
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, role, is_active) VALUES ('tenant-1', 'project-1', 'user-1', 'member', 1)",
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, role, is_active) VALUES ('tenant-2', 'project-2', 'user-1', 'owner', 1)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_context_events" => "SELECT COUNT(*) AS value FROM workspace_context_events",
        "workspace_context_outbox" => "SELECT COUNT(*) AS value FROM workspace_context_outbox",
        "workspace_judge_audits" => "SELECT COUNT(*) AS value FROM workspace_judge_audits",
        _ => return Err("unsupported table".into()),
    };
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing count row")?
        .get_i64("value")?
        .ok_or("missing count")?)
}
