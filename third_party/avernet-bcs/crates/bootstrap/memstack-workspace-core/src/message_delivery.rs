//! Delivery of committed Workspace messages to the existing Agent Runtime Provider.

use std::sync::Arc;

use bcs_domain::{BotDeliveryTarget, RedactedToken};
use bcs_protocol::{BcsFrame, BotDeliveryKind, RequestFrame};
use bcs_provider_http::HttpProviderTransport;
use bcs_route_security::OutboundUrlGuard;
use bcs_service_api::{
    BotDeliveryCommand, BotDeliveryPort, BotRunContext, BotRunContextPort,
    ProviderTransportPreference,
};
use memstack_workspace_service::{
    PublicWorkspaceMessageContext, PublicWorkspaceMessageDeliveryTarget,
    PublicWorkspaceMessageOutcome,
};
use serde_json::json;
use thiserror::Error;
use tokio::task::JoinSet;
use tracing::{error, info};
use uuid::Uuid;

use crate::workspace_provider_events::WORKSPACE_PROVIDER_ID;

/// Provider delivery configuration whose token remains redacted in the target.
#[derive(Clone)]
pub struct WorkspaceMessageRuntimeConfig {
    pub webhook_url: String,
    pub webhook_token: String,
    pub callback_timeout_ms: u64,
}

impl WorkspaceMessageRuntimeConfig {
    /// Validate the fixed internal Agent Runtime target at startup.
    ///
    /// Workspace Provider URLs are deployment configuration, never request
    /// input. This permits loopback/private Agent Runtime endpoints without
    /// weakening the strict transport used by ordinary Avernet Providers.
    ///
    /// # Errors
    ///
    /// Returns an error for a blank credential, zero timeout, or a malformed,
    /// non-HTTP, or credential-bearing webhook URL.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.webhook_url.trim().is_empty() {
            return Err("Workspace Provider webhook URL must not be blank");
        }
        workspace_provider_url_guard()
            .validate_configured_http_url(&self.webhook_url)
            .map_err(|_| "Workspace Provider webhook URL is not allowed")?;
        if self.webhook_token.trim().is_empty() {
            return Err("Workspace Provider webhook token must not be blank");
        }
        if self.callback_timeout_ms == 0 {
            return Err("Workspace Provider callback timeout must be positive");
        }
        Ok(())
    }
}

/// Runtime ports used after a Workspace message transaction has committed.
pub struct WorkspaceMessageRuntime {
    bot_delivery: Arc<dyn BotDeliveryPort>,
    bot_run_context: Arc<dyn BotRunContextPort>,
    config: WorkspaceMessageRuntimeConfig,
}

impl WorkspaceMessageRuntime {
    /// Create a delivery runtime without exposing credentials through `Debug`.
    ///
    /// # Errors
    ///
    /// Returns an error for blank Provider configuration or a zero timeout.
    pub fn new(
        bot_delivery: Arc<dyn BotDeliveryPort>,
        bot_run_context: Arc<dyn BotRunContextPort>,
        config: WorkspaceMessageRuntimeConfig,
    ) -> Result<Self, &'static str> {
        config.validate()?;
        Ok(Self {
            bot_delivery,
            bot_run_context,
            config,
        })
    }

    /// Create the production Workspace transport with a private-network policy
    /// scoped only to the fixed Agent Runtime URL in `config`.
    ///
    /// # Errors
    ///
    /// Returns the same configuration errors as [`Self::new`].
    pub fn with_internal_provider_transport(
        bot_run_context: Arc<dyn BotRunContextPort>,
        config: WorkspaceMessageRuntimeConfig,
    ) -> Result<Self, &'static str> {
        let bot_delivery = Arc::new(HttpProviderTransport::with_url_guard(
            workspace_provider_url_guard(),
        ));
        Self::new(bot_delivery, bot_run_context, config)
    }

    /// Deliver one committed or idempotently replayed message to every active
    /// Agent selected by its structured mentions.
    ///
    /// Completed run contexts are skipped. Open contexts are redelivered with
    /// the same deterministic request id so the Provider correlation suppresses
    /// duplicate Agent Runtime side effects.
    ///
    /// # Errors
    ///
    /// Returns an error when a run context conflicts, a delivery is rejected,
    /// or a delivery task cannot complete.
    pub async fn dispatch(
        &self,
        context: &PublicWorkspaceMessageContext,
        outcome: &PublicWorkspaceMessageOutcome,
    ) -> Result<(), WorkspaceMessageDeliveryError> {
        let mut deliveries = JoinSet::new();
        for target in outcome.delivery_targets.iter().cloned() {
            let bot_delivery = Arc::clone(&self.bot_delivery);
            let bot_run_context = Arc::clone(&self.bot_run_context);
            let config = self.config.clone();
            let context = context.clone();
            let outcome = outcome.clone();
            deliveries.spawn(async move {
                dispatch_target(
                    bot_delivery,
                    bot_run_context,
                    &config,
                    &context,
                    &outcome,
                    target,
                )
                .await
            });
        }

        let mut first_error = None;
        while let Some(result) = deliveries.join_next().await {
            match result {
                Ok(Ok(())) => {}
                Ok(Err(delivery_error)) => {
                    first_error.get_or_insert(delivery_error);
                }
                Err(join_error) => {
                    first_error.get_or_insert_with(|| {
                        WorkspaceMessageDeliveryError::Task(join_error.to_string())
                    });
                }
            }
        }
        first_error.map_or(Ok(()), Err)
    }
}

fn workspace_provider_url_guard() -> OutboundUrlGuard {
    OutboundUrlGuard::new(false, true)
}

/// Fail-closed Provider delivery failure reported to the public HTTP boundary.
#[derive(Debug, Error)]
pub enum WorkspaceMessageDeliveryError {
    #[error("Workspace Provider run context conflicts with an existing delivery")]
    RunContextConflict,
    #[error("Workspace Provider callback deadline overflowed")]
    DeadlineOverflow,
    #[error("Workspace Provider rejected delivery for bot {bot_id}")]
    Rejected { bot_id: String },
    #[error("Workspace Provider delivery failed for bot {bot_id}: {message}")]
    Delivery { bot_id: String, message: String },
    #[error("Workspace Provider delivery task failed: {0}")]
    Task(String),
}

async fn dispatch_target(
    bot_delivery: Arc<dyn BotDeliveryPort>,
    bot_run_context: Arc<dyn BotRunContextPort>,
    config: &WorkspaceMessageRuntimeConfig,
    context: &PublicWorkspaceMessageContext,
    outcome: &PublicWorkspaceMessageOutcome,
    target: PublicWorkspaceMessageDeliveryTarget,
) -> Result<(), WorkspaceMessageDeliveryError> {
    let run_id = delivery_request_id(&outcome.message.id, &target.agent_id);
    let expected_context = BotRunContext {
        run_id: run_id.clone(),
        bot_id: target.bot_uuid.clone(),
        group_id: outcome.group_id.clone(),
        bcs_session_id: Some(outcome.session_id.clone()),
        deadline_ms: bcs_protocol::now_ms()
            .checked_add(config.callback_timeout_ms)
            .ok_or(WorkspaceMessageDeliveryError::DeadlineOverflow)?,
        terminal: false,
    };
    if let Some(existing) = bot_run_context.get_context(&run_id).await {
        if existing.bot_id != expected_context.bot_id
            || existing.group_id != expected_context.group_id
            || existing.bcs_session_id != expected_context.bcs_session_id
        {
            return Err(WorkspaceMessageDeliveryError::RunContextConflict);
        }
        if existing.terminal {
            info!(
                run_id,
                bot_id = %target.bot_uuid,
                "Workspace Provider delivery already completed"
            );
            return Ok(());
        }
    } else {
        bot_run_context.put_context(expected_context).await;
    }

    let frame = BcsFrame::Request(RequestFrame::new(
        run_id.clone(),
        "chat.send",
        Some(json!({
            "bcs_group_id": outcome.group_id,
            "bcs_session_id": outcome.session_id,
            "session_id": outcome.session_id,
            "message": outcome.message.content,
            "timeout_ms": config.callback_timeout_ms,
            "extensions": {
                "tenant_id": context.tenant_id,
                "project_id": context.project_id,
                "workspace_id": context.workspace_id,
                "user_id": context.user_id,
                "conversation_id": agent_conversation_id(&context.workspace_id, &target.agent_id),
                "bcs_message_id": outcome.message.id,
                "workspace_message_correlation_id": outcome.correlation_id,
            }
        })),
    ));
    let result = bot_delivery
        .deliver(BotDeliveryCommand {
            target: BotDeliveryTarget::HttpProvider {
                bot_id: target.bot_uuid.clone(),
                provider_id: WORKSPACE_PROVIDER_ID.to_string(),
                provider_bot_ref: target.agent_id,
                webhook_url: config.webhook_url.clone(),
                bcs_to_provider_token: RedactedToken::new(config.webhook_token.clone()),
                protocol_version: "2.0".to_string(),
            },
            run_id: run_id.clone(),
            frame,
            delivery_kind: BotDeliveryKind::Send,
            provider_transport: ProviderTransportPreference::Callback,
            provider_bypass_headers: Vec::new(),
        })
        .await
        .map_err(|delivery_error| {
            error!(
                run_id,
                bot_id = %target.bot_uuid,
                error = %delivery_error,
                "Workspace Provider delivery failed"
            );
            WorkspaceMessageDeliveryError::Delivery {
                bot_id: target.bot_uuid.clone(),
                message: delivery_error.to_string(),
            }
        })?;
    if !result.delivered {
        error!(
            run_id,
            bot_id = %target.bot_uuid,
            "Workspace Provider rejected delivery"
        );
        return Err(WorkspaceMessageDeliveryError::Rejected {
            bot_id: target.bot_uuid,
        });
    }
    info!(
        run_id,
        bot_id = %target.bot_uuid,
        "Workspace Provider delivery accepted"
    );
    Ok(())
}

fn delivery_request_id(message_id: &str, agent_id: &str) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_DNS,
        format!("workspace-message:{message_id}:agent:{agent_id}").as_bytes(),
    )
    .to_string()
}

fn agent_conversation_id(workspace_id: &str, agent_id: &str) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_DNS,
        format!("workspace:{workspace_id}:agent:{agent_id}").as_bytes(),
    )
    .to_string()
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use async_trait::async_trait;
    use bcs_service_api::{BotDeliveryResult, ServiceResult};
    use tokio::sync::Mutex;

    use super::*;

    #[derive(Default)]
    struct RecordingDelivery {
        commands: Mutex<Vec<BotDeliveryCommand>>,
    }

    #[async_trait]
    impl BotDeliveryPort for RecordingDelivery {
        async fn is_available(&self, _target: &BotDeliveryTarget) -> bool {
            true
        }

        async fn deliver(&self, command: BotDeliveryCommand) -> ServiceResult<BotDeliveryResult> {
            let target_bot_id = command.target_bot_id().to_string();
            self.commands.lock().await.push(command);
            Ok(BotDeliveryResult {
                target_bot_id,
                delivered: true,
                error: None,
            })
        }
    }

    #[derive(Default)]
    struct RecordingRunContext {
        contexts: Mutex<HashMap<String, BotRunContext>>,
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

        async fn try_begin_terminal(&self, _run_id: &str) -> bool {
            true
        }

        async fn mark_terminal(&self, run_id: &str) -> bool {
            let mut contexts = self.contexts.lock().await;
            let Some(context) = contexts.get_mut(run_id) else {
                return false;
            };
            context.terminal = true;
            true
        }

        async fn release_terminal(&self, _run_id: &str) {}
    }

    fn outcome() -> PublicWorkspaceMessageOutcome {
        PublicWorkspaceMessageOutcome {
            message: memstack_workspace_service::PublicWorkspaceMessage {
                id: "message-1".to_string(),
                workspace_id: "workspace-1".to_string(),
                sender_id: "user-1".to_string(),
                sender_type: "human".to_string(),
                content: "hello".to_string(),
                mentions: vec!["agent-1".to_string()],
                parent_message_id: None,
                metadata: json!({}),
                created_at: "2026-08-11T00:00:00Z".to_string(),
            },
            group_id: "group-1".to_string(),
            session_id: "session-1".to_string(),
            correlation_id: "correlation-1".to_string(),
            delivery_targets: vec![PublicWorkspaceMessageDeliveryTarget {
                agent_id: "agent-1".to_string(),
                bot_uuid: "bot-1".to_string(),
                display_name: Some("Agent 1".to_string()),
            }],
            replayed: false,
        }
    }

    fn context() -> PublicWorkspaceMessageContext {
        PublicWorkspaceMessageContext {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
            user_id: "user-1".to_string(),
            user_is_superuser: false,
            authenticated_email: Some("user@example.com".to_string()),
        }
    }

    #[tokio::test]
    async fn dispatch_registers_context_and_emits_deterministic_provider_request()
    -> Result<(), Box<dyn std::error::Error>> {
        let delivery = Arc::new(RecordingDelivery::default());
        let contexts = Arc::new(RecordingRunContext::default());
        let runtime = WorkspaceMessageRuntime::new(
            delivery.clone(),
            contexts.clone(),
            WorkspaceMessageRuntimeConfig {
                webhook_url: "http://127.0.0.1:18080/internal/v1/workspace-core/provider"
                    .to_string(),
                webhook_token: "provider-webhook-secret".to_string(),
                callback_timeout_ms: 60_000,
            },
        )?;

        runtime.dispatch(&context(), &outcome()).await?;
        runtime.dispatch(&context(), &outcome()).await?;

        let commands = delivery.commands.lock().await;
        assert_eq!(commands.len(), 2);
        assert_eq!(commands[0].run_id, commands[1].run_id);
        let BotDeliveryTarget::HttpProvider { webhook_url, .. } = &commands[0].target else {
            return Err(std::io::Error::other("delivery must use an HTTP Provider target").into());
        };
        assert_eq!(
            webhook_url,
            "http://127.0.0.1:18080/internal/v1/workspace-core/provider"
        );
        let BcsFrame::Request(frame) = &commands[0].frame else {
            return Err(std::io::Error::other("delivery must use a request frame").into());
        };
        let params = frame
            .params
            .as_ref()
            .ok_or_else(|| std::io::Error::other("chat.send params are missing"))?;
        assert_eq!(frame.method, "chat.send");
        assert_eq!(params["bcs_group_id"], "group-1");
        assert_eq!(params["bcs_session_id"], "session-1");
        assert_eq!(params["extensions"]["tenant_id"], "tenant-1");
        assert_eq!(params["extensions"]["project_id"], "project-1");
        assert_eq!(params["extensions"]["workspace_id"], "workspace-1");
        assert_eq!(params["extensions"]["user_id"], "user-1");
        assert_eq!(params["extensions"]["bcs_message_id"], "message-1");
        assert_eq!(contexts.contexts.lock().await.len(), 1);
        Ok(())
    }

    #[tokio::test]
    async fn completed_context_suppresses_replay_delivery() -> Result<(), Box<dyn std::error::Error>>
    {
        let delivery = Arc::new(RecordingDelivery::default());
        let contexts = Arc::new(RecordingRunContext::default());
        let runtime = WorkspaceMessageRuntime::new(
            delivery.clone(),
            contexts.clone(),
            WorkspaceMessageRuntimeConfig {
                webhook_url: "https://agent-runtime.example/provider".to_string(),
                webhook_token: "provider-webhook-secret".to_string(),
                callback_timeout_ms: 60_000,
            },
        )?;

        runtime.dispatch(&context(), &outcome()).await?;
        let run_id = delivery.commands.lock().await[0].run_id.clone();
        assert!(contexts.mark_terminal(&run_id).await);
        runtime.dispatch(&context(), &outcome()).await?;
        assert_eq!(delivery.commands.lock().await.len(), 1);
        Ok(())
    }

    #[test]
    fn runtime_accepts_fixed_internal_provider_webhook_urls() {
        for webhook_url in [
            "http://127.0.0.1:8080/provider",
            "http://10.0.0.1/provider",
            "http://localhost/provider",
        ] {
            let runtime = WorkspaceMessageRuntime::with_internal_provider_transport(
                Arc::new(RecordingRunContext::default()),
                WorkspaceMessageRuntimeConfig {
                    webhook_url: webhook_url.to_string(),
                    webhook_token: "provider-webhook-secret".to_string(),
                    callback_timeout_ms: 60_000,
                },
            );
            assert!(runtime.is_ok(), "{webhook_url}");
        }
    }

    #[test]
    fn runtime_rejects_non_http_or_credential_bearing_webhook_urls() {
        for webhook_url in ["file:///tmp/provider", "https://user@example.com/provider"] {
            let runtime = WorkspaceMessageRuntime::new(
                Arc::new(RecordingDelivery::default()),
                Arc::new(RecordingRunContext::default()),
                WorkspaceMessageRuntimeConfig {
                    webhook_url: webhook_url.to_string(),
                    webhook_token: "provider-webhook-secret".to_string(),
                    callback_timeout_ms: 60_000,
                },
            );
            assert!(
                matches!(
                    runtime,
                    Err("Workspace Provider webhook URL is not allowed")
                ),
                "{webhook_url}"
            );
        }
    }
}
