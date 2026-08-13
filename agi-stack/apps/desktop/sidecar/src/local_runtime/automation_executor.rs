use std::{
    sync::{Arc, Weak},
    time::Instant,
};

use agistack_adapters_local_tools::LocalToolHost;
use agistack_core::{
    agent::{
        react::ReActEngine,
        types::{Role, SessionStatus},
    },
    ports::{CoreError, CoreResult, ToolHost},
};
use async_trait::async_trait;
use serde_json::{json, Value};

use super::{
    authority_store::DesktopHitlStatus,
    automation_dispatcher::{AutomationLedgerError, AutomationOperationClaim},
    automation_hitl::{reserve_authority, AutomationHitlAuthority},
    automation_worker::{
        AutomationExecutor, AutomationExecutorError, AutomationExecutorOutcome,
        AutomationWorkerExecution, AutomationWorkerWait,
    },
    now_iso, session_store, workspace_core_bridge, ConversationCapabilityMode, ConversationRunMode,
    LlmWorkloadRole, LocalConversation, LocalRuntimeState, LocalTimelineObserver,
    PLAN_MODE_TOOL_NAMES,
};

#[derive(Clone)]
struct ReadOnlyAutomationToolHost {
    inner: LocalToolHost,
}

impl ReadOnlyAutomationToolHost {
    fn new(inner: LocalToolHost) -> Self {
        Self { inner }
    }

    fn is_allowed(tool: &str) -> bool {
        PLAN_MODE_TOOL_NAMES.contains(&tool)
    }
}

#[async_trait]
impl ToolHost for ReadOnlyAutomationToolHost {
    fn list_tools(&self) -> Vec<String> {
        self.inner
            .list_tools()
            .into_iter()
            .filter(|tool| Self::is_allowed(tool))
            .collect()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        if !Self::is_allowed(tool) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' is outside local automation read authority"
            )));
        }
        self.inner.call(tool, input_json).await
    }
}

pub(super) struct LocalAutomationAgentExecutor {
    state: Weak<LocalRuntimeState>,
}

impl LocalAutomationAgentExecutor {
    pub(super) fn new(state: Weak<LocalRuntimeState>) -> Self {
        Self { state }
    }
}

#[async_trait]
impl AutomationExecutor for LocalAutomationAgentExecutor {
    async fn execute(
        &self,
        claim: &AutomationOperationClaim,
    ) -> Result<AutomationExecutorOutcome, AutomationExecutorError> {
        let state = self
            .state
            .upgrade()
            .ok_or_else(|| AutomationExecutorError::retryable("local_runtime_stopped"))?;
        validate_claim_scope(claim)?;
        let delivery_kind = snapshot_kind(&claim.job_snapshot, "delivery")?;
        match delivery_kind.as_str() {
            "none" | "announce" => {}
            "webhook" => {
                return Err(AutomationExecutorError::permanent(
                    "local_automation_webhook_delivery_unavailable",
                ));
            }
            _ => {
                return Err(AutomationExecutorError::permanent(
                    "local_automation_delivery_invalid",
                ));
            }
        }
        let goal = automation_goal(&claim.job_snapshot)?;
        let conversation = automation_conversation(&state, claim)
            .await
            .map_err(AutomationExecutorError::permanent)?;
        let workspace_id = conversation.workspace_id.as_deref().ok_or_else(|| {
            AutomationExecutorError::permanent("local_automation_workspace_unavailable")
        })?;
        if !state
            .automation_agent_authority_for_workspace(
                &claim.tenant_id,
                &claim.project_id,
                workspace_id,
            )
            .await
        {
            return Err(AutomationExecutorError::retryable(
                "local_automation_provider_unavailable",
            ));
        }

        let before_count = state
            .session_store
            .timeline_count(&conversation.id)
            .unwrap_or_default();
        let mut user_item = state.timeline_item(
            "user_message",
            conversation.id.clone(),
            Some(format!("local-automation-user-{}", claim.run_id)),
            Some("user"),
            Some(goal.clone()),
            json!({
                "automation_run_id": claim.run_id,
                "automation_job_id": claim.job_id,
                "automation_actor_user_id": claim.actor_user_id,
                "runtime_execution_id": claim.runtime_execution_id,
            }),
        );
        user_item["id"] = json!(format!("local-automation-trigger-{}", claim.run_id));
        state.append_timeline(&conversation.id, user_item);

        let engine = automation_engine(&state, &conversation)
            .await
            .map_err(AutomationExecutorError::retryable)?;
        let profile = state
            .execution_profile(&conversation)
            .map_err(|_| AutomationExecutorError::permanent("local_automation_profile_invalid"))?;
        let observer = Arc::new(LocalTimelineObserver::new(
            Arc::clone(&state),
            conversation.id.clone(),
            format!("local-automation-user-{}", claim.run_id),
            profile,
            goal.clone(),
        ));
        let started_at = Instant::now();
        let result = engine
            .run_observed(
                &claim.runtime_execution_id,
                &goal,
                Some(&claim.project_id),
                observer,
            )
            .await
            .map_err(|_| {
                AutomationExecutorError::retryable("local_automation_agent_execution_failed")
            })?;
        if result.status == SessionStatus::AwaitingInput {
            let pending = result.pending_hitl.as_ref().ok_or_else(|| {
                AutomationExecutorError::permanent("local_automation_hitl_authority_invalid")
            })?;
            reserve_authority(
                &state.session_store,
                claim,
                &conversation.id,
                &pending.id,
                &now_iso(),
            )
            .map_err(map_hitl_authority_error)?;
            let request = state
                .persist_pending_hitl(&conversation.id, None, &result)
                .map_err(|_| {
                    AutomationExecutorError::retryable("local_automation_hitl_persistence_failed")
                })?
                .ok_or_else(|| {
                    AutomationExecutorError::retryable(
                        "local_automation_hitl_authority_unavailable",
                    )
                })?;
            if request.id != pending.id
                || request.conversation_id != conversation.id
                || request.status != DesktopHitlStatus::Pending
            {
                return Err(AutomationExecutorError::permanent(
                    "local_automation_hitl_authority_invalid",
                ));
            }
            let after_count = state
                .session_store
                .timeline_count(&conversation.id)
                .unwrap_or(before_count);
            return Ok(AutomationExecutorOutcome::WaitingHuman(
                AutomationWorkerWait {
                    request_id: request.id.clone(),
                    result_summary: json!({
                        "authority": "local_scoped_agent",
                        "actor_user_id": claim.actor_user_id,
                        "runtime_execution_id": claim.runtime_execution_id,
                        "status": "waiting_human",
                        "hitl_request_id": request.id,
                        "hitl_type": request.kind,
                        "delivery": delivery_kind,
                    }),
                    event_count: after_count.saturating_sub(before_count) as u64,
                    execution_time_ms: u64::try_from(started_at.elapsed().as_millis())
                        .unwrap_or(u64::MAX),
                    conversation_id: conversation.id,
                },
            ));
        }
        if result.status != SessionStatus::Finished {
            let (code, retryable) = match result.status {
                SessionStatus::Failed | SessionStatus::Running | SessionStatus::Paused => {
                    ("local_automation_agent_execution_incomplete", true)
                }
                SessionStatus::Cancelled => ("local_automation_agent_execution_cancelled", false),
                SessionStatus::AwaitingInput => {
                    unreachable!("awaiting input status handled above")
                }
                SessionStatus::Finished => unreachable!("finished status handled above"),
            };
            return Err(if retryable {
                AutomationExecutorError::retryable(code)
            } else {
                AutomationExecutorError::permanent(code)
            });
        }
        let answer = result
            .answer
            .or_else(|| {
                result
                    .transcript
                    .iter()
                    .rev()
                    .find(|entry| entry.role == Role::Answer)
                    .map(|entry| entry.content.clone())
            })
            .unwrap_or_default();
        let after_count = state
            .session_store
            .timeline_count(&conversation.id)
            .unwrap_or(before_count);
        Ok(AutomationExecutorOutcome::Completed(
            AutomationWorkerExecution {
                result_summary: json!({
                    "authority": "local_scoped_agent",
                    "actor_user_id": claim.actor_user_id,
                    "runtime_execution_id": claim.runtime_execution_id,
                    "answer": answer,
                    "delivery": delivery_kind,
                }),
                event_count: after_count.saturating_sub(before_count) as u64,
                execution_time_ms: u64::try_from(started_at.elapsed().as_millis())
                    .unwrap_or(u64::MAX),
                conversation_id: conversation.id,
            },
        ))
    }

    async fn recover_answered_hitl(
        &self,
        authority: &AutomationHitlAuthority,
    ) -> Result<(), AutomationExecutorError> {
        let state = self
            .state
            .upgrade()
            .ok_or_else(|| AutomationExecutorError::retryable("local_runtime_stopped"))?;
        let answer = authority.response_answer.as_deref().ok_or_else(|| {
            AutomationExecutorError::permanent("local_automation_hitl_authority_invalid")
        })?;
        accept_human_response(&state, authority, &authority.request_id, answer)
            .await
            .map_err(AutomationExecutorError::retryable)
    }
}

fn map_hitl_authority_error(error: AutomationLedgerError) -> AutomationExecutorError {
    match error {
        AutomationLedgerError::Storage(_) => {
            AutomationExecutorError::retryable("local_automation_hitl_authority_store_unavailable")
        }
        AutomationLedgerError::LeaseLost => {
            AutomationExecutorError::retryable("local_automation_hitl_authority_lease_lost")
        }
        AutomationLedgerError::NotFound
        | AutomationLedgerError::RevisionConflict { .. }
        | AutomationLedgerError::IdempotencyConflict
        | AutomationLedgerError::InvalidRecord(_) => {
            AutomationExecutorError::permanent("local_automation_hitl_authority_conflict")
        }
    }
}

pub(super) async fn accept_human_response(
    state: &LocalRuntimeState,
    authority: &AutomationHitlAuthority,
    request_id: &str,
    answer: &str,
) -> Result<(), &'static str> {
    if authority.request_id != request_id {
        return Err("local_automation_hitl_request_mismatch");
    }
    let conversation = state
        .session_store
        .conversation(&authority.conversation_id)
        .map_err(|_| "local_automation_conversation_store_unavailable")?
        .ok_or("local_automation_conversation_not_found")?;
    if conversation.tenant_id != authority.tenant_id
        || conversation.project_id != authority.project_id
    {
        return Err("local_automation_conversation_scope_mismatch");
    }
    let workspace_id = conversation
        .workspace_id
        .as_deref()
        .ok_or("local_automation_workspace_unavailable")?;
    validate_workspace_scope(
        state,
        &authority.tenant_id,
        &authority.project_id,
        workspace_id,
    )
    .await?;
    let engine = automation_engine(state, &conversation).await?;
    let accepted = engine
        .accept_human_response(&authority.runtime_execution_id, request_id, answer)
        .await
        .map_err(|_| "local_automation_hitl_checkpoint_rejected")?;
    let pending_matches = accepted
        .pending_hitl
        .as_ref()
        .is_some_and(|request| request.id == request_id);
    if accepted.session_id != authority.runtime_execution_id
        || accepted.project_id.as_deref() != Some(authority.project_id.as_str())
        || accepted.status != SessionStatus::Running
        || !pending_matches
        || accepted.hitl_answer(request_id) != Some(answer)
    {
        return Err("local_automation_hitl_checkpoint_mismatch");
    }
    Ok(())
}

async fn automation_engine(
    state: &LocalRuntimeState,
    conversation: &LocalConversation,
) -> Result<ReActEngine, &'static str> {
    let tool_host: Arc<dyn ToolHost> = Arc::new(ReadOnlyAutomationToolHost::new(
        state.tool_host.lock().expect("local tool host").clone(),
    ));
    let llm = state
        .llm_for_role(conversation, LlmWorkloadRole::Default)
        .await
        .map_err(|_| "local_automation_workspace_core_unavailable")?;
    Ok(ReActEngine::new(
        llm,
        tool_host,
        state.checkpoints.clone(),
        state.clock.clone(),
    )
    .with_max_rounds(8))
}

pub(super) async fn execution_workspace_id(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    job_snapshot: &Value,
    command_conversation_id: Option<&str>,
) -> Result<String, &'static str> {
    let configured_conversation_id = command_conversation_id
        .or_else(|| job_snapshot.get("conversation_id").and_then(Value::as_str))
        .map(str::trim)
        .filter(|value| !value.is_empty());
    if let Some(conversation_id) = configured_conversation_id {
        let conversation = state
            .session_store
            .conversation(conversation_id)
            .map_err(|_| "local_automation_conversation_store_unavailable")?
            .ok_or("local_automation_conversation_not_found")?;
        if conversation.tenant_id != tenant_id || conversation.project_id != project_id {
            return Err("local_automation_conversation_scope_mismatch");
        }
        let workspace_id = conversation
            .workspace_id
            .as_deref()
            .ok_or("local_automation_workspace_unavailable")?;
        validate_workspace_scope(state, tenant_id, project_id, workspace_id).await?;
        return Ok(workspace_id.to_string());
    }

    let workspace_id = job_snapshot
        .get("workspace_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or("local_automation_workspace_required")?;
    validate_workspace_scope(state, tenant_id, project_id, workspace_id).await?;
    Ok(workspace_id.to_string())
}

pub(super) async fn validate_workspace_scope(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<(), &'static str> {
    #[cfg(test)]
    if state
        .mock_llm_enabled
        .load(std::sync::atomic::Ordering::Acquire)
        != 0
    {
        return Ok(());
    }
    workspace_core_bridge::validate_workspace_scope(state, tenant_id, project_id, workspace_id)
        .await
}

fn validate_claim_scope(claim: &AutomationOperationClaim) -> Result<(), AutomationExecutorError> {
    let project_id = session_store::required_string(&claim.job_snapshot, "project_id")
        .map_err(|_| AutomationExecutorError::permanent("local_automation_job_snapshot_invalid"))?;
    let tenant_id = session_store::required_string(&claim.job_snapshot, "tenant_id")
        .map_err(|_| AutomationExecutorError::permanent("local_automation_job_snapshot_invalid"))?;
    let job_id = session_store::required_string(&claim.job_snapshot, "id")
        .map_err(|_| AutomationExecutorError::permanent("local_automation_job_snapshot_invalid"))?;
    if project_id != claim.project_id || tenant_id != claim.tenant_id || job_id != claim.job_id {
        return Err(AutomationExecutorError::permanent(
            "local_automation_job_scope_mismatch",
        ));
    }
    Ok(())
}

fn snapshot_kind(snapshot: &Value, field: &str) -> Result<String, AutomationExecutorError> {
    snapshot
        .get(field)
        .and_then(|value| value.get("kind"))
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(ToString::to_string)
        .ok_or_else(|| AutomationExecutorError::permanent("local_automation_job_snapshot_invalid"))
}

fn automation_goal(snapshot: &Value) -> Result<String, AutomationExecutorError> {
    let payload = snapshot.get("payload").ok_or_else(|| {
        AutomationExecutorError::permanent("local_automation_job_snapshot_invalid")
    })?;
    let kind = payload
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let config = payload
        .get("config")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            AutomationExecutorError::permanent("local_automation_job_snapshot_invalid")
        })?;
    let (field, prefix) = match kind {
        "agent_turn" => ("message", None),
        "system_event" => ("content", Some("[System Event] ")),
        _ => {
            return Err(AutomationExecutorError::permanent(
                "local_automation_payload_unsupported",
            ));
        }
    };
    let content = config
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| AutomationExecutorError::permanent("local_automation_payload_invalid"))?;
    Ok(format!("{}{content}", prefix.unwrap_or_default()))
}

async fn automation_conversation(
    state: &LocalRuntimeState,
    claim: &AutomationOperationClaim,
) -> Result<LocalConversation, &'static str> {
    let mode = claim
        .job_snapshot
        .get("conversation_mode")
        .and_then(Value::as_str)
        .unwrap_or("fresh");
    if !matches!(mode, "fresh" | "reuse") {
        return Err("local_automation_conversation_mode_invalid");
    }
    let configured_id = claim
        .conversation_id
        .as_deref()
        .or_else(|| {
            claim
                .job_snapshot
                .get("conversation_id")
                .and_then(Value::as_str)
        })
        .map(str::trim)
        .filter(|value| !value.is_empty());
    if mode == "reuse" && configured_id.is_none() {
        return Err("local_automation_reuse_conversation_required");
    }
    if let Some(conversation_id) = configured_id {
        let existing = state
            .session_store
            .conversation(conversation_id)
            .map_err(|_| "local_automation_conversation_store_unavailable")?
            .ok_or("local_automation_conversation_not_found")?;
        if existing.project_id != claim.project_id || existing.tenant_id != claim.tenant_id {
            return Err("local_automation_conversation_scope_mismatch");
        }
        let workspace_id = existing
            .workspace_id
            .as_deref()
            .ok_or("local_automation_workspace_unavailable")?;
        validate_workspace_scope(state, &claim.tenant_id, &claim.project_id, workspace_id).await?;
        return Ok(existing);
    }

    let workspace_id = execution_workspace_id(
        state,
        &claim.tenant_id,
        &claim.project_id,
        &claim.job_snapshot,
        None,
    )
    .await?;
    let now = now_iso();
    let title = claim
        .job_snapshot
        .get("name")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("Local automation");
    let conversation = LocalConversation {
        id: format!("local-automation-conversation-{}", claim.run_id),
        project_id: claim.project_id.clone(),
        tenant_id: claim.tenant_id.clone(),
        title: title.to_string(),
        workspace_id: Some(workspace_id),
        capability_mode: ConversationCapabilityMode::Work,
        current_mode: ConversationRunMode::Plan,
        created_at: now.clone(),
        updated_at: now,
    };
    state
        .session_store
        .insert_conversation(&conversation)
        .map_err(|_| "local_automation_conversation_store_unavailable")?;
    Ok(conversation)
}
