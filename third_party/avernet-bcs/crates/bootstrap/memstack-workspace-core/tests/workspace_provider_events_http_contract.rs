use std::{
    collections::{HashMap, HashSet},
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
    DbTransactionStep, DbTransactionStepResult,
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
use tokio::sync::Mutex;
use tower::ServiceExt;

const WORKSPACE_EVENT_TOKEN: &str = "workspace-event-secret";

struct EmptyRecoveryDb;

#[async_trait]
impl DbPlugin for EmptyRecoveryDb {
    async fn query(&self, _statement: DbStatement) -> DbResult<Vec<DbRow>> {
        Ok(Vec::new())
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
}

fn test_app() -> Result<TestApp, std::io::Error> {
    let fallback = Arc::new(RecordingFallback::default());
    let run_context = Arc::new(RecordingRunContext::default());
    let message_flow = Arc::new(RecordingMessageFlow::default());
    let provider_events = WorkspaceProviderBotEventService::new(
        fallback.clone(),
        WORKSPACE_EVENT_TOKEN.to_string(),
        run_context.clone(),
        message_flow.clone(),
        Arc::new(EmptyRecoveryDb),
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
    })
}

fn bot_event_request(
    provider_id: &str,
    token: &str,
    run_id: &str,
) -> Result<Request<Body>, axum::http::Error> {
    Request::builder()
        .method("POST")
        .uri("/bot/events")
        .header("content-type", "application/json")
        .header("X-BCN-Provider-Id", provider_id)
        .header("authorization", format!("Bearer {token}"))
        .body(Body::from(
            json!({
                "run_id": run_id,
                "state": "final",
                "event": "chat",
                "message": { "text": "done" }
            })
            .to_string(),
        ))
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
        .oneshot(bot_event_request(
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

    let duplicate_terminal = app
        .clone()
        .oneshot(bot_event_request(
            WORKSPACE_PROVIDER_ID,
            WORKSPACE_EVENT_TOKEN,
            "run-open",
        )?)
        .await?;
    assert_eq!(duplicate_terminal.status(), StatusCode::GONE);
    assert_eq!(
        response_json(duplicate_terminal).await?["error"],
        "run_terminated"
    );

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
