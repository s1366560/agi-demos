//! Restricted Provider callback bridge for Workspace Agent Runtime deliveries.

use std::sync::Arc;

use async_trait::async_trait;
use bcs_db_api::{
    DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, db_get_column,
    db_get_column_opt,
};
use bcs_service_api::{
    BotEventCommand, BotEventOutcome, BotRunContext, BotRunContextPort, ChatEventState,
    MessageFlowService, ProviderBotCoordinationCommand, ProviderBotCoordinationOutcome,
    ProviderBotEventCommand, ProviderBotEventCredential, ProviderBotEventError,
    ProviderBotEventOutcome, ProviderBotEventService, ServiceResult,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use tokio::sync::Mutex;
use tracing::{error, info};

/// Provider identity reserved for MemStack Workspace Agent Runtime callbacks.
pub const WORKSPACE_PROVIDER_ID: &str = "memstack-workspace-agent-runtime";

#[async_trait]
trait WorkspaceBotEventIngestPort: Send + Sync {
    async fn ingest(&self, command: BotEventCommand) -> ServiceResult<BotEventOutcome>;
}

struct MessageFlowEventIngest {
    message_flow: Arc<dyn MessageFlowService>,
}

#[async_trait]
impl WorkspaceBotEventIngestPort for MessageFlowEventIngest {
    async fn ingest(&self, command: BotEventCommand) -> ServiceResult<BotEventOutcome> {
        self.message_flow.handle_bot_event(command).await
    }
}

#[derive(Debug, Error)]
enum WorkspaceRunContextRecoveryError {
    #[error(transparent)]
    Database(#[from] DbError),

    #[error("persisted Workspace run context is missing required field {0}")]
    InvalidField(&'static str),

    #[error("persisted Workspace run context deadline is invalid")]
    InvalidDeadline,
}

#[async_trait]
trait WorkspaceRunContextRecoveryPort: Send + Sync {
    async fn recover(
        &self,
        run_id: &str,
    ) -> Result<Option<BotRunContext>, WorkspaceRunContextRecoveryError>;
}

struct DbWorkspaceRunContextRecovery {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    callback_timeout_ms: u64,
}

impl DbWorkspaceRunContextRecovery {
    fn new(
        db: Arc<dyn DbPlugin>,
        sql_flavor: DbSqlFlavor,
        callback_timeout_ms: u64,
    ) -> Result<Self, &'static str> {
        if sql_flavor == DbSqlFlavor::Mysql {
            return Err("Workspace run recovery supports only PostgreSQL and SQLite");
        }
        if callback_timeout_ms == 0 {
            return Err("Workspace Provider callback timeout must be positive");
        }
        Ok(Self {
            db,
            sql_flavor,
            callback_timeout_ms,
        })
    }
}

#[async_trait]
impl WorkspaceRunContextRecoveryPort for DbWorkspaceRunContextRecovery {
    async fn recover(
        &self,
        run_id: &str,
    ) -> Result<Option<BotRunContext>, WorkspaceRunContextRecoveryError> {
        let rows = self
            .db
            .query(build_run_context_recovery(
                self.sql_flavor,
                run_id,
                self.callback_timeout_ms,
            ))
            .await?;
        rows.first().map(run_context_from_row).transpose()
    }
}

/// Wraps the upstream Provider event service with one fail-closed Workspace
/// branch. All non-Workspace providers retain the original BCS behavior.
pub struct WorkspaceProviderBotEventService {
    fallback: Arc<dyn ProviderBotEventService>,
    event_token: String,
    bot_run_context: Arc<dyn BotRunContextPort>,
    run_context_recovery: Arc<dyn WorkspaceRunContextRecoveryPort>,
    recovery_gate: Mutex<()>,
    event_ingest: Arc<dyn WorkspaceBotEventIngestPort>,
}

impl WorkspaceProviderBotEventService {
    /// Build the restricted Workspace callback service.
    ///
    /// # Errors
    ///
    /// Returns an error when the dedicated callback token is blank.
    pub fn new(
        fallback: Arc<dyn ProviderBotEventService>,
        event_token: String,
        bot_run_context: Arc<dyn BotRunContextPort>,
        message_flow: Arc<dyn MessageFlowService>,
        db: Arc<dyn DbPlugin>,
        sql_flavor: DbSqlFlavor,
        callback_timeout_ms: u64,
    ) -> Result<Self, &'static str> {
        if event_token.trim().is_empty() {
            return Err("Workspace Provider event token must not be blank");
        }
        Ok(Self {
            fallback,
            event_token,
            bot_run_context,
            run_context_recovery: Arc::new(DbWorkspaceRunContextRecovery::new(
                db,
                sql_flavor,
                callback_timeout_ms,
            )?),
            recovery_gate: Mutex::new(()),
            event_ingest: Arc::new(MessageFlowEventIngest { message_flow }),
        })
    }

    async fn resolve_run_context(
        &self,
        run_id: &str,
    ) -> Result<BotRunContext, ProviderBotEventError> {
        if let Some(context) = self.bot_run_context.get_context(run_id).await {
            return Ok(context);
        }

        // Serialize only cache-miss recovery. The second lookup prevents a
        // late database response from overwriting a terminal context restored
        // by another callback.
        let _recovery_guard = self.recovery_gate.lock().await;
        if let Some(context) = self.bot_run_context.get_context(run_id).await {
            return Ok(context);
        }
        let context = self
            .run_context_recovery
            .recover(run_id)
            .await
            .map_err(|recovery_error| {
                error!(
                    provider_id = WORKSPACE_PROVIDER_ID,
                    run_id,
                    error = %recovery_error,
                    "Workspace Provider run context recovery failed"
                );
                ProviderBotEventError::Internal(
                    "Workspace Provider run context recovery failed".to_string(),
                )
            })?
            .ok_or_else(|| ProviderBotEventError::RunNotFound("run_not_found".to_string()))?;
        self.bot_run_context.put_context(context.clone()).await;
        info!(
            provider_id = WORKSPACE_PROVIDER_ID,
            run_id,
            bot_id = %context.bot_id,
            group_id = %context.group_id,
            "Workspace Provider run context recovered"
        );
        Ok(context)
    }

    async fn submit_workspace_event(
        &self,
        command: ProviderBotEventCommand,
    ) -> Result<ProviderBotEventOutcome, ProviderBotEventError> {
        authenticate_workspace_credential(&command.credential, &self.event_token)?;
        if command.run_id.trim().is_empty() {
            return Err(ProviderBotEventError::InvalidRequest(
                "run_id is required".to_string(),
            ));
        }
        if !matches!(command.event.as_deref(), None | Some("chat")) {
            return Err(ProviderBotEventError::InvalidRequest(
                "Workspace Provider accepts only chat events".to_string(),
            ));
        }

        let context = self.resolve_run_context(&command.run_id).await?;
        if context.terminal || bcs_protocol::now_ms() > context.deadline_ms {
            return Err(ProviderBotEventError::RunTerminated(
                "run_terminated".to_string(),
            ));
        }

        let terminal = is_terminal(&command.state);
        if matches!(command.state, ChatEventState::Final) && command.message_text.trim().is_empty()
        {
            return Err(ProviderBotEventError::InvalidRequest(
                "final Workspace Provider event must include text".to_string(),
            ));
        }
        if terminal
            && !self
                .bot_run_context
                .try_begin_terminal(&command.run_id)
                .await
        {
            return Err(ProviderBotEventError::RunTerminated(
                "run_terminated".to_string(),
            ));
        }

        let payload = workspace_event_payload(&command);
        let run_id = command.run_id.clone();
        let outcome = self
            .event_ingest
            .ingest(BotEventCommand {
                bot_id: context.bot_id.clone(),
                run_id: run_id.clone(),
                group_id: context.group_id.clone(),
                event_type: "chat.event".to_string(),
                event_payload: payload,
                state: command.state,
                bcs_session_id: context.bcs_session_id.clone(),
            })
            .await;
        let outcome = match outcome {
            Ok(outcome) => outcome,
            Err(flow_error) => {
                if terminal {
                    self.bot_run_context.release_terminal(&run_id).await;
                }
                error!(
                    provider_id = WORKSPACE_PROVIDER_ID,
                    run_id,
                    bot_id = %context.bot_id,
                    error = %flow_error,
                    "Workspace Provider callback ingest failed"
                );
                return Err(ProviderBotEventError::Internal(
                    "Workspace Provider callback ingest failed".to_string(),
                ));
            }
        };

        if terminal {
            let _ = self.bot_run_context.mark_terminal(&run_id).await;
        }
        info!(
            provider_id = WORKSPACE_PROVIDER_ID,
            run_id,
            bot_id = %context.bot_id,
            terminal,
            delivered_count = outcome.delivered_count,
            failed_count = outcome.failed_count,
            "Workspace Provider callback accepted"
        );
        Ok(ProviderBotEventOutcome {
            delivered_count: outcome.delivered_count,
            failed_count: outcome.failed_count,
        })
    }
}

fn build_run_context_recovery(
    flavor: DbSqlFlavor,
    run_id: &str,
    callback_timeout_ms: u64,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor).push_static(
        "SELECT correlation.provider_run_id AS run_id, binding.bot_uuid, \
         correlation.bcs_group_id, correlation.bcs_session_id, ",
    );
    let builder = match flavor {
        DbSqlFlavor::Postgres => builder
            .push_static("CAST(EXTRACT(EPOCH FROM correlation.updated_at) * 1000 AS BIGINT) + ")
            .bind(callback_timeout_ms),
        DbSqlFlavor::Sqlite => builder
            .push_static("CAST(strftime('%s', correlation.updated_at) AS INTEGER) * 1000 + ")
            .bind(callback_timeout_ms),
        DbSqlFlavor::Mysql => builder.push_static("0"),
    };
    builder
        .push_static(
            " AS deadline_ms FROM workspace_agent_runtime_correlations correlation \
             JOIN workspace_agent_bindings binding ON binding.tenant_id = correlation.tenant_id \
             AND binding.project_id = correlation.project_id \
             AND binding.workspace_id = correlation.workspace_id \
             AND binding.agent_id = correlation.provider_bot_ref \
             JOIN bcs_bots bot ON bot.bot_uuid = binding.bot_uuid AND bot.env = 'memstack' \
             JOIN bcs_group_participants participant \
             ON participant.group_id = correlation.bcs_group_id \
             AND participant.bot_uuid = binding.participant_actor_id \
             AND participant.env = 'memstack' WHERE correlation.provider_run_id = ",
        )
        .bind(run_id)
        .push_static(
            " AND (correlation.status = 'running' OR \
             (correlation.status IN ('completed', 'failed', 'aborted') \
             AND correlation.callback_completed_at IS NULL)) \
             AND correlation.provider_id = 'memstack-workspace-agent-runtime' \
             AND correlation.bcs_group_id IS NOT NULL \
             AND binding.is_active = TRUE AND bot.status = 'online' \
             AND bot.is_deleted = FALSE AND participant.actor_kind = 'bot' LIMIT 1",
        )
        .build()
}

fn run_context_from_row(row: &DbRow) -> Result<BotRunContext, WorkspaceRunContextRecoveryError> {
    let deadline_ms = db_get_column::<i64>(row, "deadline_ms")
        .map_err(WorkspaceRunContextRecoveryError::Database)?;
    Ok(BotRunContext {
        run_id: required_recovery_string(row, "run_id")?,
        bot_id: required_recovery_string(row, "bot_uuid")?,
        group_id: required_recovery_string(row, "bcs_group_id")?,
        bcs_session_id: db_get_column_opt(row, "bcs_session_id")?,
        deadline_ms: u64::try_from(deadline_ms)
            .map_err(|_| WorkspaceRunContextRecoveryError::InvalidDeadline)?,
        terminal: false,
    })
}

fn required_recovery_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceRunContextRecoveryError> {
    db_get_column_opt(row, column)?.ok_or(WorkspaceRunContextRecoveryError::InvalidField(column))
}

#[async_trait]
impl ProviderBotEventService for WorkspaceProviderBotEventService {
    async fn submit_event(
        &self,
        command: ProviderBotEventCommand,
    ) -> Result<ProviderBotEventOutcome, ProviderBotEventError> {
        if command.provider_id == WORKSPACE_PROVIDER_ID {
            self.submit_workspace_event(command).await
        } else {
            self.fallback.submit_event(command).await
        }
    }

    async fn submit_coordination(
        &self,
        command: ProviderBotCoordinationCommand,
    ) -> Result<ProviderBotCoordinationOutcome, ProviderBotEventError> {
        self.fallback.submit_coordination(command).await
    }
}

fn authenticate_workspace_credential(
    credential: &ProviderBotEventCredential,
    expected_token: &str,
) -> Result<(), ProviderBotEventError> {
    let ProviderBotEventCredential::StaticBearer(token) = credential else {
        return Err(ProviderBotEventError::Unauthorized(
            "auth_mode_mismatch".to_string(),
        ));
    };
    if !secret_matches(token.as_bytes(), expected_token.as_bytes()) {
        return Err(ProviderBotEventError::Unauthorized(
            "unauthorized".to_string(),
        ));
    }
    Ok(())
}

fn secret_matches(left: &[u8], right: &[u8]) -> bool {
    let left = Sha256::digest(left);
    let right = Sha256::digest(right);
    left.iter()
        .zip(right.iter())
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

fn is_terminal(state: &ChatEventState) -> bool {
    matches!(
        state,
        ChatEventState::Final | ChatEventState::Error | ChatEventState::Aborted
    )
}

fn workspace_event_payload(command: &ProviderBotEventCommand) -> Value {
    command.payload.clone().unwrap_or_else(|| {
        json!({
            "run_id": command.run_id,
            "state": state_name(&command.state),
            "message": {
                "content": [{"type": "text", "text": command.message_text}]
            }
        })
    })
}

fn state_name(state: &ChatEventState) -> &'static str {
    match state {
        ChatEventState::Final => "final",
        ChatEventState::Error => "error",
        ChatEventState::Aborted => "aborted",
        ChatEventState::Delta => "delta",
        ChatEventState::ToolCallStart => "tool_call_start",
        ChatEventState::ToolCallEnd => "tool_call_end",
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use bcs_db_api::{DbPlugin, DbStatement, DbValue};
    use bcs_db_local::LocalSqliteDbPlugin;
    use bcs_service_api::{BotRunContext, BotRunContextPort};
    use tokio::sync::Mutex;

    use super::*;

    #[derive(Default)]
    struct RecordingFallback {
        events: Mutex<Vec<String>>,
    }

    #[async_trait]
    impl ProviderBotEventService for RecordingFallback {
        async fn submit_event(
            &self,
            command: ProviderBotEventCommand,
        ) -> Result<ProviderBotEventOutcome, ProviderBotEventError> {
            self.events.lock().await.push(command.provider_id);
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
    struct RecordingRunContext {
        contexts: Mutex<HashMap<String, BotRunContext>>,
        terminal_inflight: Mutex<Vec<String>>,
    }

    #[async_trait]
    impl BotRunContextPort for RecordingRunContext {
        async fn put_context(&self, context: BotRunContext) {
            self.contexts
                .lock()
                .await
                .insert(context.run_id.clone(), context);
        }

        async fn get_context(&self, run_id: &str) -> Option<BotRunContext> {
            self.contexts.lock().await.get(run_id).cloned()
        }

        async fn try_begin_terminal(&self, run_id: &str) -> bool {
            let contexts = self.contexts.lock().await;
            if contexts.get(run_id).is_none_or(|context| context.terminal) {
                return false;
            }
            drop(contexts);
            let mut inflight = self.terminal_inflight.lock().await;
            if inflight.iter().any(|candidate| candidate == run_id) {
                return false;
            }
            inflight.push(run_id.to_string());
            true
        }

        async fn mark_terminal(&self, run_id: &str) -> bool {
            self.terminal_inflight
                .lock()
                .await
                .retain(|candidate| candidate != run_id);
            let mut contexts = self.contexts.lock().await;
            let Some(context) = contexts.get_mut(run_id) else {
                return false;
            };
            if context.terminal {
                return false;
            }
            context.terminal = true;
            true
        }

        async fn release_terminal(&self, run_id: &str) {
            self.terminal_inflight
                .lock()
                .await
                .retain(|candidate| candidate != run_id);
        }
    }

    #[derive(Default)]
    struct RecordingRecovery {
        contexts: Mutex<HashMap<String, BotRunContext>>,
        calls: Mutex<Vec<String>>,
    }

    #[async_trait]
    impl WorkspaceRunContextRecoveryPort for RecordingRecovery {
        async fn recover(
            &self,
            run_id: &str,
        ) -> Result<Option<BotRunContext>, WorkspaceRunContextRecoveryError> {
            self.calls.lock().await.push(run_id.to_string());
            Ok(self.contexts.lock().await.get(run_id).cloned())
        }
    }

    #[derive(Default)]
    struct RecordingIngest {
        commands: Mutex<Vec<BotEventCommand>>,
    }

    #[async_trait]
    impl WorkspaceBotEventIngestPort for RecordingIngest {
        async fn ingest(&self, command: BotEventCommand) -> ServiceResult<BotEventOutcome> {
            self.commands.lock().await.push(command);
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
    }

    fn service(
        run_context: Arc<RecordingRunContext>,
        fallback: Arc<RecordingFallback>,
        ingest: Arc<RecordingIngest>,
    ) -> WorkspaceProviderBotEventService {
        service_with_recovery(
            run_context,
            fallback,
            ingest,
            Arc::new(RecordingRecovery::default()),
        )
    }

    fn service_with_recovery(
        run_context: Arc<RecordingRunContext>,
        fallback: Arc<RecordingFallback>,
        ingest: Arc<RecordingIngest>,
        recovery: Arc<RecordingRecovery>,
    ) -> WorkspaceProviderBotEventService {
        WorkspaceProviderBotEventService {
            fallback,
            event_token: "workspace-event-secret".to_string(),
            bot_run_context: run_context,
            run_context_recovery: recovery,
            recovery_gate: Mutex::new(()),
            event_ingest: ingest,
        }
    }

    fn command(provider_id: &str, token: &str, state: ChatEventState) -> ProviderBotEventCommand {
        ProviderBotEventCommand {
            provider_id: provider_id.to_string(),
            credential: ProviderBotEventCredential::StaticBearer(token.to_string()),
            run_id: "run-1".to_string(),
            state,
            message_text: "done".to_string(),
            event: Some("chat".to_string()),
            payload: Some(json!({"state": "final", "message": {"content": "done"}})),
        }
    }

    async fn put_open_context(contexts: &RecordingRunContext) {
        contexts
            .put_context(BotRunContext {
                run_id: "run-1".to_string(),
                bot_id: "bot-1".to_string(),
                group_id: "group-1".to_string(),
                bcs_session_id: Some("session-1".to_string()),
                deadline_ms: u64::MAX,
                terminal: false,
            })
            .await;
    }

    #[tokio::test]
    async fn workspace_terminal_requires_token_and_known_run_and_is_idempotent()
    -> Result<(), Box<dyn std::error::Error>> {
        let contexts = Arc::new(RecordingRunContext::default());
        let fallback = Arc::new(RecordingFallback::default());
        let ingest = Arc::new(RecordingIngest::default());
        let service = service(contexts.clone(), fallback.clone(), ingest.clone());

        let wrong_token = service
            .submit_event(command(
                WORKSPACE_PROVIDER_ID,
                "wrong",
                ChatEventState::Final,
            ))
            .await;
        assert!(matches!(
            wrong_token,
            Err(ProviderBotEventError::Unauthorized(_))
        ));

        let missing_run = service
            .submit_event(command(
                WORKSPACE_PROVIDER_ID,
                "workspace-event-secret",
                ChatEventState::Final,
            ))
            .await;
        assert!(matches!(
            missing_run,
            Err(ProviderBotEventError::RunNotFound(_))
        ));

        put_open_context(contexts.as_ref()).await;
        let accepted = service
            .submit_event(command(
                WORKSPACE_PROVIDER_ID,
                "workspace-event-secret",
                ChatEventState::Final,
            ))
            .await?;
        assert_eq!(accepted.delivered_count, 1);
        assert_eq!(ingest.commands.lock().await.len(), 1);

        let duplicate = service
            .submit_event(command(
                WORKSPACE_PROVIDER_ID,
                "workspace-event-secret",
                ChatEventState::Final,
            ))
            .await;
        assert!(matches!(
            duplicate,
            Err(ProviderBotEventError::RunTerminated(_))
        ));
        assert!(fallback.events.lock().await.is_empty());
        Ok(())
    }

    #[tokio::test]
    async fn non_workspace_provider_falls_back_without_using_workspace_token()
    -> Result<(), Box<dyn std::error::Error>> {
        let contexts = Arc::new(RecordingRunContext::default());
        let fallback = Arc::new(RecordingFallback::default());
        let ingest = Arc::new(RecordingIngest::default());
        let service = service(contexts, fallback.clone(), ingest.clone());

        let outcome = service
            .submit_event(command(
                "ordinary-provider",
                "ordinary-token",
                ChatEventState::Delta,
            ))
            .await?;
        assert_eq!(outcome.delivered_count, 7);
        assert_eq!(
            fallback.events.lock().await.as_slice(),
            ["ordinary-provider"]
        );
        assert!(ingest.commands.lock().await.is_empty());
        Ok(())
    }

    #[tokio::test]
    async fn workspace_terminal_recovers_persisted_context_once_before_ingest()
    -> Result<(), Box<dyn std::error::Error>> {
        let contexts = Arc::new(RecordingRunContext::default());
        let fallback = Arc::new(RecordingFallback::default());
        let ingest = Arc::new(RecordingIngest::default());
        let recovery = Arc::new(RecordingRecovery::default());
        recovery.contexts.lock().await.insert(
            "run-1".to_string(),
            BotRunContext {
                run_id: "run-1".to_string(),
                bot_id: "persisted-bot".to_string(),
                group_id: "persisted-group".to_string(),
                bcs_session_id: Some("persisted-session".to_string()),
                deadline_ms: u64::MAX,
                terminal: false,
            },
        );
        let service =
            service_with_recovery(contexts.clone(), fallback, ingest.clone(), recovery.clone());

        service
            .submit_event(command(
                WORKSPACE_PROVIDER_ID,
                "workspace-event-secret",
                ChatEventState::Final,
            ))
            .await?;
        let commands = ingest.commands.lock().await;
        assert_eq!(commands.len(), 1);
        assert_eq!(commands[0].bot_id, "persisted-bot");
        assert_eq!(commands[0].group_id, "persisted-group");
        assert_eq!(
            commands[0].bcs_session_id.as_deref(),
            Some("persisted-session")
        );
        drop(commands);
        assert_eq!(recovery.calls.lock().await.as_slice(), ["run-1"]);
        assert!(contexts.get_context("run-1").await.is_some());
        Ok(())
    }

    #[test]
    fn recovery_statement_uses_dialect_placeholders_and_fixed_provider_scope() {
        let postgres = build_run_context_recovery(DbSqlFlavor::Postgres, "run-1", 60_000);
        assert!(postgres.sql().contains("$1"));
        assert!(postgres.sql().contains("$2"));
        assert!(postgres.sql().contains("correlation.status = 'running'"));
        assert!(postgres.sql().contains("correlation.callback_completed_at IS NULL"));
        assert!(
            postgres
                .sql()
                .contains("correlation.provider_id = 'memstack-workspace-agent-runtime'")
        );
        assert!(postgres.sql().contains("binding.is_active = TRUE"));
        assert_eq!(
            postgres.params(),
            &[DbValue::U64(60_000), DbValue::String("run-1".to_string())]
        );

        let sqlite = build_run_context_recovery(DbSqlFlavor::Sqlite, "run-1", 60_000);
        assert!(!sqlite.sql().contains("$1"));
        assert_eq!(sqlite.sql().matches('?').count(), 2);
        assert_eq!(sqlite.params(), postgres.params());
    }

    #[tokio::test]
    async fn sqlite_recovery_requires_open_callback_and_active_roster()
    -> Result<(), Box<dyn std::error::Error>> {
        let db = Arc::new(LocalSqliteDbPlugin::new()?);
        for statement in [
            "CREATE TABLE workspace_agent_runtime_correlations (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, provider_run_id TEXT NOT NULL, provider_id TEXT NOT NULL, provider_bot_ref TEXT NOT NULL, bcs_group_id TEXT, bcs_session_id TEXT, status TEXT NOT NULL, callback_completed_at TEXT, updated_at TEXT NOT NULL)",
            "CREATE TABLE workspace_agent_bindings (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, participant_actor_id TEXT NOT NULL, is_active INTEGER NOT NULL)",
            "CREATE TABLE bcs_bots (bot_uuid TEXT NOT NULL, env TEXT NOT NULL, status TEXT NOT NULL, is_deleted INTEGER NOT NULL)",
            "CREATE TABLE bcs_group_participants (group_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, env TEXT NOT NULL, actor_kind TEXT NOT NULL)",
            "INSERT INTO workspace_agent_runtime_correlations (tenant_id, project_id, workspace_id, provider_run_id, provider_id, provider_bot_ref, bcs_group_id, bcs_session_id, status, updated_at) VALUES ('tenant-1', 'project-1', 'workspace-1', 'run-1', 'memstack-workspace-agent-runtime', 'agent-1', 'group-1', 'session-1', 'running', CURRENT_TIMESTAMP)",
            "INSERT INTO workspace_agent_bindings (tenant_id, project_id, workspace_id, agent_id, bot_uuid, participant_actor_id, is_active) VALUES ('tenant-1', 'project-1', 'workspace-1', 'agent-1', 'bot-1', 'bot-1', TRUE)",
            "INSERT INTO bcs_bots (bot_uuid, env, status, is_deleted) VALUES ('bot-1', 'memstack', 'online', FALSE)",
            "INSERT INTO bcs_group_participants (group_id, bot_uuid, env, actor_kind) VALUES ('group-1', 'bot-1', 'memstack', 'bot')",
        ] {
            db.execute(DbStatement::new(statement)).await?;
        }
        let recovery = DbWorkspaceRunContextRecovery::new(db.clone(), DbSqlFlavor::Sqlite, 60_000)?;

        let context = recovery
            .recover("run-1")
            .await?
            .ok_or("running context was not recovered")?;
        assert_eq!(context.bot_id, "bot-1");
        assert_eq!(context.group_id, "group-1");
        assert_eq!(context.bcs_session_id.as_deref(), Some("session-1"));
        assert!(context.deadline_ms >= bcs_protocol::now_ms());

        db.execute(DbStatement::new(
            "UPDATE workspace_agent_runtime_correlations SET status = 'completed'",
        ))
        .await?;
        assert!(recovery.recover("run-1").await?.is_some());
        db.execute(DbStatement::new(
            "UPDATE workspace_agent_runtime_correlations SET callback_completed_at = CURRENT_TIMESTAMP",
        ))
        .await?;
        assert!(recovery.recover("run-1").await?.is_none());
        db.execute(DbStatement::new(
            "UPDATE workspace_agent_runtime_correlations SET status = 'running', callback_completed_at = NULL",
        ))
        .await?;
        db.execute(DbStatement::new(
            "UPDATE workspace_agent_bindings SET is_active = FALSE",
        ))
        .await?;
        assert!(recovery.recover("run-1").await?.is_none());
        Ok(())
    }
}
