//! Production ReAct binding: one generation lease and private durable input log.

use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};

use agistack_adapters_http_llm::RequestLoggedLlm;
use agistack_adapters_postgres::{
    AgentExecutionEventInsertRecord, PgAgentExecutionEventRepository,
};
use agistack_core::{
    model_request::{ModelRequestLog, ModelRequestStatus},
    ports::{CoreError, CoreResult},
    ReActEngine,
};
use agistack_plugin_host::{ScopeKindV2, ScopeV2};
use async_trait::async_trait;
use serde_json::{json, Value};

use crate::plugin_generation_v2::{
    RustServerGenerationAdmissionV2, RustServerOperationGenerationV2,
};

#[derive(Clone)]
pub(crate) struct AgentBoundaryFactoryV2 {
    admission: RustServerGenerationAdmissionV2,
    writer: Option<PgAgentExecutionEventRepository>,
    counter: Arc<AtomicU64>,
}

impl AgentBoundaryFactoryV2 {
    pub(crate) fn from_app(app: &crate::AppState) -> Self {
        Self {
            admission: app.agent_generation.clone(),
            writer: app.agent_event_writer.clone(),
            counter: app.event_counter.clone(),
        }
    }

    pub(crate) fn bind(
        &self,
        engine: ReActEngine,
        tenant_id: &str,
        project_id: &str,
        conversation_id: &str,
        message_id: Option<&str>,
        operation_id: &str,
    ) -> CoreResult<ReActEngine> {
        let generation = self
            .admission
            .admit_operation()
            .map_err(CoreError::Harness)?;
        let scope = ScopeV2 {
            kind: ScopeKindV2::Session,
            tenant_id: Some(tenant_id.into()),
            project_id: Some(project_id.into()),
            session_id: Some(conversation_id.into()),
        };
        let policy = generation
            .tool_policy(&scope, operation_id)
            .map_err(CoreError::Harness)?;
        let log = Arc::new(ServerModelRequestLogV2 {
            writer: self.writer.clone(),
            counter: self.counter.clone(),
            conversation_id: conversation_id.into(),
            message_id: message_id.map(str::to_owned),
            operation_id: operation_id.into(),
            contributors: generation.request_contributors(&scope),
            generation,
        });
        Ok(engine
            .with_tool_policy(crate::computer_use_device_v2::policy(policy))
            .map_llm(|inner| Arc::new(RequestLoggedLlm::new(inner, log))))
    }
}

#[derive(Clone)]
struct ServerModelRequestLogV2 {
    writer: Option<PgAgentExecutionEventRepository>,
    counter: Arc<AtomicU64>,
    conversation_id: String,
    message_id: Option<String>,
    operation_id: String,
    generation: Arc<RustServerOperationGenerationV2>,
    contributors: Value,
}

impl ServerModelRequestLogV2 {
    async fn append(&self, event_type: &str, attempt_id: &str, request: Value) -> CoreResult<()> {
        let writer = self.writer.as_ref().ok_or_else(|| {
            CoreError::Storage("durable model request storage is unavailable".into())
        })?;
        let (last, _) = writer.get_last_event_time(&self.conversation_id).await?;
        let time = chrono::Utc::now()
            .timestamp_micros()
            .max(last.saturating_add(1));
        let counter = self.counter.fetch_add(1, Ordering::Relaxed) + 1;
        let data = json!({
            "attempt_id": attempt_id, "operation_id": self.operation_id,
            "schema_version": 1, "format": "provider.http.json/v1",
            "generation_digest": self.generation.descriptor.digest,
            "contributors": self.contributors,
            "message_id": self.message_id, "request": request,
        });
        // Never publish full model inputs to the public WebSocket observation stream.
        writer
            .insert_event(AgentExecutionEventInsertRecord {
                id: &uuid::Uuid::new_v4().to_string(),
                conversation_id: &self.conversation_id,
                message_id: self.message_id.as_deref(),
                event_type,
                event_data: &data,
                event_time_us: time,
                event_counter: i32::try_from(counter).unwrap_or(i32::MAX),
                correlation_id: Some(&self.operation_id),
            })
            .await
    }
}

#[async_trait]
impl ModelRequestLog for ServerModelRequestLogV2 {
    async fn prepare_request(&self, protocol: &str, body: Value) -> CoreResult<String> {
        let id = uuid::Uuid::new_v4().to_string();
        self.append(
            "model_request_prepared",
            &id,
            json!({"protocol":protocol, "body":body}),
        )
        .await?;
        Ok(id)
    }
    async fn settle_request(&self, attempt_id: &str, status: ModelRequestStatus) -> CoreResult<()> {
        self.append(
            "model_request_settled",
            attempt_id,
            json!({"status":status}),
        )
        .await
    }
    fn cancel_request(&self, attempt_id: &str) {
        let log = self.clone();
        let id = attempt_id.to_owned();
        // The spawned append retains the exact generation until cancellation is
        // settled. A process crash still leaves its durable prepared event.
        tokio::spawn(async move {
            if log
                .settle_request(&id, ModelRequestStatus::Cancelled)
                .await
                .is_err()
            {
                eprintln!("model request cancellation persistence failed");
            }
        });
    }
}
