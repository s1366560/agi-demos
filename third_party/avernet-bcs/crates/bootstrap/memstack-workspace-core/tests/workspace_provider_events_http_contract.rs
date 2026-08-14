use std::{
    collections::{BTreeMap, HashMap, HashSet},
    sync::Arc,
};

use async_trait::async_trait;
use axum::{
    Router,
    body::{Body, to_bytes},
    http::{Request, Response, StatusCode},
};
use bcs_db_api::{
    DbError, DbExecuteResult, DbHealth, DbPlugin, DbResult, DbRow, DbSqlFlavor, DbStatement,
    DbTransactionStep, DbTransactionStepResult, DbValue,
};
use bcs_http::{router::build_router, state::HttpAppState};
use bcs_service_api::{
    BotEventCommand, BotEventOutcome, BotRunContext, BotRunContextPort, ChatAbortCommand,
    ChatAbortOutcome, GroupCallbackCommand, GroupCallbackOutcome, MessageFlowService,
    ProviderBotCoordinationCommand, ProviderBotCoordinationOutcome, ProviderBotEventCommand,
    ProviderBotEventError, ProviderBotEventOutcome, ProviderBotEventService, ServiceError,
    ServiceResult, TaskCompleteCommand, TaskCompleteOutcome, TaskDispatchCommand,
    TaskDispatchOutcome, TaskRunAliasRegistration, WebSendCommand, WebSendOutcome,
};
use bcs_services_container::Services;
use memstack_workspace_core::workspace_provider_events::{
    WORKSPACE_PROVIDER_ID, WorkspaceProviderBotEventService,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use tokio::sync::Mutex;
use tower::ServiceExt;

const WORKSPACE_EVENT_TOKEN: &str = "workspace-event-secret";

struct EmptyRecoveryDb {
    terminal_proofs: Mutex<HashMap<String, TerminalProof>>,
    marker_failures: Mutex<HashSet<String>>,
}

#[derive(Clone)]
struct TerminalProof {
    status: String,
    report: Value,
    report_hash: String,
    provider_event_hash: Option<String>,
    provider_event_ingested_at: Option<String>,
}

#[async_trait]
impl DbPlugin for EmptyRecoveryDb {
    async fn query(&self, statement: DbStatement) -> DbResult<Vec<DbRow>> {
        let run_id = match statement.params().get(1) {
            Some(DbValue::String(run_id)) => run_id,
            _ => {
                return Err(DbError::Conversion(
                    "Provider terminal query is missing run id".to_string(),
                ));
            }
        };
        let proof = self.terminal_proofs.lock().await.get(run_id).cloned();
        if statement.sql().contains("JOIN workspace_outbox") {
            return Ok(proof
                .as_ref()
                .map(|proof| vec![terminal_proof_row(run_id, proof)])
                .unwrap_or_default());
        }
        if statement
            .sql()
            .contains("FROM workspace_agent_runtime_correlations correlation")
        {
            return Ok(proof
                .map(|_| vec![run_context_recovery_row(run_id)])
                .unwrap_or_default());
        }
        Ok(Vec::new())
    }

    async fn execute(&self, statement: DbStatement) -> DbResult<DbExecuteResult> {
        if statement.sql().contains("SET provider_event_hash =") {
            let expected_hash = statement_string_param(&statement, 0)?;
            let run_id = statement_string_param(&statement, 1)?;
            let expected_status = statement_string_param(&statement, 3)?;
            let repeated_hash = statement_string_param(&statement, 4)?;
            if expected_hash != repeated_hash {
                return Err(DbError::Conversion(
                    "Provider event hash bind parameters disagree".to_string(),
                ));
            }
            let mut proofs = self.terminal_proofs.lock().await;
            let affected_rows = proofs.get_mut(run_id).is_some_and(|proof| {
                if proof.status != expected_status
                    || proof
                        .provider_event_hash
                        .as_deref()
                        .is_some_and(|hash| hash != expected_hash)
                {
                    return false;
                }
                proof.provider_event_hash = Some(expected_hash.to_string());
                true
            });
            return Ok(execute_result(affected_rows));
        }
        if statement.sql().contains("SET provider_event_ingested_at =") {
            let run_id = statement_string_param(&statement, 0)?;
            let expected_hash = statement_string_param(&statement, 2)?;
            if self.marker_failures.lock().await.contains(run_id) {
                return Err(DbError::Backend(
                    "simulated Provider ingest marker failure".to_string(),
                ));
            }
            let mut proofs = self.terminal_proofs.lock().await;
            let affected_rows = proofs.get_mut(run_id).is_some_and(|proof| {
                if proof.provider_event_hash.as_deref() != Some(expected_hash) {
                    return false;
                }
                proof.provider_event_ingested_at = Some("2026-08-14T00:00:00Z".to_string());
                true
            });
            return Ok(execute_result(affected_rows));
        }
        Err(DbError::Unsupported(
            "unexpected execute in Provider HTTP contract".to_string(),
        ))
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

fn terminal_proof_row(run_id: &str, proof: &TerminalProof) -> DbRow {
    let payload = json!({
        "execution_status": &proof.status,
        "terminal_message_id": "message-1",
        "terminal_event_id": "event-1",
        "report_hash": &proof.report_hash,
        "report": &proof.report,
    })
    .to_string();
    DbRow::new(BTreeMap::from([
        (
            "correlation_id".to_string(),
            DbValue::String(format!("correlation-{run_id}")),
        ),
        (
            "provider_run_id".to_string(),
            DbValue::String(run_id.to_string()),
        ),
        (
            "delivery_request_id".to_string(),
            DbValue::String(format!("delivery-{run_id}")),
        ),
        ("status".to_string(), DbValue::String(proof.status.clone())),
        (
            "provider_event_hash".to_string(),
            proof
                .provider_event_hash
                .clone()
                .map_or(DbValue::Null, DbValue::String),
        ),
        (
            "provider_event_ingested_at".to_string(),
            proof
                .provider_event_ingested_at
                .clone()
                .map_or(DbValue::Null, DbValue::String),
        ),
        ("plan_id".to_string(), DbValue::Null),
        ("task_id".to_string(), DbValue::Null),
        ("attempt_id".to_string(), DbValue::Null),
        (
            "outbox_id".to_string(),
            DbValue::String(format!("outbox-{run_id}")),
        ),
        ("payload_json".to_string(), DbValue::String(payload)),
        (
            "metadata_json".to_string(),
            DbValue::String(json!({"report_hash": &proof.report_hash}).to_string()),
        ),
        ("terminal_id".to_string(), DbValue::Null),
        ("task_status".to_string(), DbValue::Null),
        ("attempt_status".to_string(), DbValue::Null),
    ]))
}

fn run_context_recovery_row(run_id: &str) -> DbRow {
    DbRow::new(BTreeMap::from([
        ("run_id".to_string(), DbValue::String(run_id.to_string())),
        ("bot_uuid".to_string(), DbValue::String("bot-1".to_string())),
        (
            "bcs_group_id".to_string(),
            DbValue::String("group-1".to_string()),
        ),
        (
            "bcs_session_id".to_string(),
            DbValue::String("session-1".to_string()),
        ),
        ("deadline_ms".to_string(), DbValue::I64(i64::MAX)),
    ]))
}

fn statement_string_param(statement: &DbStatement, index: usize) -> DbResult<&str> {
    match statement.params().get(index) {
        Some(DbValue::String(value)) => Ok(value),
        _ => Err(DbError::Conversion(format!(
            "Provider terminal statement is missing string parameter {index}"
        ))),
    }
}

fn execute_result(affected: bool) -> DbExecuteResult {
    DbExecuteResult {
        affected_rows: u64::from(affected),
        last_insert_id: None,
    }
}

fn provider_event(run_id: &str) -> Value {
    json!({
        "run_id": run_id,
        "seq": 1,
        "state": "final",
        "message": {"content": [{"type": "text", "text": "done"}]},
    })
}

fn terminal_report(run_id: &str) -> Value {
    json!({
        "provider_state": "final",
        "sequence": 1,
        "message_text": "done",
        "provider_event": provider_event(run_id),
    })
}

fn terminal_proof(run_id: &str) -> Result<TerminalProof, serde_json::Error> {
    let report = terminal_report(run_id);
    Ok(TerminalProof {
        status: "completed".to_string(),
        report_hash: canonical_json_hash(&report)?,
        report,
        provider_event_hash: None,
        provider_event_ingested_at: None,
    })
}

fn canonical_json_hash(value: &Value) -> Result<String, serde_json::Error> {
    let bytes = serde_json::to_vec(&canonical_json(value))?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(canonical_json).collect()),
        Value::Object(items) => Value::Object(
            items
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect::<BTreeMap<_, _>>()
                .into_iter()
                .collect(),
        ),
        _ => value.clone(),
    }
}

#[derive(Default)]
struct RecordingFallback {
    provider_ids: Mutex<Vec<String>>,
}

#[async_trait]
impl ProviderBotEventService for RecordingFallback {
    async fn submit_event(
        &self,
        command: ProviderBotEventCommand,
    ) -> Result<ProviderBotEventOutcome, ProviderBotEventError> {
        self.provider_ids.lock().await.push(command.provider_id);
        Ok(ProviderBotEventOutcome {
            delivered_count: 7,
            failed_count: 0,
        })
    }

    async fn submit_coordination(
        &self,
        _command: ProviderBotCoordinationCommand,
    ) -> Result<ProviderBotCoordinationOutcome, ProviderBotEventError> {
        Ok(ProviderBotCoordinationOutcome {
            processed: true,
            duplicate: false,
        })
    }
}

#[derive(Default)]
struct RunState {
    contexts: HashMap<String, BotRunContext>,
    terminal_inflight: HashSet<String>,
}

#[derive(Default)]
struct RecordingRunContext {
    state: Mutex<RunState>,
}

#[async_trait]
impl BotRunContextPort for RecordingRunContext {
    async fn put_context(&self, context: BotRunContext) {
        self.state
            .lock()
            .await
            .contexts
            .insert(context.run_id.clone(), context);
    }

    async fn get_context(&self, run_id: &str) -> Option<BotRunContext> {
        self.state.lock().await.contexts.get(run_id).cloned()
    }

    async fn try_begin_terminal(&self, run_id: &str) -> bool {
        let mut state = self.state.lock().await;
        if state
            .contexts
            .get(run_id)
            .is_none_or(|context| context.terminal)
            || state.terminal_inflight.contains(run_id)
        {
            return false;
        }
        state.terminal_inflight.insert(run_id.to_string())
    }

    async fn mark_terminal(&self, run_id: &str) -> bool {
        let mut state = self.state.lock().await;
        state.terminal_inflight.remove(run_id);
        let Some(context) = state.contexts.get_mut(run_id) else {
            return false;
        };
        if context.terminal {
            return false;
        }
        context.terminal = true;
        true
    }

    async fn release_terminal(&self, run_id: &str) {
        self.state.lock().await.terminal_inflight.remove(run_id);
    }
}

#[derive(Default)]
struct RecordingMessageFlow {
    events: Mutex<Vec<BotEventCommand>>,
}

fn unused_message_flow<T>() -> ServiceResult<T> {
    Err(ServiceError::InternalError(
        "message flow method is not used by this contract".to_string(),
    ))
}

#[async_trait]
impl MessageFlowService for RecordingMessageFlow {
    async fn handle_web_send(&self, _command: WebSendCommand) -> ServiceResult<WebSendOutcome> {
        unused_message_flow()
    }

    async fn handle_bot_event(&self, command: BotEventCommand) -> ServiceResult<BotEventOutcome> {
        self.events.lock().await.push(command);
        Ok(BotEventOutcome {
            bot_deliveries: Vec::new(),
            frontend_deliveries: Vec::new(),
            unregistered_run_ids: Vec::new(),
            mentions: Vec::new(),
            delivered_count: 1,
            failed_count: 0,
            delivery_results: Vec::new(),
        })
    }

    async fn handle_group_callback(
        &self,
        _command: GroupCallbackCommand,
    ) -> ServiceResult<GroupCallbackOutcome> {
        unused_message_flow()
    }

    async fn handle_chat_abort(
        &self,
        _command: ChatAbortCommand,
    ) -> ServiceResult<ChatAbortOutcome> {
        unused_message_flow()
    }

    async fn register_task_run_alias(
        &self,
        _task_id: &str,
        _run_id: &str,
        _bot_id: &str,
    ) -> ServiceResult<TaskRunAliasRegistration> {
        unused_message_flow()
    }

    async fn handle_task_dispatch(
        &self,
        _command: TaskDispatchCommand,
    ) -> ServiceResult<TaskDispatchOutcome> {
        unused_message_flow()
    }

    async fn handle_task_complete(
        &self,
        _command: TaskCompleteCommand,
    ) -> ServiceResult<TaskCompleteOutcome> {
        unused_message_flow()
    }
}

struct TestApp {
    app: Router,
    fallback: Arc<RecordingFallback>,
    run_context: Arc<RecordingRunContext>,
    message_flow: Arc<RecordingMessageFlow>,
    terminal_proofs: Arc<EmptyRecoveryDb>,
}

fn test_app() -> Result<TestApp, std::io::Error> {
    let fallback = Arc::new(RecordingFallback::default());
    let run_context = Arc::new(RecordingRunContext::default());
    let message_flow = Arc::new(RecordingMessageFlow::default());
    let terminal_proofs = Arc::new(EmptyRecoveryDb {
        terminal_proofs: Mutex::new(HashMap::from([(
            "run-open".to_string(),
            terminal_proof("run-open").map_err(std::io::Error::other)?,
        )])),
        marker_failures: Mutex::new(HashSet::new()),
    });
    let provider_events = WorkspaceProviderBotEventService::new(
        fallback.clone(),
        WORKSPACE_EVENT_TOKEN.to_string(),
        run_context.clone(),
        message_flow.clone(),
        terminal_proofs.clone(),
        DbSqlFlavor::Sqlite,
        60_000,
    )
    .map_err(std::io::Error::other)?;
    let services = Services::builder()
        .provider_bot_events(Arc::new(provider_events))
        .bot_run_context(run_context.clone())
        .message_flow(message_flow.clone())
        .build_for_test();

    Ok(TestApp {
        app: build_router(HttpAppState::new(services)),
        fallback,
        run_context,
        message_flow,
        terminal_proofs,
    })
}

fn bot_event_request(
    provider_id: &str,
    token: &str,
    run_id: &str,
) -> Result<Request<Body>, axum::http::Error> {
    bot_event_request_with_body(provider_id, token, terminal_event_body(run_id))
}

fn bot_event_request_with_body(
    provider_id: &str,
    token: &str,
    body: Value,
) -> Result<Request<Body>, axum::http::Error> {
    Request::builder()
        .method("POST")
        .uri("/bot/events")
        .header("content-type", "application/json")
        .header("X-BCN-Provider-Id", provider_id)
        .header("authorization", format!("Bearer {token}"))
        .body(Body::from(body.to_string()))
}

fn terminal_event_body(run_id: &str) -> Value {
    let mut payload = provider_event(run_id);
    payload["terminal_message_id"] = json!("message-1");
    payload["terminal_event_id"] = json!("event-1");
    payload["terminal_report"] = terminal_report(run_id);
    json!({
        "run_id": run_id,
        "seq": 1,
        "event": "chat",
        "message": {"text": "done"},
        "payload": payload,
    })
}

fn delta_event_request(
    provider_id: &str,
    token: &str,
    run_id: &str,
) -> Result<Request<Body>, axum::http::Error> {
    bot_event_request_with_body(
        provider_id,
        token,
        json!({
            "run_id": run_id,
            "seq": 1,
            "event": "chat",
            "message": {"text": "working"},
            "payload": {
                "run_id": run_id,
                "seq": 1,
                "state": "delta",
                "message": {"content": [{"type": "text", "text": "working"}]},
            },
        }),
    )
}

async fn response_json(response: Response<Body>) -> Result<Value, Box<dyn std::error::Error>> {
    let body = to_bytes(response.into_body(), usize::MAX).await?;
    Ok(serde_json::from_slice(&body)?)
}

async fn put_context(run_context: &RecordingRunContext, run_id: &str, deadline_ms: u64) {
    run_context
        .put_context(BotRunContext {
            run_id: run_id.to_string(),
            bot_id: "bot-1".to_string(),
            group_id: "group-1".to_string(),
            bcs_session_id: Some("session-1".to_string()),
            deadline_ms,
            terminal: false,
        })
        .await;
}

#[tokio::test]
async fn workspace_provider_callback_enforces_token_and_run_lifecycle()
-> Result<(), Box<dyn std::error::Error>> {
    let TestApp {
        app,
        fallback,
        run_context,
        message_flow,
        terminal_proofs,
    } = test_app()?;

    let wrong_token = app
        .clone()
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            "wrong-token",
            "run-open",
        )?)
        .await?;
    assert_eq!(wrong_token.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(response_json(wrong_token).await?["error"], "unauthorized");

    let unknown_run = app
        .clone()
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            "run-unknown",
        )?)
        .await?;
    assert_eq!(unknown_run.status(), StatusCode::NOT_FOUND);
    assert_eq!(response_json(unknown_run).await?["error"], "run_not_found");

    put_context(
        run_context.as_ref(),
        "run-expired",
        bcs_protocol::now_ms().saturating_sub(1),
    )
    .await;
    let expired_run = app
        .clone()
        .oneshot(delta_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            "run-expired",
        )?)
        .await?;
    assert_eq!(expired_run.status(), StatusCode::GONE);
    assert_eq!(response_json(expired_run).await?["error"], "run_terminated");

    put_context(
        run_context.as_ref(),
        "run-open",
        bcs_protocol::now_ms() + 60_000,
    )
    .await;
    let accepted = app
        .clone()
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            "run-open",
        )?)
        .await?;
    assert_eq!(accepted.status(), StatusCode::OK);
    let accepted_body = response_json(accepted).await?;
    assert_eq!(accepted_body["ok"], true);
    assert_eq!(accepted_body["delivered_count"], 1);
    {
        let proofs = terminal_proofs.terminal_proofs.lock().await;
        let proof = proofs
            .get("run-open")
            .ok_or("accepted terminal proof disappeared")?;
        let expected_hash = canonical_json_hash(&provider_event("run-open"))?;
        assert_eq!(
            proof.provider_event_hash.as_deref(),
            Some(expected_hash.as_str())
        );
        assert!(proof.provider_event_ingested_at.is_some());
    }
    run_context.state.lock().await.contexts.remove("run-open");

    let duplicate_terminal = app
        .clone()
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            "run-open",
        )?)
        .await?;
    assert_eq!(duplicate_terminal.status(), StatusCode::OK);
    let duplicate_body = response_json(duplicate_terminal).await?;
    assert_eq!(duplicate_body["delivered_count"], 0);
    assert_eq!(duplicate_body["failed_count"], 0);

    let events = message_flow.events.lock().await;
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].run_id, "run-open");
    assert_eq!(events[0].bot_id, "bot-1");
    assert_eq!(events[0].group_id, "group-1");
    assert_eq!(events[0].bcs_session_id.as_deref(), Some("session-1"));
    assert!(fallback.provider_ids.lock().await.is_empty());
    Ok(())
}

#[tokio::test]
async fn workspace_provider_terminal_without_durable_proof_is_not_acknowledged_and_can_retry()
-> Result<(), Box<dyn std::error::Error>> {
    let TestApp {
        app,
        run_context,
        message_flow,
        terminal_proofs,
        ..
    } = test_app()?;
    put_context(
        run_context.as_ref(),
        "run-without-proof",
        bcs_protocol::now_ms() + 60_000,
    )
    .await;

    let rejected = app
        .clone()
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            "run-without-proof",
        )?)
        .await?;
    assert_eq!(rejected.status(), StatusCode::INTERNAL_SERVER_ERROR);
    assert!(message_flow.events.lock().await.is_empty());
    assert_eq!(
        run_context
            .get_context("run-without-proof")
            .await
            .map(|context| context.terminal),
        Some(false)
    );

    terminal_proofs.terminal_proofs.lock().await.insert(
        "run-without-proof".to_string(),
        terminal_proof("run-without-proof")?,
    );
    let accepted = app
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            "run-without-proof",
        )?)
        .await?;
    assert_eq!(accepted.status(), StatusCode::OK);
    assert_eq!(message_flow.events.lock().await.len(), 1);
    Ok(())
}

#[tokio::test]
async fn workspace_provider_terminal_tampering_never_reaches_message_flow()
-> Result<(), Box<dyn std::error::Error>> {
    let TestApp {
        app,
        run_context,
        message_flow,
        terminal_proofs,
        ..
    } = test_app()?;
    let run_id = "run-tampered";
    put_context(
        run_context.as_ref(),
        run_id,
        bcs_protocol::now_ms() + 60_000,
    )
    .await;
    terminal_proofs
        .terminal_proofs
        .lock()
        .await
        .insert(run_id.to_string(), terminal_proof(run_id)?);

    let mut state = terminal_event_body(run_id);
    state["state"] = json!("error");
    let mut terminal_id = terminal_event_body(run_id);
    terminal_id["payload"]["terminal_event_id"] = json!("tampered-event");
    let mut message = terminal_event_body(run_id);
    message["message"]["text"] = json!("tampered message");
    let mut sequence = terminal_event_body(run_id);
    sequence["payload"]["terminal_report"]["sequence"] = json!(2);
    let mut provider_event = terminal_event_body(run_id);
    provider_event["payload"]["terminal_report"]["provider_event"]["unexpected"] = json!(true);

    for (body, expected_status) in [
        (state, StatusCode::BAD_REQUEST),
        (terminal_id, StatusCode::INTERNAL_SERVER_ERROR),
        (message, StatusCode::BAD_REQUEST),
        (sequence, StatusCode::BAD_REQUEST),
        (provider_event, StatusCode::BAD_REQUEST),
    ] {
        let response = app
            .clone()
            .oneshot(bot_event_request_with_body(
                WORKSPACE_PROVIDER_ID,
                WORKSPACE_EVENT_TOKEN,
                body,
            )?)
            .await?;
        assert_eq!(response.status(), expected_status);
    }

    assert!(message_flow.events.lock().await.is_empty());
    assert_eq!(
        run_context
            .get_context(run_id)
            .await
            .map(|context| context.terminal),
        Some(false)
    );
    Ok(())
}

#[tokio::test]
async fn workspace_provider_marker_failure_replay_only_retries_the_marker()
-> Result<(), Box<dyn std::error::Error>> {
    let TestApp {
        app,
        run_context,
        message_flow,
        terminal_proofs,
        ..
    } = test_app()?;
    let run_id = "run-marker-retry";
    put_context(
        run_context.as_ref(),
        run_id,
        bcs_protocol::now_ms() + 60_000,
    )
    .await;
    terminal_proofs
        .terminal_proofs
        .lock()
        .await
        .insert(run_id.to_string(), terminal_proof(run_id)?);
    terminal_proofs
        .marker_failures
        .lock()
        .await
        .insert(run_id.to_string());

    let marker_failed = app
        .clone()
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            run_id,
        )?)
        .await?;
    assert_eq!(marker_failed.status(), StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(message_flow.events.lock().await.len(), 1);
    assert_eq!(
        run_context
            .get_context(run_id)
            .await
            .map(|context| context.terminal),
        Some(true)
    );
    {
        let proofs = terminal_proofs.terminal_proofs.lock().await;
        let proof = proofs.get(run_id).ok_or("terminal proof disappeared")?;
        assert!(proof.provider_event_hash.is_some());
        assert!(proof.provider_event_ingested_at.is_none());
    }

    terminal_proofs.marker_failures.lock().await.remove(run_id);
    let replay = app
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            run_id,
        )?)
        .await?;
    assert_eq!(replay.status(), StatusCode::OK);
    let replay_body = response_json(replay).await?;
    assert_eq!(replay_body["delivered_count"], 0);
    assert_eq!(message_flow.events.lock().await.len(), 1);
    assert!(
        terminal_proofs
            .terminal_proofs
            .lock()
            .await
            .get(run_id)
            .and_then(|proof| proof.provider_event_ingested_at.as_ref())
            .is_some()
    );
    Ok(())
}

#[tokio::test]
async fn ordinary_provider_callback_uses_upstream_fallback()
-> Result<(), Box<dyn std::error::Error>> {
    let TestApp { app, fallback, .. } = test_app()?;

    let response = app
        .oneshot(bot_event_request(
            "ordinary-provider",
            "ordinary-provider-token",
            "ordinary-run",
        )?)
        .await?;
    assert_eq!(response.status(), StatusCode::OK);
    let body = response_json(response).await?;
    assert_eq!(body["ok"], true);
    assert_eq!(body["delivered_count"], 7);
    assert_eq!(
        fallback.provider_ids.lock().await.as_slice(),
        ["ordinary-provider"]
    );
    Ok(())
}
