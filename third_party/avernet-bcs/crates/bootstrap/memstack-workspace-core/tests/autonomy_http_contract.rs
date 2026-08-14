use std::error::Error;
use std::sync::Arc;

use async_trait::async_trait;
use axum::body::{Body, to_bytes};
use axum::http::{Method, Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use memstack_workspace_service::{
    PublicWorkspaceAutonomyJudgePort, PublicWorkspaceAutonomyJudgePortError,
    PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgmentRequest,
    PublicWorkspaceAutonomyNextAction, PublicWorkspaceAutonomyVerdictKind,
};
use memstack_workspace_service_api::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, ProviderRegistryRoute,
    TenantId, WorkspaceContextJudgePort, WorkspaceContextJudgePortError, WorkspaceContextJudgment,
    WorkspaceContextJudgmentRequest,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "autonomy-http-contract-token";
const PATH: &str = "/api/v1/workspaces/workspace-1/autonomy/tick";
const ATTENTIONS_PATH: &str = "/api/v1/workspaces/workspace-1/autonomy/attentions";

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

struct UnusedContextJudge;

#[async_trait]
impl WorkspaceContextJudgePort for UnusedContextJudge {
    async fn select(
        &self,
        _request: &WorkspaceContextJudgmentRequest,
    ) -> Result<WorkspaceContextJudgment, WorkspaceContextJudgePortError> {
        Err(WorkspaceContextJudgePortError::Unavailable)
    }
}

struct FirstCandidateAutonomyJudge;

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for FirstCandidateAutonomyJudge {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        let root_task_id = request
            .candidates()
            .first()
            .map(|candidate| candidate.root_task_id.clone())
            .ok_or(PublicWorkspaceAutonomyJudgePortError::Unavailable)?;
        let workspace_agent_binding_id = request
            .agent_candidates()
            .first()
            .map(|candidate| candidate.workspace_agent_binding_id.clone())
            .ok_or(PublicWorkspaceAutonomyJudgePortError::Unavailable)?;
        PublicWorkspaceAutonomyJudgment::new(
            request,
            PublicWorkspaceAutonomyVerdictKind::Continue,
            Some(root_task_id.clone()),
            Some(PublicWorkspaceAutonomyNextAction {
                title: "Implement the next verified slice".to_string(),
                description: "Advance the selected root goal with concrete runtime evidence"
                    .to_string(),
                workspace_agent_binding_id: workspace_agent_binding_id.clone(),
            }),
            "the structured root candidate is ready".to_string(),
            "autonomy-judge-agent".to_string(),
            "judge_workspace_autonomy".to_string(),
            json!({"candidate_ids": [root_task_id.clone()]}),
            json!({
                "verdict": "continue",
                "selected_root_task_id": root_task_id,
                "next_action": {
                    "title": "Implement the next verified slice",
                    "description": "Advance the selected root goal with concrete runtime evidence",
                    "workspace_agent_binding_id": workspace_agent_binding_id,
                }
            }),
            7,
        )
        .map_err(|_| PublicWorkspaceAutonomyJudgePortError::Unavailable)
    }
}

#[tokio::test]
async fn autonomy_tick_uses_structured_judge_and_replays_durable_terminal_response()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_all_authorities(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(UnusedAgentRegistry),
        Arc::new(UnusedProviderRegistry),
        Arc::new(UnusedContextJudge),
        Arc::new(FirstCandidateAutonomyJudge),
    )?);

    let first = send(
        state.clone(),
        Some(json!({"force": true})),
        Some(0),
        "tick-http-1",
    )
    .await?;
    assert_eq!(first.0, StatusCode::OK);
    assert_eq!(
        first.1,
        json!({"triggered": true, "root_task_id": "root-task-1", "reason": "triggered"})
    );
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_autonomy_ticks").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_judge_audits").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_autonomy_progression_outbox").await?,
        1
    );
    let progression = db
        .query(DbStatement::new(
            "SELECT root_task_id, task_title, task_description, \
                    workspace_agent_binding_id, status \
             FROM workspace_autonomy_progression_outbox",
        ))
        .await?;
    assert_eq!(progression.len(), 1);
    assert_eq!(
        progression[0].get_string("root_task_id")?.as_deref(),
        Some("root-task-1")
    );
    assert_eq!(
        progression[0].get_string("task_title")?.as_deref(),
        Some("Implement the next verified slice")
    );
    assert_eq!(
        progression[0].get_string("task_description")?.as_deref(),
        Some("Advance the selected root goal with concrete runtime evidence")
    );
    assert_eq!(
        progression[0]
            .get_string("workspace_agent_binding_id")?
            .as_deref(),
        Some("binding-1")
    );
    assert_eq!(
        progression[0].get_string("status")?.as_deref(),
        Some("pending")
    );

    let replay = send(state, Some(json!({"force": true})), Some(0), "tick-http-1").await?;
    assert_eq!(replay, first);
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_judge_audits").await?, 1);
    Ok(())
}

#[tokio::test]
async fn autonomy_tick_without_if_match_replays_before_resolving_changed_revision()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_all_authorities(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(UnusedAgentRegistry),
        Arc::new(UnusedProviderRegistry),
        Arc::new(UnusedContextJudge),
        Arc::new(FirstCandidateAutonomyJudge),
    )?);

    let first = send(
        state.clone(),
        Some(json!({"force": true})),
        None,
        "tick-http-without-if-match",
    )
    .await?;
    assert_eq!(first.0, StatusCode::OK);

    let replay = send(
        state,
        Some(json!({"force": true})),
        None,
        "tick-http-without-if-match",
    )
    .await?;
    assert_eq!(replay, first);
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_judge_audits").await?, 1);
    Ok(())
}

#[tokio::test]
async fn autonomy_attention_routes_enforce_membership_editor_retry_and_exact_resolution()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    seed_attention_state(db.as_ref()).await?;
    let state = Arc::new(WorkspaceCoreState::new_with_all_authorities(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(UnusedAgentRegistry),
        Arc::new(UnusedProviderRegistry),
        Arc::new(UnusedContextJudge),
        Arc::new(FirstCandidateAutonomyJudge),
    )?);

    let member_list =
        send_attention_request(state.clone(), Method::GET, "viewer-1", ATTENTIONS_PATH).await?;
    assert_eq!(member_list.0, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&member_list.1)?,
        json!([
            {
                "attention_id": "attention-dispatch-1",
                "root_task_id": "root-task-1",
                "source_kind": "task_dispatch_dead_letter",
                "source_id": "dispatch-1",
                "reason": "delivery retries exhausted",
                "status": "open",
                "created_at_ms": 10
            },
            {
                "attention_id": "attention-judge-1",
                "root_task_id": "root-task-1",
                "source_kind": "judge_block",
                "source_id": "audit-1",
                "reason": "editor decision required",
                "status": "open",
                "created_at_ms": 11
            }
        ])
    );

    let outsider =
        send_attention_request(state.clone(), Method::GET, "outsider-1", ATTENTIONS_PATH).await?;
    assert_eq!(outsider.0, StatusCode::FORBIDDEN);

    let dispatch_retry_path = format!("{ATTENTIONS_PATH}/attention-dispatch-1/retry");
    let viewer_retry = send_attention_request(
        state.clone(),
        Method::POST,
        "viewer-1",
        dispatch_retry_path.as_str(),
    )
    .await?;
    assert_eq!(viewer_retry.0, StatusCode::FORBIDDEN);

    let dispatch_resolve_path = format!("{ATTENTIONS_PATH}/attention-dispatch-1/resolve");
    let missing_revision = send_attention_mutation_request(
        state.clone(),
        "user-1",
        dispatch_resolve_path.as_str(),
        None,
        Some("dispatch-resolve-key"),
    )
    .await?;
    assert_eq!(missing_revision.0, StatusCode::BAD_REQUEST);
    let missing_idempotency = send_attention_mutation_request(
        state.clone(),
        "user-1",
        dispatch_resolve_path.as_str(),
        Some(0),
        None,
    )
    .await?;
    assert_eq!(missing_idempotency.0, StatusCode::BAD_REQUEST);
    let viewer_resolve = send_attention_mutation_request(
        state.clone(),
        "viewer-1",
        dispatch_resolve_path.as_str(),
        Some(0),
        Some("viewer-dispatch-resolve-key"),
    )
    .await?;
    assert_eq!(viewer_resolve.0, StatusCode::FORBIDDEN);
    let wrong_source_resolve = send_attention_mutation_request(
        state.clone(),
        "user-1",
        dispatch_resolve_path.as_str(),
        Some(0),
        Some("dispatch-resolve-key"),
    )
    .await?;
    assert_eq!(wrong_source_resolve.0, StatusCode::CONFLICT);
    assert_eq!(authority_revision(db.as_ref()).await?, 0);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        0
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 0);

    let owner_retry = send_attention_request(
        state.clone(),
        Method::POST,
        "user-1",
        dispatch_retry_path.as_str(),
    )
    .await?;
    assert_eq!(owner_retry.0, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&owner_retry.1)?,
        json!({
            "attention_id": "attention-dispatch-1",
            "status": "retry_queued"
        })
    );

    let dispatch = db
        .query(DbStatement::new(
            "SELECT dispatch_id, delivery_request_id, task_title, status, attempt_count, \
                    next_attempt_at_ms, lease_owner, lease_expires_at_ms, lease_generation, \
                    last_error, delivered_at_ms FROM workspace_task_dispatch_outbox \
             WHERE dispatch_id = 'dispatch-1'",
        ))
        .await?;
    assert_eq!(dispatch.len(), 1);
    assert_eq!(
        dispatch[0].get_string("dispatch_id")?.as_deref(),
        Some("dispatch-1")
    );
    assert_eq!(
        dispatch[0].get_string("delivery_request_id")?.as_deref(),
        Some("delivery-1")
    );
    assert_eq!(
        dispatch[0].get_string("task_title")?.as_deref(),
        Some("Preserve immutable dispatch snapshot")
    );
    assert_eq!(
        dispatch[0].get_string("status")?.as_deref(),
        Some("pending")
    );
    assert_eq!(dispatch[0].get_i64("attempt_count")?, Some(0));
    assert!(
        dispatch[0]
            .get_i64("next_attempt_at_ms")?
            .is_some_and(|value| value > 0)
    );
    assert_eq!(dispatch[0].get_string("lease_owner")?, None);
    assert_eq!(dispatch[0].get_i64("lease_expires_at_ms")?, None);
    assert_eq!(dispatch[0].get_i64("lease_generation")?, Some(7));
    assert_eq!(dispatch[0].get_string("last_error")?, None);
    assert_eq!(dispatch[0].get_i64("delivered_at_ms")?, None);

    let resolved = db
        .query(DbStatement::new(
            "SELECT status, resolved_by_actor_id, resolved_at_ms \
             FROM workspace_autonomy_attentions \
             WHERE attention_id = 'attention-dispatch-1'",
        ))
        .await?;
    assert_eq!(resolved.len(), 1);
    assert_eq!(
        resolved[0].get_string("status")?.as_deref(),
        Some("resolved")
    );
    assert_eq!(
        resolved[0].get_string("resolved_by_actor_id")?.as_deref(),
        Some("user-1")
    );
    assert!(
        resolved[0]
            .get_i64("resolved_at_ms")?
            .is_some_and(|value| value > 0)
    );

    let duplicate_retry = send_attention_request(
        state.clone(),
        Method::POST,
        "user-1",
        dispatch_retry_path.as_str(),
    )
    .await?;
    assert_eq!(duplicate_retry.0, StatusCode::CONFLICT);

    let judge_retry = send_attention_request(
        state.clone(),
        Method::POST,
        "user-1",
        format!("{ATTENTIONS_PATH}/attention-judge-1/retry").as_str(),
    )
    .await?;
    assert_eq!(judge_retry.0, StatusCode::CONFLICT);

    let judge_resolve_path = format!("{ATTENTIONS_PATH}/attention-judge-1/resolve");
    let resolved_judge = send_attention_mutation_request(
        state.clone(),
        "user-1",
        judge_resolve_path.as_str(),
        Some(0),
        Some("judge-resolve-key-1"),
    )
    .await?;
    assert_eq!(resolved_judge.0, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&resolved_judge.1)?,
        json!({
            "attention_id": "attention-judge-1",
            "status": "resolved",
            "committed_revision": 1,
            "replayed": false
        })
    );
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);
    let resolved_judge_row = db
        .query(DbStatement::new(
            "SELECT status, resolved_by_actor_id, resolved_at_ms \
             FROM workspace_autonomy_attentions WHERE attention_id = 'attention-judge-1'",
        ))
        .await?;
    assert_eq!(resolved_judge_row.len(), 1);
    assert_eq!(
        resolved_judge_row[0].get_string("status")?.as_deref(),
        Some("resolved")
    );
    assert_eq!(
        resolved_judge_row[0]
            .get_string("resolved_by_actor_id")?
            .as_deref(),
        Some("user-1")
    );
    assert!(
        resolved_judge_row[0]
            .get_i64("resolved_at_ms")?
            .is_some_and(|value| value > 0)
    );
    assert_eq!(
        scalar_query(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_tasks root WHERE root.task_id = \
             'root-task-1' AND NOT EXISTS (SELECT 1 FROM workspace_autonomy_attentions attention \
             WHERE attention.tenant_id = root.tenant_id AND attention.project_id = root.project_id \
             AND attention.workspace_id = root.workspace_id AND attention.root_task_id = root.task_id \
             AND attention.status = 'open')"
        )
        .await?,
        1
    );

    let replayed_judge = send_attention_mutation_request(
        state.clone(),
        "user-1",
        judge_resolve_path.as_str(),
        Some(0),
        Some("judge-resolve-key-1"),
    )
    .await?;
    assert_eq!(replayed_judge.0, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&replayed_judge.1)?,
        json!({
            "attention_id": "attention-judge-1",
            "status": "resolved",
            "committed_revision": 1,
            "replayed": true
        })
    );
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);

    for statement in [
        "INSERT INTO workspace_autonomy_attentions \
         (attention_id, tenant_id, project_id, workspace_id, root_task_id, source_kind, source_id, \
          reason, status, created_at_ms) VALUES ('attention-judge-2', 'tenant-1', 'project-1', \
          'workspace-1', 'root-task-1', 'judge_escalate', 'audit-2', 'second editor decision', \
          'open', 12)",
        "INSERT INTO workspace_autonomy_attentions \
         (attention_id, tenant_id, project_id, workspace_id, root_task_id, source_kind, source_id, \
          reason, status, created_at_ms) VALUES ('attention-other-scope', 'tenant-2', 'project-2', \
          'workspace-2', 'root-task-2', 'judge_block', 'audit-other', 'other scope decision', \
          'open', 13)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    let idempotency_conflict = send_attention_mutation_request(
        state.clone(),
        "user-1",
        format!("{ATTENTIONS_PATH}/attention-judge-2/resolve").as_str(),
        Some(1),
        Some("judge-resolve-key-1"),
    )
    .await?;
    assert_eq!(idempotency_conflict.0, StatusCode::CONFLICT);
    let stale_revision = send_attention_mutation_request(
        state.clone(),
        "user-1",
        format!("{ATTENTIONS_PATH}/attention-judge-2/resolve").as_str(),
        Some(0),
        Some("judge-stale-revision-key"),
    )
    .await?;
    assert_eq!(stale_revision.0, StatusCode::CONFLICT);
    let wrong_scope = send_attention_mutation_request(
        state.clone(),
        "user-1",
        format!("{ATTENTIONS_PATH}/attention-other-scope/resolve").as_str(),
        Some(1),
        Some("judge-wrong-scope-key"),
    )
    .await?;
    assert_eq!(wrong_scope.0, StatusCode::CONFLICT);
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);

    db.execute(DbStatement::new(
        "INSERT INTO workspace_autonomy_attentions \
         (attention_id, tenant_id, project_id, workspace_id, root_task_id, source_kind, \
          source_id, reason, status, created_at_ms) VALUES \
         ('attention-invalid-1', 'tenant-1', 'project-1', 'workspace-1', 'root-task-1', \
          'invalid_source', 'invalid-1', 'invalid persisted source', 'open', 12)",
    ))
    .await?;
    let invalid_record =
        send_attention_request(state, Method::GET, "user-1", ATTENTIONS_PATH).await?;
    assert_eq!(invalid_record.0, StatusCode::INTERNAL_SERVER_ERROR);
    Ok(())
}

async fn send(
    state: Arc<WorkspaceCoreState>,
    body: Option<Value>,
    revision: Option<u64>,
    idempotency_key: &str,
) -> Result<(StatusCode, Value), Box<dyn Error>> {
    let mut builder = Request::builder()
        .method("POST")
        .uri(PATH)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "user-1")
        .header("idempotency-key", idempotency_key)
        .header(header::CONTENT_TYPE, "application/json");
    if let Some(revision) = revision {
        builder = builder.header("if-match", revision.to_string());
    }
    let request = builder.body(match body {
        Some(body) => Body::from(serde_json::to_vec(&body)?),
        None => Body::empty(),
    })?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let response_body = to_bytes(response.into_body(), usize::MAX).await?;
    let body = serde_json::from_slice(&response_body).map_err(|error| {
        std::io::Error::other(format!(
            "autonomy response {status} was not JSON: {error}; body={}",
            String::from_utf8_lossy(&response_body)
        ))
    })?;
    Ok((status, body))
}

async fn send_attention_request(
    state: Arc<WorkspaceCoreState>,
    method: Method,
    user_id: &str,
    path: &str,
) -> Result<(StatusCode, Vec<u8>), Box<dyn Error>> {
    let request = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", user_id)
        .body(Body::empty())?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await?.to_vec();
    Ok((status, body))
}

async fn send_attention_mutation_request(
    state: Arc<WorkspaceCoreState>,
    user_id: &str,
    path: &str,
    revision: Option<u64>,
    idempotency_key: Option<&str>,
) -> Result<(StatusCode, Vec<u8>), Box<dyn Error>> {
    let mut builder = Request::builder()
        .method(Method::POST)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", user_id);
    if let Some(revision) = revision {
        builder = builder.header("if-match", revision.to_string());
    }
    if let Some(idempotency_key) = idempotency_key {
        builder = builder.header("idempotency-key", idempotency_key);
    }
    let response = workspace_router(state)
        .oneshot(builder.body(Body::empty())?)
        .await?;
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await?.to_vec();
    Ok((status, body))
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, assignee_user_id TEXT, assignee_agent_id TEXT, status TEXT NOT NULL, priority INTEGER NOT NULL, estimated_effort TEXT, blocker_reason TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, archived_at TEXT)",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, display_name TEXT, description TEXT, config_json TEXT NOT NULL, is_active INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_judge_audits (audit_id TEXT PRIMARY KEY, tenant_id TEXT, project_id TEXT, workspace_id TEXT, plan_id TEXT, plan_node_id TEXT, judgment_type TEXT NOT NULL, agent_id TEXT NOT NULL, tool_name TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL, rationale TEXT NOT NULL, latency_ms INTEGER NOT NULL, status TEXT NOT NULL, error_detail TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE workspace_autonomy_judgment_claims (claim_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, status TEXT NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, lease_generation INTEGER NOT NULL, audit_id TEXT, judgment_json TEXT, error_detail TEXT, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL, judged_at_ms INTEGER, applied_at_ms INTEGER, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_autonomy_ticks (tick_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, root_task_id TEXT, actor_id TEXT NOT NULL, force INTEGER NOT NULL, verdict TEXT NOT NULL, reason TEXT NOT NULL, judge_audit_id TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE workspace_autonomy_progression_outbox (progression_id TEXT PRIMARY KEY, tick_id TEXT NOT NULL UNIQUE, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, root_task_id TEXT NOT NULL, actor_id TEXT NOT NULL, judge_agent_id TEXT NOT NULL, workspace_agent_binding_id TEXT NOT NULL, task_title TEXT NOT NULL, task_description TEXT NOT NULL, status TEXT NOT NULL, attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL, next_attempt_at_ms INTEGER NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, lease_generation INTEGER NOT NULL, execution_task_id TEXT, last_error TEXT, created_at_ms INTEGER NOT NULL, completed_at_ms INTEGER)",
        "CREATE TABLE workspace_autonomy_attentions (attention_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, root_task_id TEXT, source_kind TEXT NOT NULL, source_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, created_at_ms INTEGER NOT NULL, resolved_at_ms INTEGER, resolved_by_actor_id TEXT)",
        "CREATE TABLE workspace_task_dispatch_outbox (dispatch_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, delivery_request_id TEXT NOT NULL, task_title TEXT NOT NULL, status TEXT NOT NULL, attempt_count INTEGER NOT NULL, next_attempt_at_ms INTEGER NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, lease_generation INTEGER NOT NULL, last_error TEXT, delivered_at_ms INTEGER)",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, description, created_by, status, priority, metadata_json, created_at) VALUES ('root-task-1', 'tenant-1', 'project-1', 'workspace-1', 'Root objective', 'Proceed through the structured judge', 'user-1', 'todo', 2, '{\"task_role\":\"goal_root\"}', CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_agent_bindings VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', 'agent-1', 'Delivery Agent', 'Executes verified work', '{}', 1, 'idle', CURRENT_TIMESTAMP)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn seed_attention_state(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for statement in [
        "INSERT INTO workspace_task_dispatch_outbox VALUES ('dispatch-1', 'tenant-1', 'project-1', 'workspace-1', 'delivery-1', 'Preserve immutable dispatch snapshot', 'dead_letter', 5, 1, 'worker-1', 999, 7, 'provider unavailable', 888)",
        "INSERT INTO workspace_autonomy_attentions (attention_id, tenant_id, project_id, workspace_id, root_task_id, source_kind, source_id, reason, status, created_at_ms) VALUES ('attention-dispatch-1', 'tenant-1', 'project-1', 'workspace-1', 'root-task-1', 'task_dispatch_dead_letter', 'dispatch-1', 'delivery retries exhausted', 'open', 10)",
        "INSERT INTO workspace_autonomy_attentions (attention_id, tenant_id, project_id, workspace_id, root_task_id, source_kind, source_id, reason, status, created_at_ms) VALUES ('attention-judge-1', 'tenant-1', 'project-1', 'workspace-1', 'root-task-1', 'judge_block', 'audit-1', 'editor decision required', 'open', 11)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(())
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_autonomy_ticks" => "SELECT COUNT(*) AS value FROM workspace_autonomy_ticks",
        "workspace_judge_audits" => "SELECT COUNT(*) AS value FROM workspace_judge_audits",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        "workspace_autonomy_progression_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_autonomy_progression_outbox"
        }
        _ => return Err("unsupported table".into()),
    };
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing count")?
        .get_i64("value")?
        .ok_or("missing count value")?)
}

async fn scalar_query(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing scalar row")?
        .get_i64("value")?
        .ok_or("missing scalar value")?)
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
        ))
        .await?
        .first()
        .ok_or("missing authority")?
        .get_i64("value")?
        .ok_or("missing revision")?)
}
