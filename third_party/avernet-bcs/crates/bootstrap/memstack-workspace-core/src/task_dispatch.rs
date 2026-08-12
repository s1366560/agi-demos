//! Provider delivery for durable Workspace execution Task assignments.

use std::sync::Arc;

use bcs_domain::{BotDeliveryTarget, RedactedToken};
use bcs_protocol::{BcsFrame, BotDeliveryKind, RequestFrame};
use bcs_provider_http::HttpProviderTransport;
use bcs_route_security::OutboundUrlGuard;
use bcs_service_api::{
    BotDeliveryCommand, BotDeliveryPort, BotRunContext, BotRunContextPort,
    ProviderTransportPreference,
};
use memstack_workspace_service::PublicWorkspaceTaskDispatchClaim;
use serde_json::{Value, json};
use thiserror::Error;
use tracing::{error, info};

use crate::workspace_provider_events::WORKSPACE_PROVIDER_ID;

/// Fixed internal Provider target used for Task dispatch.
#[derive(Clone)]
pub struct WorkspaceTaskRuntimeConfig {
    pub webhook_url: String,
    pub webhook_token: String,
    pub callback_timeout_ms: u64,
}

impl WorkspaceTaskRuntimeConfig {
    /// Validate the startup-owned Provider target and deadline.
    ///
    /// # Errors
    ///
    /// Returns an error for a blank credential, invalid URL, or zero timeout.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.webhook_url.trim().is_empty() {
            return Err("Workspace Task Provider webhook URL must not be blank");
        }
        workspace_provider_url_guard()
            .validate_configured_http_url(&self.webhook_url)
            .map_err(|_| "Workspace Task Provider webhook URL is not allowed")?;
        if self.webhook_token.trim().is_empty() {
            return Err("Workspace Task Provider webhook token must not be blank");
        }
        if self.callback_timeout_ms == 0 {
            return Err("Workspace Task Provider callback timeout must be positive");
        }
        Ok(())
    }
}

/// Correlated `chat.inject` runtime for one durable Task dispatch claim.
pub struct WorkspaceTaskRuntime {
    bot_delivery: Arc<dyn BotDeliveryPort>,
    bot_run_context: Arc<dyn BotRunContextPort>,
    config: WorkspaceTaskRuntimeConfig,
}

impl WorkspaceTaskRuntime {
    /// Construct a Task runtime over injected Avernet delivery ports.
    ///
    /// # Errors
    ///
    /// Returns an error when `config` is invalid.
    pub fn new(
        bot_delivery: Arc<dyn BotDeliveryPort>,
        bot_run_context: Arc<dyn BotRunContextPort>,
        config: WorkspaceTaskRuntimeConfig,
    ) -> Result<Self, &'static str> {
        config.validate()?;
        Ok(Self {
            bot_delivery,
            bot_run_context,
            config,
        })
    }

    /// Construct the production internal HTTP Provider transport.
    ///
    /// # Errors
    ///
    /// Returns the same configuration errors as [`Self::new`].
    pub fn with_internal_provider_transport(
        bot_run_context: Arc<dyn BotRunContextPort>,
        config: WorkspaceTaskRuntimeConfig,
    ) -> Result<Self, &'static str> {
        let bot_delivery = Arc::new(HttpProviderTransport::with_url_guard(
            workspace_provider_url_guard(),
        ));
        Self::new(bot_delivery, bot_run_context, config)
    }

    /// Deliver one immutable Task snapshot with its deterministic Provider run id.
    ///
    /// A terminal matching run context proves that a previous attempt was
    /// accepted, so a post-acceptance crash can be ACKed without another side
    /// effect. An open matching context is redelivered with the same request id;
    /// the Provider owns idempotent suppression at that boundary.
    ///
    /// # Errors
    ///
    /// Returns a stable conflict, deadline, rejection, or transport failure.
    pub async fn dispatch(
        &self,
        claim: &PublicWorkspaceTaskDispatchClaim,
    ) -> Result<(), WorkspaceTaskDeliveryError> {
        let run_id = claim.delivery_request_id.clone();
        let expected_context = BotRunContext {
            run_id: run_id.clone(),
            bot_id: claim.bot_uuid.clone(),
            group_id: claim.group_id.clone(),
            bcs_session_id: Some(claim.conversation_id.clone()),
            deadline_ms: bcs_protocol::now_ms()
                .checked_add(self.config.callback_timeout_ms)
                .ok_or(WorkspaceTaskDeliveryError::DeadlineOverflow)?,
            terminal: false,
        };
        if let Some(existing) = self.bot_run_context.get_context(&run_id).await {
            if existing.bot_id != expected_context.bot_id
                || existing.group_id != expected_context.group_id
                || existing.bcs_session_id != expected_context.bcs_session_id
            {
                return Err(WorkspaceTaskDeliveryError::RunContextConflict);
            }
            if existing.terminal {
                info!(
                    run_id,
                    task_id = %claim.task_id,
                    agent_id = %claim.agent_id,
                    "Workspace Task Provider delivery already completed"
                );
                return Ok(());
            }
        } else {
            self.bot_run_context.put_context(expected_context).await;
        }

        let result = self
            .bot_delivery
            .deliver(BotDeliveryCommand {
                target: BotDeliveryTarget::HttpProvider {
                    bot_id: claim.bot_uuid.clone(),
                    provider_id: WORKSPACE_PROVIDER_ID.to_string(),
                    provider_bot_ref: claim.agent_id.clone(),
                    webhook_url: self.config.webhook_url.clone(),
                    bcs_to_provider_token: RedactedToken::new(self.config.webhook_token.clone()),
                    protocol_version: "2.0".to_string(),
                },
                run_id: run_id.clone(),
                frame: task_frame(claim),
                delivery_kind: BotDeliveryKind::Inject,
                provider_transport: ProviderTransportPreference::Callback,
                provider_bypass_headers: Vec::new(),
            })
            .await
            .map_err(|_| {
                error!(
                    run_id,
                    task_id = %claim.task_id,
                    agent_id = %claim.agent_id,
                    "Workspace Task Provider delivery failed"
                );
                WorkspaceTaskDeliveryError::Delivery {
                    bot_id: claim.bot_uuid.clone(),
                }
            })?;
        if !result.delivered {
            error!(
                run_id,
                task_id = %claim.task_id,
                agent_id = %claim.agent_id,
                "Workspace Task Provider rejected delivery"
            );
            return Err(WorkspaceTaskDeliveryError::Rejected {
                bot_id: claim.bot_uuid.clone(),
            });
        }
        let _ = self.bot_run_context.mark_terminal(&run_id).await;
        info!(
            run_id,
            task_id = %claim.task_id,
            agent_id = %claim.agent_id,
            "Workspace Task Provider delivery accepted"
        );
        Ok(())
    }
}

/// Stable Task Provider delivery failure.
#[derive(Debug, Error)]
pub enum WorkspaceTaskDeliveryError {
    #[error("Workspace Task Provider run context conflicts with an existing delivery")]
    RunContextConflict,
    #[error("Workspace Task Provider callback deadline overflowed")]
    DeadlineOverflow,
    #[error("Workspace Task Provider rejected delivery for bot {bot_id}")]
    Rejected { bot_id: String },
    #[error("Workspace Task Provider delivery failed for bot {bot_id}")]
    Delivery { bot_id: String },
}

fn task_frame(claim: &PublicWorkspaceTaskDispatchClaim) -> BcsFrame {
    BcsFrame::Request(RequestFrame::new(
        claim.delivery_request_id.clone(),
        "chat.inject",
        Some(json!({
            "bcs_group_id": &claim.group_id,
            "bcs_session_id": &claim.conversation_id,
            "session_id": &claim.conversation_id,
            "message": task_message(claim),
            "extensions": {
                "tenant_id": &claim.tenant_id,
                "project_id": &claim.project_id,
                "workspace_id": &claim.workspace_id,
                "user_id": &claim.user_id,
                "task_id": &claim.task_id,
                "attempt_id": &claim.attempt_id,
                "plan_id": &claim.plan_id,
                "plan_node_id": &claim.plan_node_id,
                "conversation_id": &claim.conversation_id,
                "delivery_request_id": &claim.delivery_request_id,
            }
        })),
    ))
}

fn task_message(claim: &PublicWorkspaceTaskDispatchClaim) -> Value {
    let content = match claim.task_description.as_deref() {
        Some(description) if !description.trim().is_empty() => {
            format!("Workspace task: {}\n\n{}", claim.task_title, description)
        }
        _ => format!("Workspace task: {}", claim.task_title),
    };
    json!({"content": content})
}

fn workspace_provider_url_guard() -> OutboundUrlGuard {
    OutboundUrlGuard::new(false, true)
}
