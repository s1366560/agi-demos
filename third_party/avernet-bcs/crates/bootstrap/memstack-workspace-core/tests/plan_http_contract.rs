use std::error::Error;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use axum::body::{Body, to_bytes};
use axum::http::{Request, Response, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service_api::{
    WorkspacePlanJudgePort, WorkspacePlanJudgePortError, WorkspacePlanJudgment,
    WorkspacePlanJudgmentRequest,
};
use serde_json::{Value, json};
use tower::ServiceExt;

#[path = "../src/plan_http_models.rs"]
mod plan_http_models;
#[path = "../src/plans.rs"]
mod plans;
#[path = "../src/workspace_scope.rs"]
mod workspace_scope;

use plans::{PlanHttpState, plan_routes};

struct WorkspaceCoreState {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
}

impl WorkspaceCoreState {
    fn new_with_sql_flavor(
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
        Ok(Self { db, sql_flavor })
    }
}

const SERVICE_TOKEN: &str = "plan-http-contract-token";
const PLAN_PATH: &str = "/api/v1/workspaces/workspace-1/plan";

struct TestJudge {
    calls: AtomicUsize,
    unavailable: bool,
}

impl TestJudge {
    const fn proceeding() -> Self {
        Self {
            calls: AtomicUsize::new(0),
            unavailable: false,
        }
    }

    const fn unavailable() -> Self {
        Self {
            calls: AtomicUsize::new(0),
            unavailable: true,
        }
    }
}

#[async_trait]
impl WorkspacePlanJudgePort for TestJudge {
    async fn judge(
        &self,
        request: &WorkspacePlanJudgmentRequest,
    ) -> Result<WorkspacePlanJudgment, WorkspacePlanJudgePortError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if self.unavailable {
            return Err(WorkspacePlanJudgePortError::Unavailable);
        }
        WorkspacePlanJudgment::new(
            request,
            true,
            request
                .kind()
                .requires_selected_node()
                .then(|| request.candidate_node_ids().first().cloned())
                .flatten(),
            "structured HTTP contract verdict".to_string(),
            "plan-http-judge".to_string(),
            "judge_workspace_plan".to_string(),
            request.evidence().clone(),
            json!({"proceed": true}),
            3,
        )
        .map_err(|_| WorkspacePlanJudgePortError::Unavailable)
    }
}

#[tokio::test]
async fn all_eleven_plan_routes_preserve_success_contracts() -> Result<(), Box<dyn Error>> {
    let cases = [
        ("GET", PLAN_PATH, "pending", None),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/recover-stale-attempts",
            "running",
            Some(json!({})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/outbox/failed-outbox/retry",
            "pending",
            Some(json!({})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/iteration/pause",
            "pending",
            Some(json!({})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/iteration/resume",
            "pending",
            Some(json!({})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/iteration/trigger-next",
            "pending",
            Some(json!({})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/delivery/run-pipeline",
            "pending",
            Some(json!({"node_id": "node-1"})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/delivery/regenerate-contract",
            "pending",
            Some(json!({})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/nodes/node-1/request-replan",
            "pending",
            Some(json!({})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/nodes/node-1/reopen",
            "blocked",
            Some(json!({})),
        ),
        (
            "POST",
            "/api/v1/workspaces/workspace-1/plan/nodes/node-1/accept-review",
            "pending",
            Some(json!({})),
        ),
    ];

    for (index, (method, uri, node_status, body)) in cases.into_iter().enumerate() {
        let (db, judge, state) = fixture(node_status, true, false).await?;
        let response = send(
            state,
            proxy_request(
                method,
                uri,
                "user-owner",
                body.as_ref(),
                Some(&format!("route-{index}")),
                None,
            )?,
        )
        .await?;
        assert_eq!(response.status(), StatusCode::OK, "{method} {uri}");
        let payload = response_json(response).await?;
        if method == "GET" {
            assert_eq!(payload["workspace_id"], "workspace-1");
            assert_eq!(payload["plan"]["id"], "plan-1");
        } else {
            assert_eq!(payload["ok"], true);
            assert_eq!(payload["plan_id"], "plan-1");
        }
        drop((db, judge));
    }
    Ok(())
}

#[tokio::test]
async fn authentication_scope_validation_and_missing_plan_fail_closed() -> Result<(), Box<dyn Error>>
{
    let (_db, _judge, state) = fixture("pending", true, false).await?;
    let unauthorized = Request::builder().uri(PLAN_PATH).body(Body::empty())?;
    assert_eq!(
        send(state.clone(), unauthorized).await?.status(),
        StatusCode::UNAUTHORIZED
    );

    let invalid_query = proxy_request(
        "GET",
        &format!("{PLAN_PATH}?event_limit=201"),
        "user-owner",
        None,
        None,
        None,
    )?;
    let response = send(state.clone(), invalid_query).await?;
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(response).await?["detail"][0]["loc"],
        json!(["query", "event_limit"])
    );

    let invalid_body = proxy_request(
        "POST",
        "/api/v1/workspaces/workspace-1/plan/iteration/pause",
        "user-owner",
        Some(&json!({"unknown": true})),
        None,
        None,
    )?;
    assert_eq!(
        send(state.clone(), invalid_body).await?.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );

    let outsider = proxy_request("GET", PLAN_PATH, "outsider", None, None, None)?;
    assert_eq!(send(state, outsider).await?.status(), StatusCode::FORBIDDEN);

    let (_db, _judge, missing_state) = fixture("pending", false, false).await?;
    let missing = proxy_request("GET", PLAN_PATH, "user-owner", None, None, None)?;
    assert_eq!(
        send(missing_state, missing).await?.status(),
        StatusCode::NOT_FOUND
    );
    Ok(())
}

#[tokio::test]
async fn viewer_is_rejected_before_judge_and_stale_revision_conflicts() -> Result<(), Box<dyn Error>>
{
    let (_db, judge, state) = fixture("pending", true, false).await?;
    let viewer = proxy_request(
        "POST",
        "/api/v1/workspaces/workspace-1/plan/delivery/regenerate-contract",
        "user-viewer",
        Some(&json!({})),
        Some("viewer-regenerate"),
        None,
    )?;
    assert_eq!(
        send(state.clone(), viewer).await?.status(),
        StatusCode::FORBIDDEN
    );
    assert_eq!(judge.calls.load(Ordering::SeqCst), 0);

    let stale = proxy_request(
        "POST",
        "/api/v1/workspaces/workspace-1/plan/iteration/pause",
        "user-owner",
        Some(&json!({})),
        Some("stale-pause"),
        Some("W/\"0\""),
    )?;
    assert_eq!(send(state, stale).await?.status(), StatusCode::CONFLICT);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn idempotency_replays_once_and_rejects_same_key_with_new_payload()
-> Result<(), Box<dyn Error>> {
    let (db, judge, state) = fixture("pending", true, false).await?;
    let uri = "/api/v1/workspaces/workspace-1/plan/iteration/pause";
    let first_request = proxy_request(
        "POST",
        uri,
        "user-owner",
        Some(&json!({"reason": "pause now"})),
        Some("pause-once"),
        Some("\"1\""),
    )?;
    let first = response_json(send(state.clone(), first_request).await?).await?;
    let replay_request = proxy_request(
        "POST",
        uri,
        "user-owner",
        Some(&json!({"reason": "pause now"})),
        Some("pause-once"),
        Some("\"1\""),
    )?;
    let replay = response_json(send(state.clone(), replay_request).await?).await?;
    assert_eq!(replay, first);
    assert_eq!(table_count(db.as_ref(), "workspace_plan_events").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 2);

    let conflict_request = proxy_request(
        "POST",
        uri,
        "user-owner",
        Some(&json!({"reason": "different request"})),
        Some("pause-once"),
        Some("\"1\""),
    )?;
    assert_eq!(
        send(state, conflict_request).await?.status(),
        StatusCode::CONFLICT
    );
    assert_eq!(judge.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn judge_failure_writes_only_failed_audit_and_pipeline_selection_is_structured()
-> Result<(), Box<dyn Error>> {
    let (db, judge, state) = fixture("pending", true, true).await?;
    let unavailable = proxy_request(
        "POST",
        "/api/v1/workspaces/workspace-1/plan/nodes/node-1/request-replan",
        "user-owner",
        Some(&json!({"reason": "judge this"})),
        Some("judge-failure"),
        None,
    )?;
    assert_eq!(
        send(state, unavailable).await?.status(),
        StatusCode::SERVICE_UNAVAILABLE
    );
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        scalar_i64(db.as_ref(), "SELECT revision AS value FROM workspace_plans").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_plan_events").await?, 0);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_judge_audits").await?, 1);

    let (_db, selecting_judge, selecting_state) = fixture("pending", true, false).await?;
    let selected = proxy_request(
        "POST",
        "/api/v1/workspaces/workspace-1/plan/delivery/run-pipeline",
        "user-owner",
        Some(&json!({})),
        Some("select-pipeline"),
        None,
    )?;
    let response = send(selecting_state, selected).await?;
    assert_eq!(response.status(), StatusCode::OK);
    let payload = response_json(response).await?;
    assert_eq!(payload["node_id"], "node-1");
    assert!(
        payload["outbox_id"]
            .as_str()
            .is_some_and(|value| value.starts_with("outbox-"))
    );
    assert_eq!(selecting_judge.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn explicit_pipeline_and_structural_actions_do_not_call_judge() -> Result<(), Box<dyn Error>>
{
    for (uri, node_status, body) in [
        (
            "/api/v1/workspaces/workspace-1/plan/delivery/run-pipeline",
            "pending",
            json!({"node_id": "node-1"}),
        ),
        (
            "/api/v1/workspaces/workspace-1/plan/iteration/pause",
            "pending",
            json!({}),
        ),
        (
            "/api/v1/workspaces/workspace-1/plan/nodes/node-1/reopen",
            "blocked",
            json!({}),
        ),
        (
            "/api/v1/workspaces/workspace-1/plan/outbox/failed-outbox/retry",
            "pending",
            json!({}),
        ),
    ] {
        let (_db, judge, state) = fixture(node_status, true, false).await?;
        let request = proxy_request("POST", uri, "user-owner", Some(&body), Some(uri), None)?;
        assert_eq!(
            send(state, request).await?.status(),
            StatusCode::OK,
            "{uri}"
        );
        assert_eq!(judge.calls.load(Ordering::SeqCst), 0, "{uri}");
    }
    Ok(())
}

#[tokio::test]
async fn snapshot_recovery_is_judged_then_returns_replayed_terminal_projection()
-> Result<(), Box<dyn Error>> {
    let (db, judge, state) = fixture("running", true, false).await?;
    let request = proxy_request(
        "GET",
        &format!("{PLAN_PATH}?recover_stale_attempts=true"),
        "user-owner",
        None,
        Some("snapshot-recovery"),
        None,
    )?;
    let response = send(state, request).await?;
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response_json(response).await?["plan"]["nodes"][0]["execution"],
        "pending"
    );
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(table_count(db.as_ref(), "workspace_plan_events").await?, 1);
    Ok(())
}

async fn fixture(
    node_status: &str,
    include_plan: bool,
    judge_unavailable: bool,
) -> Result<(Arc<LocalSqliteDbPlugin>, Arc<TestJudge>, Arc<PlanHttpState>), Box<dyn Error>> {
    let db = Arc::new(seeded_db(node_status, include_plan).await?);
    let judge = Arc::new(if judge_unavailable {
        TestJudge::unavailable()
    } else {
        TestJudge::proceeding()
    });
    let state = Arc::new(PlanHttpState::new(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        judge.clone(),
    )?);
    Ok((db, judge, state))
}

fn proxy_request(
    method: &str,
    uri: &str,
    user_id: &str,
    payload: Option<&Value>,
    idempotency_key: Option<&str>,
    if_match: Option<&str>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-workspace-id", "workspace-1")
        .header("x-memstack-user-id", user_id)
        .header("x-memstack-user-is-superuser", "false");
    if let Some(key) = idempotency_key {
        builder = builder.header("idempotency-key", key);
    }
    if let Some(revision) = if_match {
        builder = builder.header(header::IF_MATCH, revision);
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
    state: Arc<PlanHttpState>,
    request: Request<Body>,
) -> Result<Response<Body>, Box<dyn Error>> {
    Ok(plan_routes(state).oneshot(request).await?)
}

async fn response_json(response: Response<Body>) -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX).await?,
    )?)
}

async fn seeded_db(
    node_status: &str,
    include_plan: bool,
) -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_plans (plan_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, source_task_id TEXT, goal TEXT NOT NULL, goal_json TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_plan_nodes (node_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, workspace_task_id TEXT, parent_id TEXT, kind TEXT NOT NULL, title TEXT NOT NULL, description TEXT, intent TEXT, status TEXT NOT NULL, sequence_number INTEGER NOT NULL, dependencies_json TEXT NOT NULL, acceptance_criteria_json TEXT NOT NULL, feature_checkpoint_json TEXT, handoff_package_json TEXT, recommended_capabilities_json TEXT NOT NULL, priority INTEGER NOT NULL, progress_json TEXT NOT NULL, assignee_agent_id TEXT, current_attempt_id TEXT, timeout_deadline_at TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_plan_blackboard_entries (entry_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, created_by_actor_id TEXT, version INTEGER NOT NULL, schema_ref TEXT, metadata_json TEXT NOT NULL)",
        "CREATE TABLE workspace_plan_events (event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, event_sequence INTEGER NOT NULL, node_id TEXT, attempt_id TEXT, event_type TEXT NOT NULL, source TEXT NOT NULL, actor_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(plan_id, event_sequence))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 10, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, next_attempt_at TEXT, dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_pipeline_runs (run_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT, provider TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, node_id TEXT, attempt_id TEXT, commit_ref TEXT, metadata_json TEXT NOT NULL, started_at TEXT, completed_at TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE workspace_judge_audits (audit_id TEXT PRIMARY KEY, tenant_id TEXT, project_id TEXT, workspace_id TEXT, plan_id TEXT, plan_node_id TEXT, judgment_type TEXT NOT NULL, agent_id TEXT NOT NULL, tool_name TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL, rationale TEXT NOT NULL, latency_ms INTEGER NOT NULL, status TEXT NOT NULL, error_detail TEXT, created_at TEXT NOT NULL)",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    for statement in [
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id) VALUES ('workspace-1', 'tenant-1', 'project-1')".to_string(),
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, role) VALUES ('owner', 'tenant-1', 'project-1', 'workspace-1', 'user-owner', 'owner')".to_string(),
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, role) VALUES ('viewer', 'tenant-1', 'project-1', 'workspace-1', 'user-viewer', 'viewer')".to_string(),
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    if include_plan {
        for statement in [
            "INSERT INTO workspace_plans (plan_id, tenant_id, project_id, workspace_id, goal, goal_json, status, revision, metadata_json, created_at, updated_at) VALUES ('plan-1', 'tenant-1', 'project-1', 'workspace-1', 'Ship migration', '{\"id\":\"node-1\"}', 'active', 1, '{\"iteration_loop\":{\"loop_status\":\"active\"}}', '2026-08-11T00:00:00Z', '2026-08-11T00:00:00Z')".to_string(),
            format!("INSERT INTO workspace_plan_nodes (node_id, tenant_id, project_id, workspace_id, plan_id, kind, title, description, intent, status, sequence_number, dependencies_json, acceptance_criteria_json, recommended_capabilities_json, priority, progress_json, timeout_deadline_at, metadata_json, created_at, updated_at) VALUES ('node-1', 'tenant-1', 'project-1', 'workspace-1', 'plan-1', 'task', 'Ship migration', 'Root task', 'todo', '{node_status}', 0, '[]', '[]', '[]', 0, '{{\"percent\":0}}', {}, '{{}}', '2026-08-11T00:00:00Z', '2026-08-11T00:00:00Z')", if node_status == "running" { "'2000-01-01T00:00:00Z'" } else { "NULL" }),
            "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, idempotency_key, status, attempt_count, max_attempts, created_at, updated_at) VALUES ('failed-outbox', 'tenant-1', 'project-1', 'workspace-1', 'workspace_plan', 'plan-1', 'old_event', 'workspace.events', 0, '{}', '{}', 'old-outbox', 'failed', 2, 10, '2026-08-11T00:00:00Z', '2026-08-11T00:00:00Z')".to_string(),
        ] {
            db.execute(DbStatement::new(statement)).await?;
        }
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::new(format!(
            "SELECT COUNT(*) AS value FROM {table}"
        )))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}
