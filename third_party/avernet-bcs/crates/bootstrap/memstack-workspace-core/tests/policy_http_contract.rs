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
    TenantId,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "policy-http-contract-token";

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

struct FakeProviderRegistry;

#[async_trait]
impl ProviderRegistryPort for FakeProviderRegistry {
    async fn resolve(
        &self,
        lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        let allowed = matches!(
            (lookup.provider_id().as_str(), lookup.model_id().as_str()),
            ("provider-1", "model-1") | ("provider-2", "model-2")
        );
        if !allowed {
            return Ok(None);
        }
        ProviderRegistryRoute::parse(lookup.provider_id().as_str(), lookup.model_id().as_str())
            .map(Some)
            .map_err(|_| ProviderRegistryPortError::Unavailable)
    }

    async fn tenant_default(
        &self,
        _tenant_id: &TenantId,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        ProviderRegistryRoute::parse("provider-1", "model-1")
            .map(Some)
            .map_err(|_| ProviderRegistryPortError::Unavailable)
    }
}

#[tokio::test]
async fn policy_http_routes_preserve_legacy_shapes_cas_access_and_events()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_registries(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(UnusedAgentRegistry),
        Arc::new(FakeProviderRegistry),
    )?);

    let default = send(
        state.clone(),
        "GET",
        "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy",
        "project-owner",
        None,
    )
    .await?;
    assert_eq!(default.status(), StatusCode::OK);
    let default = response_json(default).await?;
    assert_policy_shape(&default)?;
    assert_eq!(default["revision"], 0);
    assert_eq!(default["roles"]["default"]["provider_id"], "provider-1");

    let patched = send(
        state.clone(),
        "PATCH",
        "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy",
        "project-owner",
        Some(json!({
            "expected_revision": 0,
            "capability_mode": "code",
            "route": {"provider_id": "provider-1", "model_id": "model-1"},
            "reasoning_effort": "high",
            "permission_mode": "automatic"
        })),
    )
    .await?;
    assert_eq!(patched.status(), StatusCode::OK);
    let patched = response_json(patched).await?;
    assert_policy_shape(&patched)?;
    assert_eq!(patched["revision"], 1);
    assert_eq!(patched["roles"]["coding"]["model_id"], "model-1");

    let legacy = send(
        state.clone(),
        "GET",
        "/api/v1/llm-providers/routing-policy?project_id=project-1&workspace_id=workspace-1",
        "project-owner",
        None,
    )
    .await?;
    assert_eq!(legacy.status(), StatusCode::OK);
    assert_eq!(response_json(legacy).await?, patched);

    let replaced = send(
        state.clone(),
        "PUT",
        "/api/v1/llm-providers/routing-policy",
        "project-owner",
        Some(json!({
            "project_id": "project-1",
            "workspace_id": "workspace-1",
            "expected_revision": 1,
            "roles": {
                "default": {"provider_id": "provider-2", "model_id": "model-2"},
                "fast": null,
                "coding": null,
                "vision": null
            },
            "fallbacks": [
                {"provider_id": "provider-1", "model_id": "model-1"}
            ]
        })),
    )
    .await?;
    assert_eq!(replaced.status(), StatusCode::OK);
    let replaced = response_json(replaced).await?;
    assert_policy_shape(&replaced)?;
    assert_eq!(replaced["revision"], 2);
    assert_eq!(replaced["roles"]["default"]["provider_id"], "provider-2");
    assert_eq!(replaced["fallbacks"][0]["model_id"], "model-1");

    let forbidden = send(
        state.clone(),
        "PATCH",
        "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy",
        "project-viewer",
        Some(json!({
            "expected_revision": 2,
            "capability_mode": "work",
            "route": {"provider_id": "provider-1", "model_id": "model-1"},
            "reasoning_effort": "medium",
            "permission_mode": "ask"
        })),
    )
    .await?;
    assert_eq!(forbidden.status(), StatusCode::FORBIDDEN);
    assert_eq!(response_json(forbidden).await?["detail"], "Access denied");

    let invalid = send(
        state.clone(),
        "PATCH",
        "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy",
        "project-owner",
        Some(json!({
            "expected_revision": 2,
            "capability_mode": "work",
            "route": {"provider_id": "missing", "model_id": "missing"},
            "reasoning_effort": "medium",
            "permission_mode": "ask"
        })),
    )
    .await?;
    assert_eq!(invalid.status(), StatusCode::BAD_REQUEST);
    assert_eq!(
        response_json(invalid).await?["detail"],
        "Invalid provider route"
    );

    let stale = send(
        state,
        "PATCH",
        "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agent-policy",
        "project-owner",
        Some(json!({
            "expected_revision": 1,
            "capability_mode": "work",
            "route": {"provider_id": "provider-1", "model_id": "model-1"},
            "reasoning_effort": "low",
            "permission_mode": "ask"
        })),
    )
    .await?;
    assert_eq!(stale.status(), StatusCode::CONFLICT);
    assert_eq!(
        response_json(stale).await?["detail"],
        "Workspace policy revision conflict"
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 2);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        2
    );
    Ok(())
}

async fn send(
    state: Arc<WorkspaceCoreState>,
    method: &str,
    uri: &str,
    actor_id: &str,
    body: Option<Value>,
) -> Result<Response<Body>, Box<dyn Error>> {
    let method = Method::from_bytes(method.as_bytes())?;
    let mut request = Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", actor_id)
        .header("x-memstack-user-is-superuser", "false");
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

fn assert_policy_shape(response: &Value) -> Result<(), Box<dyn Error>> {
    let actual = response
        .as_object()
        .ok_or("Policy response must be a JSON object")?
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let expected = [
        "capability_version",
        "fallbacks",
        "permission_mode",
        "project_id",
        "reasoning_effort",
        "revision",
        "roles",
        "tenant_id",
        "updated_at",
        "workspace_id",
    ]
    .into_iter()
    .collect::<BTreeSet<_>>();
    assert_eq!(actual, expected);
    assert_eq!(response["capability_version"], "workspace-agent-policy-v1");
    assert!(response["updated_at"].as_str().is_some());
    Ok(())
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT, UNIQUE(tenant_id, project_id, workspace_id))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_agent_policies (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, roles_json TEXT NOT NULL DEFAULT '{}', fallbacks_json TEXT NOT NULL DEFAULT '[]', reasoning_effort TEXT NOT NULL DEFAULT 'medium', permission_mode TEXT NOT NULL DEFAULT 'ask', updated_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    for statement in [
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1', 'Policy Space', 'workspace-owner')",
        "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES ('workspace-1', 'tenant-1', 'project-1', 1)",
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, role, is_active) VALUES ('tenant-1', 'project-1', 'project-owner', 'project-owner', 'owner', 1)",
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, role, is_active) VALUES ('tenant-1', 'project-1', 'project-viewer', 'project-viewer', 'viewer', 1)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        _ => return Err("unsupported table".into()),
    };
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}
