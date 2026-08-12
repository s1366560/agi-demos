use std::collections::BTreeSet;
use std::error::Error;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use axum::body::{Body, to_bytes};
use axum::http::{Request, Response, StatusCode, header};
use bcs_db_api::{
    DbError, DbExecuteResult, DbHealth, DbPlugin, DbResult, DbRow, DbSqlFlavor, DbStatement,
    DbTransactionStep, DbTransactionStepResult,
};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use memstack_workspace_service_api::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "agent-http-contract-token";
const THEME_COLOR_32: &str = "12345678901234567890123456789012";

#[derive(Clone, Copy)]
enum RegistryMode {
    Available,
    Missing,
    Unavailable,
}

struct FakeAgentRegistry {
    mode: RegistryMode,
    calls: AtomicUsize,
}

impl FakeAgentRegistry {
    fn new(mode: RegistryMode) -> Self {
        Self {
            mode,
            calls: AtomicUsize::new(0),
        }
    }

    fn calls(&self) -> usize {
        self.calls.load(Ordering::Relaxed)
    }
}

#[async_trait]
impl AgentRegistryPort for FakeAgentRegistry {
    async fn resolve(
        &self,
        lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        match self.mode {
            RegistryMode::Available => AgentRegistryAgent::parse(
                lookup.agent_id().as_str(),
                "planner",
                Some("Registry Planner".to_string()),
                true,
            )
            .map(Some)
            .map_err(|_| AgentRegistryPortError::Unavailable),
            RegistryMode::Missing => Ok(None),
            RegistryMode::Unavailable => Err(AgentRegistryPortError::Unavailable),
        }
    }
}

struct UnusedDb;

#[async_trait]
impl DbPlugin for UnusedDb {
    async fn query(&self, _statement: DbStatement) -> DbResult<Vec<DbRow>> {
        Err(DbError::Unsupported("query must not run".to_string()))
    }

    async fn execute(&self, _statement: DbStatement) -> DbResult<DbExecuteResult> {
        Err(DbError::Unsupported("execute must not run".to_string()))
    }

    async fn transaction(
        &self,
        _steps: Vec<DbTransactionStep>,
    ) -> DbResult<Vec<DbTransactionStepResult>> {
        Err(DbError::Unsupported("transaction must not run".to_string()))
    }

    async fn health_check(&self) -> DbResult<DbHealth> {
        Ok(DbHealth::healthy())
    }
}

#[tokio::test]
async fn agent_http_mutations_preserve_legacy_shape_replay_and_atomic_roster()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(agent_db().await?);
    let registry = Arc::new(FakeAgentRegistry::new(RegistryMode::Available));
    let state = state(db.clone(), registry.clone())?;
    create_workspace(state.clone()).await?;

    let first = send(
        state.clone(),
        agent_request(
            "POST",
            None,
            "owner-1",
            Some(json!({
                "agent_id": "agent-1",
                "display_name": "Workspace Planner",
                "description": "Plans work",
                "config": {"mode": "plan"},
                "is_active": true,
                "hex_q": 2,
                "hex_r": -1,
                "theme_color": THEME_COLOR_32,
                "label": "planner"
            })),
            Some("http-agent-bind"),
            Some("1"),
        )?,
    )
    .await?;
    assert_eq!(first.status(), StatusCode::CREATED);
    let first = response_json(first).await?;
    assert_agent_response_shape(&first)?;
    let binding_id = first["id"].as_str().ok_or("missing binding id")?;
    assert_eq!(first["workspace_id"], "workspace-1");
    assert_eq!(first["agent_id"], "agent-1");
    assert_eq!(first["display_name"], "Workspace Planner");
    assert_eq!(first["config"], json!({"mode": "plan"}));
    assert_eq!(first["theme_color"], THEME_COLOR_32);
    assert_eq!(registry.calls(), 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_agent_bindings").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "bcs_bots").await?, 1);
    assert_eq!(bot_participant_count(db.as_ref()).await?, 1);

    let rebound = send(
        state.clone(),
        agent_request(
            "POST",
            None,
            "owner-1",
            Some(json!({
                "agent_id": "agent-1",
                "display_name": "Renamed Planner",
                "config": {"mode": "review"},
                "is_active": false,
                "hex_q": 3,
                "hex_r": -1,
                "theme_color": THEME_COLOR_32,
                "label": "review"
            })),
            Some("http-agent-rebind"),
            Some("2"),
        )?,
    )
    .await?;
    assert_eq!(rebound.status(), StatusCode::CREATED);
    let rebound = response_json(rebound).await?;
    assert_eq!(rebound["id"], binding_id);
    assert_eq!(rebound["display_name"], "Renamed Planner");
    assert_eq!(rebound["is_active"], false);
    assert_eq!(outbox_payload(db.as_ref(), 3).await?["is_update"], true);
    assert_eq!(registry.calls(), 2);

    let updated = send(
        state.clone(),
        agent_request(
            "PATCH",
            Some(binding_id),
            "owner-1",
            Some(json!({
                "description": "Updated through HTTP",
                "is_active": true,
                "hex_q": 4,
                "hex_r": -2,
                "label": "relay"
            })),
            Some("http-agent-update"),
            Some("3"),
        )?,
    )
    .await?;
    assert_eq!(updated.status(), StatusCode::OK);
    let updated = response_json(updated).await?;
    assert_agent_response_shape(&updated)?;
    assert_eq!(updated["id"], binding_id);
    assert_eq!(updated["description"], "Updated through HTTP");
    assert_eq!(updated["config"], json!({"mode": "review"}));
    assert_eq!(updated["hex_q"], 4);
    assert_eq!(updated["hex_r"], -2);

    let deleted = send(
        state.clone(),
        agent_request(
            "DELETE",
            Some(binding_id),
            "owner-1",
            None,
            Some("http-agent-unbind"),
            Some("4"),
        )?,
    )
    .await?;
    assert_eq!(deleted.status(), StatusCode::NO_CONTENT);
    assert!(to_bytes(deleted.into_body(), usize::MAX).await?.is_empty());

    let replayed = send(
        state,
        agent_request(
            "DELETE",
            Some(binding_id),
            "owner-1",
            None,
            Some("http-agent-unbind"),
            Some("4"),
        )?,
    )
    .await?;
    assert_eq!(replayed.status(), StatusCode::NO_CONTENT);
    assert!(to_bytes(replayed.into_body(), usize::MAX).await?.is_empty());
    assert_eq!(
        table_count(db.as_ref(), "workspace_agent_bindings").await?,
        0
    );
    assert_eq!(table_count(db.as_ref(), "bcs_bots").await?, 0);
    assert_eq!(bot_participant_count(db.as_ref()).await?, 0);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        5
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 5);
    Ok(())
}

#[tokio::test]
async fn agent_http_validation_preserves_legacy_422_envelopes() -> Result<(), Box<dyn Error>> {
    let state = state(
        Arc::new(UnusedDb),
        Arc::new(FakeAgentRegistry::new(RegistryMode::Available)),
    )?;

    let cases = [
        (
            agent_request(
                "POST",
                None,
                "owner-1",
                Some(json!({"agent_id": "agent-1", "unknown": true})),
                None,
                None,
            )?,
            json!({"detail": [{
                "type": "extra_forbidden",
                "loc": ["body", "unknown"],
                "msg": "Extra inputs are not permitted",
                "input": true
            }]}),
        ),
        (
            agent_request(
                "PATCH",
                Some("binding-1"),
                "owner-1",
                Some(json!({"status": "busy"})),
                None,
                None,
            )?,
            json!({"detail": [{
                "type": "extra_forbidden",
                "loc": ["body", "status"],
                "msg": "Extra inputs are not permitted",
                "input": "busy"
            }]}),
        ),
        (
            agent_request(
                "POST",
                None,
                "owner-1",
                Some(json!({"agent_id": "agent-1", "hex_q": 25, "hex_r": 0})),
                None,
                None,
            )?,
            json!({"detail": [{
                "type": "less_than_equal",
                "loc": ["body", "hex_q"],
                "msg": "Input should be less than or equal to 24",
                "input": 25,
                "ctx": {"le": 24}
            }]}),
        ),
    ];

    for (request, expected) in cases {
        let response = send(state.clone(), request).await?;
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(response_json(response).await?, expected);
    }
    Ok(())
}

#[tokio::test]
async fn agent_http_rejects_invalid_hex_pairs_without_partial_writes() -> Result<(), Box<dyn Error>>
{
    let db = Arc::new(agent_db().await?);
    let state = state(
        db.clone(),
        Arc::new(FakeAgentRegistry::new(RegistryMode::Available)),
    )?;
    create_workspace(state.clone()).await?;

    for (idempotency_key, payload) in [
        (
            "reserved-center",
            json!({"agent_id": "agent-1", "hex_q": 0, "hex_r": 0}),
        ),
        (
            "partial-position",
            json!({"agent_id": "agent-1", "hex_q": 2}),
        ),
        (
            "outside-radius",
            json!({"agent_id": "agent-1", "hex_q": 24, "hex_r": 24}),
        ),
    ] {
        let response = send(
            state.clone(),
            agent_request(
                "POST",
                None,
                "owner-1",
                Some(payload),
                Some(idempotency_key),
                Some("1"),
            )?,
        )
        .await?;
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        assert_eq!(
            response_json(response).await?,
            json!({"detail": "Invalid workspace request"})
        );
    }

    assert_eq!(workspace_revision(db.as_ref()).await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_agent_bindings").await?,
        0
    );
    assert_eq!(table_count(db.as_ref(), "bcs_bots").await?, 0);
    assert_eq!(bot_participant_count(db.as_ref()).await?, 0);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);
    Ok(())
}

#[tokio::test]
async fn agent_http_fails_closed_for_registry_permissions_and_stale_revision()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(agent_db().await?);
    let missing = Arc::new(FakeAgentRegistry::new(RegistryMode::Missing));
    let missing_state = state(db.clone(), missing.clone())?;
    create_workspace(missing_state.clone()).await?;

    let missing_response = send(
        missing_state,
        agent_request(
            "POST",
            None,
            "owner-1",
            Some(json!({"agent_id": "agent-missing", "hex_q": 2, "hex_r": -1})),
            Some("missing-agent"),
            Some("1"),
        )?,
    )
    .await?;
    assert_eq!(missing_response.status(), StatusCode::BAD_REQUEST);
    assert_eq!(
        response_json(missing_response).await?,
        json!({"detail": "Invalid workspace request"})
    );
    assert_eq!(missing.calls(), 1);

    let unavailable = Arc::new(FakeAgentRegistry::new(RegistryMode::Unavailable));
    let unavailable_response = send(
        state(db.clone(), unavailable.clone())?,
        agent_request(
            "POST",
            None,
            "owner-1",
            Some(json!({"agent_id": "agent-1", "hex_q": 2, "hex_r": -1})),
            Some("unavailable-registry"),
            Some("1"),
        )?,
    )
    .await?;
    assert_eq!(
        unavailable_response.status(),
        StatusCode::SERVICE_UNAVAILABLE
    );
    assert_eq!(
        response_json(unavailable_response).await?,
        json!({"detail": "Workspace Core is unavailable"})
    );
    assert_eq!(unavailable.calls(), 1);

    db.execute(DbStatement::new(
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('viewer-member', 'tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer-1', 'viewer')",
    ))
    .await?;
    let available = Arc::new(FakeAgentRegistry::new(RegistryMode::Available));
    let available_state = state(db.clone(), available.clone())?;
    let viewer_response = send(
        available_state.clone(),
        agent_request(
            "POST",
            None,
            "viewer-1",
            Some(json!({"agent_id": "agent-1", "hex_q": 2, "hex_r": -1})),
            Some("viewer-bind"),
            Some("1"),
        )?,
    )
    .await?;
    assert_eq!(viewer_response.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        response_json(viewer_response).await?,
        json!({"detail": "Access denied"})
    );
    assert_eq!(available.calls(), 0);

    let bound = send(
        available_state.clone(),
        agent_request(
            "POST",
            None,
            "owner-1",
            Some(json!({"agent_id": "agent-1", "hex_q": 2, "hex_r": -1})),
            Some("valid-bind"),
            Some("1"),
        )?,
    )
    .await?;
    assert_eq!(bound.status(), StatusCode::CREATED);
    let bound = response_json(bound).await?;
    let binding_id = bound["id"].as_str().ok_or("missing binding id")?;

    let stale = send(
        available_state,
        agent_request(
            "PATCH",
            Some(binding_id),
            "owner-1",
            Some(json!({"display_name": "Stale update"})),
            Some("stale-update"),
            Some("1"),
        )?,
    )
    .await?;
    assert_eq!(stale.status(), StatusCode::CONFLICT);
    assert_eq!(
        response_json(stale).await?,
        json!({"detail": "Workspace authority revision conflict"})
    );
    assert_eq!(workspace_revision(db.as_ref()).await?, 2);
    assert_eq!(
        table_count(db.as_ref(), "workspace_agent_bindings").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "bcs_bots").await?, 1);
    assert_eq!(bot_participant_count(db.as_ref()).await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 2);
    Ok(())
}

fn state(
    db: Arc<dyn DbPlugin>,
    registry: Arc<dyn AgentRegistryPort>,
) -> Result<Arc<WorkspaceCoreState>, Box<dyn Error>> {
    Ok(Arc::new(WorkspaceCoreState::new_with_dependencies(
        db,
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        registry,
    )?))
}

async fn create_workspace(state: Arc<WorkspaceCoreState>) -> Result<(), Box<dyn Error>> {
    let request = Request::builder()
        .method("POST")
        .uri("/internal/v1/tenants/tenant-1/projects/project-1/workspaces")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .header("x-idempotency-key", "agent-http-workspace-create")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "workspace_id": "workspace-1",
                "group_id": "group-workspace-1",
                "owner_member_id": "member-1",
                "name": "Team Space",
                "description": "Shared workspace",
                "metadata": {"workspace_type": "general"}
            })
            .to_string(),
        ))?;
    let response = send(state, request).await?;
    assert_eq!(response.status(), StatusCode::CREATED);
    Ok(())
}

fn agent_request(
    method: &str,
    binding_id: Option<&str>,
    user_id: &str,
    payload: Option<Value>,
    idempotency_key: Option<&str>,
    if_match: Option<&str>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let suffix = binding_id.map_or_else(String::new, |value| format!("/{value}"));
    let mut builder = Request::builder()
        .method(method)
        .uri(format!(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agents{suffix}"
        ))
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", user_id)
        .header("x-memstack-user-is-superuser", "false");
    if let Some(idempotency_key) = idempotency_key {
        builder = builder.header("idempotency-key", idempotency_key);
    }
    if let Some(if_match) = if_match {
        builder = builder.header("if-match", if_match);
    }
    let body = if let Some(payload) = payload {
        builder = builder.header(header::CONTENT_TYPE, "application/json");
        Body::from(payload.to_string())
    } else {
        Body::empty()
    };
    Ok(builder.body(body)?)
}

async fn send(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
) -> Result<Response<Body>, Box<dyn Error>> {
    Ok(workspace_router(state).oneshot(request).await?)
}

async fn response_json(response: Response<Body>) -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX).await?,
    )?)
}

fn assert_agent_response_shape(response: &Value) -> Result<(), Box<dyn Error>> {
    let actual = response
        .as_object()
        .ok_or("Agent response must be a JSON object")?
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let expected = [
        "agent_id",
        "config",
        "created_at",
        "description",
        "display_name",
        "hex_q",
        "hex_r",
        "id",
        "is_active",
        "label",
        "status",
        "theme_color",
        "updated_at",
        "workspace_id",
    ]
    .into_iter()
    .collect::<BTreeSet<_>>();
    assert_eq!(actual, expected);
    assert!(response["created_at"].as_str().is_some());
    assert!(response["updated_at"].as_str().is_some());
    Ok(())
}

async fn agent_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE bcs_groups (group_id TEXT NOT NULL, label TEXT, status TEXT NOT NULL, driver_bot TEXT NOT NULL, originator TEXT, env TEXT NOT NULL, routing_policy_json TEXT, context TEXT, group_kind TEXT NOT NULL DEFAULT 'normal', version INTEGER NOT NULL DEFAULT 1, record_status TEXT NOT NULL DEFAULT 'active', lifecycle_status TEXT NOT NULL DEFAULT 'active', group_strategy TEXT NOT NULL DEFAULT 'chat', created_by TEXT, visibility TEXT NOT NULL DEFAULT 'private', gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(group_id, env))",
        "CREATE TABLE bcs_group_participants (group_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, role TEXT NOT NULL, env TEXT NOT NULL, actor_kind TEXT NOT NULL DEFAULT 'bot', mode TEXT NOT NULL DEFAULT 'auto', gmt_create TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(env, group_id, bot_uuid))",
        "CREATE TABLE bcs_bots (bot_uuid TEXT NOT NULL, name TEXT NOT NULL, bot_info TEXT, registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, env TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'public', created_by TEXT, actor_kind TEXT NOT NULL DEFAULT 'bot', status TEXT NOT NULL DEFAULT 'online', is_deleted INTEGER NOT NULL DEFAULT 0, agent_code TEXT, gmt_create TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(bot_uuid, env))",
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, is_archived INTEGER NOT NULL DEFAULT 0, office_status TEXT NOT NULL DEFAULT 'inactive', hex_layout_config_json TEXT NOT NULL DEFAULT '{}', default_blocking_categories_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT, deleted_by TEXT, UNIQUE(tenant_id, project_id, workspace_id), UNIQUE(tenant_id, project_id, name))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, invited_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(workspace_id, user_id), UNIQUE(workspace_id, participant_actor_id))",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, participant_actor_id TEXT NOT NULL, display_name TEXT, description TEXT, config_json TEXT NOT NULL DEFAULT '{}', is_active INTEGER NOT NULL DEFAULT 1, hex_q INTEGER, hex_r INTEGER, theme_color TEXT, label TEXT, status TEXT NOT NULL DEFAULT 'idle', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(workspace_id, agent_id), UNIQUE(workspace_id, bot_uuid), UNIQUE(workspace_id, participant_actor_id), UNIQUE(workspace_id, hex_q, hex_r))",
        "CREATE TABLE workspace_topology_nodes (node_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, hex_q INTEGER, hex_r INTEGER)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, is_active) VALUES ('tenant-1', 'project-1', 'owner-1', 'owner-1', 1)",
    ))
    .await?;
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "bcs_bots" => "SELECT COUNT(*) AS value FROM bcs_bots",
        "workspace_agent_bindings" => "SELECT COUNT(*) AS value FROM workspace_agent_bindings",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    scalar_i64(db, sql).await
}

async fn bot_participant_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    scalar_i64(
        db,
        "SELECT COUNT(*) AS value FROM bcs_group_participants WHERE actor_kind = 'bot'",
    )
    .await
}

async fn workspace_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    scalar_i64(
        db,
        "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
    )
    .await
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn outbox_payload(db: &dyn DbPlugin, event_sequence: i64) -> Result<Value, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT payload_json FROM workspace_outbox WHERE event_sequence = ?",
            vec![event_sequence.into()],
        ))
        .await?;
    let payload = rows
        .first()
        .ok_or("missing outbox row")?
        .get_string("payload_json")?
        .ok_or("missing outbox payload")?;
    Ok(serde_json::from_str(&payload)?)
}
