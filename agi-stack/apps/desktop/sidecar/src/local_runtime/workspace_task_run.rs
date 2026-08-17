//! Atomic Desktop authority projection for Workspace Task Provider deliveries.

use rusqlite::{params, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    authority_store::{
        insert_plan_version, insert_run, insert_run_event, is_recovered_unstarted_run,
        query_conversation, query_plan_version, DesktopExecutionEnvironment,
        DesktopPermissionProfile, DesktopPlanStatus, DesktopPlanVersion, DesktopRun,
        DesktopRunStatus,
    },
    session_store::DesktopSessionStore,
    ConversationCapabilityMode, ConversationRunMode, LlmRouteTarget, LocalConversation,
};

const REQUEST_CHANNEL: &str = "provider_send";
const AUTHORITY_SOURCE: &str = "workspace_task_dispatch";

#[derive(Debug)]
pub(super) struct ProjectWorkspaceTaskRunInput {
    pub(super) request_id: String,
    pub(super) request_hash: String,
    pub(super) request_payload: Value,
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) workspace_id: String,
    pub(super) user_id: String,
    pub(super) task_id: String,
    pub(super) attempt_id: String,
    pub(super) plan_id: Option<String>,
    pub(super) plan_node_id: Option<String>,
    pub(super) workspace_agent_binding_id: String,
    pub(super) agent_id: String,
    pub(super) conversation_id: String,
    pub(super) message: String,
    pub(super) llm_route: LlmRouteTarget,
    pub(super) environment: Option<DesktopExecutionEnvironment>,
    pub(super) now: String,
}

#[derive(Clone, Debug)]
pub(super) struct ProjectWorkspaceTaskRunOutcome {
    pub(super) run: DesktopRun,
    pub(super) response: Value,
}

#[derive(Clone, Debug)]
pub(super) struct RecoveredWorkspaceTaskRun {
    pub(super) request_payload: Value,
    pub(super) run: DesktopRun,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum ProjectWorkspaceTaskRunError {
    PayloadConflict,
    AuthorityConflict,
    AuthorityMissing,
    InvalidRequest,
    Storage(String),
}

impl DesktopSessionStore {
    /// Atomically create or verify every authority needed to execute one Task delivery.
    pub(super) fn project_workspace_task_run(
        &self,
        input: ProjectWorkspaceTaskRunInput,
    ) -> Result<ProjectWorkspaceTaskRunOutcome, ProjectWorkspaceTaskRunError> {
        validate_input(&input)?;
        let mut connection = self
            .connection()
            .map_err(ProjectWorkspaceTaskRunError::Storage)?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;

        if let Some((channel, request_hash, response_json)) = transaction
            .query_row(
                "SELECT channel, request_hash, response_json
                 FROM desktop_workspace_core_requests WHERE request_id = ?1",
                [input.request_id.as_str()],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                },
            )
            .optional()
            .map_err(storage)?
        {
            if channel != REQUEST_CHANNEL || request_hash != input.request_hash {
                return Err(ProjectWorkspaceTaskRunError::PayloadConflict);
            }
            let response = serde_json::from_str(&response_json).map_err(storage)?;
            let outcome = load_and_verify_projection(&transaction, &input, response)?;
            transaction.commit().map_err(storage)?;
            return Ok(outcome);
        }

        let run_id = input.request_id.clone();
        let plan_version_id = deterministic_id("workspace-task-plan", &input.request_id);
        let plan_task_id = deterministic_id("workspace-task-plan-step", &input.request_id);
        let decision_id = deterministic_id("workspace-task-decision", &input.request_id);

        let mut conversation = match query_conversation(&transaction, &input.conversation_id)
            .map_err(|error| storage(error.to_string()))?
        {
            Some(conversation) => {
                verify_conversation_scope(&conversation, &input)?;
                let concurrent_runs: i64 = transaction
                    .query_row(
                        "SELECT COUNT(*) FROM desktop_runs
                         WHERE conversation_id = ?1 AND id != ?2
                           AND status IN ('queued', 'running', 'needs_input', 'needs_approval',
                                          'paused', 'ready_review', 'disconnected', 'interrupted')",
                        params![input.conversation_id, run_id],
                        |row| row.get(0),
                    )
                    .map_err(storage)?;
                if concurrent_runs != 0 {
                    return Err(ProjectWorkspaceTaskRunError::AuthorityConflict);
                }
                conversation
            }
            None => LocalConversation {
                id: input.conversation_id.clone(),
                project_id: input.project_id.clone(),
                tenant_id: input.tenant_id.clone(),
                title: format!("Workspace Task {}", input.task_id),
                workspace_id: Some(input.workspace_id.clone()),
                capability_mode: ConversationCapabilityMode::Code,
                current_mode: ConversationRunMode::Build,
                created_at: input.now.clone(),
                updated_at: input.now.clone(),
            },
        };
        conversation.capability_mode = ConversationCapabilityMode::Code;
        conversation.current_mode = ConversationRunMode::Build;
        conversation.updated_at.clone_from(&input.now);
        upsert_conversation(&transaction, &conversation)?;
        project_llm_route(&transaction, &input)?;
        project_execution_selection(&transaction, &input)?;

        transaction
            .execute(
                "DELETE FROM desktop_agent_plan_tasks WHERE conversation_id = ?1",
                [input.conversation_id.as_str()],
            )
            .map_err(storage)?;
        let plan_task = json!({
            "id": plan_task_id,
            "conversation_id": input.conversation_id,
            "content": input.message,
            "status": "pending",
            "priority": "medium",
            "order_index": 0,
            "created_at": input.now,
            "updated_at": input.now,
            "workspace_task_id": input.task_id,
        });
        transaction
            .execute(
                "INSERT INTO desktop_agent_plan_tasks(id, conversation_id, position, value_json)
                 VALUES (?1, ?2, 0, ?3)",
                params![
                    plan_task_id,
                    input.conversation_id,
                    serde_json::to_string(&plan_task).map_err(storage)?,
                ],
            )
            .map_err(storage)?;
        let next_plan_version: i64 = transaction
            .query_row(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM desktop_plan_versions
                 WHERE conversation_id = ?1",
                [input.conversation_id.as_str()],
                |row| row.get(0),
            )
            .map_err(storage)?;
        let plan = DesktopPlanVersion {
            id: plan_version_id,
            conversation_id: input.conversation_id.clone(),
            version: next_plan_version,
            status: DesktopPlanStatus::Approved,
            tasks: vec![plan_task],
            created_at: input.now.clone(),
            approved_at: Some(input.now.clone()),
        };
        insert_plan_version(&transaction, &plan).map_err(storage)?;

        let authorization_snapshot = json!({
            "source": AUTHORITY_SOURCE,
            "tenant_id": input.tenant_id,
            "project_id": input.project_id,
            "workspace_id": input.workspace_id,
            "user_id": input.user_id,
            "task_id": input.task_id,
            "attempt_id": input.attempt_id,
            "plan_id": input.plan_id,
            "plan_node_id": input.plan_node_id,
            "workspace_agent_binding_id": input.workspace_agent_binding_id,
            "agent_id": input.agent_id,
            "conversation_id": input.conversation_id,
            "delivery_request_id": input.request_id,
            "provider_run_id": input.request_id,
            "provider_id": "memstack-workspace-agent-runtime",
            "llm_provider_id": input.llm_route.provider_id,
            "llm_model_id": input.llm_route.model_id,
            "request_hash": input.request_hash,
            "provider_request": input.request_payload,
            "approved_at": input.now,
            "mode": "build",
            "permission_profile": DesktopPermissionProfile::WorkspaceWrite,
            "environment": input.environment.clone(),
        });
        let run = DesktopRun {
            id: run_id,
            conversation_id: input.conversation_id.clone(),
            project_id: input.project_id.clone(),
            plan_version_id: plan.id.clone(),
            idempotency_key: format!("workspace-task-run:{}", input.request_id),
            message_id: input.request_id.clone(),
            request_message: input.message.clone(),
            status: DesktopRunStatus::Queued,
            revision: 1,
            created_at: input.now.clone(),
            updated_at: input.now.clone(),
            started_at: None,
            completed_at: None,
            last_heartbeat_at: None,
            error: None,
            environment: input.environment.clone(),
            permission_profile: DesktopPermissionProfile::WorkspaceWrite,
            authorization_snapshot,
        };
        insert_run(&transaction, &run).map_err(|error| storage(error.to_string()))?;
        insert_run_event(&transaction, &run, "queued", &input.now)
            .map_err(|error| storage(error.to_string()))?;

        let decision = json!({
            "id": decision_id,
            "conversation_id": input.conversation_id,
            "plan_version_id": plan.id,
            "run_id": run.id,
            "decision": "approved",
            "created_at": input.now,
            "authorization_snapshot": run.authorization_snapshot,
        });
        transaction
            .execute(
                "INSERT INTO desktop_decisions(
                   id, conversation_id, plan_version_id, run_id, decision, created_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, 'approved', ?5, ?6)",
                params![
                    decision_id,
                    input.conversation_id,
                    plan.id,
                    run.id,
                    input.now,
                    serde_json::to_string(&decision).map_err(storage)?,
                ],
            )
            .map_err(storage)?;

        let response = json!({"ok": true, "provider_run_id": run.id});
        transaction
            .execute(
                "INSERT INTO desktop_workspace_core_requests(
                   request_id, channel, request_hash, response_json, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    input.request_id,
                    REQUEST_CHANNEL,
                    input.request_hash,
                    serde_json::to_string(&response).map_err(storage)?,
                    input.now,
                ],
            )
            .map_err(storage)?;
        transaction.commit().map_err(storage)?;
        Ok(ProjectWorkspaceTaskRunOutcome { run, response })
    }

    /// Return only task-dispatch runs that crashed before their first launch.
    pub(super) fn recovered_workspace_task_runs(
        &self,
    ) -> Result<Vec<RecoveredWorkspaceTaskRun>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_runs
                 WHERE status = 'interrupted' ORDER BY created_at ASC, id ASC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        let mut recovered = Vec::new();
        for row in rows {
            let run: DesktopRun = serde_json::from_str(&row.map_err(|error| error.to_string())?)
                .map_err(|error| error.to_string())?;
            if run.authorization_snapshot["source"].as_str() != Some(AUTHORITY_SOURCE)
                || !is_recovered_unstarted_run(&run)
            {
                continue;
            }
            let request_payload = run.authorization_snapshot["provider_request"].clone();
            if !request_payload.is_object() {
                return Err("recovered Workspace Task request authority is missing".to_string());
            }
            recovered.push(RecoveredWorkspaceTaskRun {
                request_payload,
                run,
            });
        }
        Ok(recovered)
    }
}

fn validate_input(
    input: &ProjectWorkspaceTaskRunInput,
) -> Result<(), ProjectWorkspaceTaskRunError> {
    if [
        input.request_id.as_str(),
        input.request_hash.as_str(),
        input.tenant_id.as_str(),
        input.project_id.as_str(),
        input.workspace_id.as_str(),
        input.user_id.as_str(),
        input.task_id.as_str(),
        input.attempt_id.as_str(),
        input.workspace_agent_binding_id.as_str(),
        input.agent_id.as_str(),
        input.conversation_id.as_str(),
        input.message.as_str(),
        input.llm_route.provider_id.as_str(),
        input.llm_route.model_id.as_str(),
        input.now.as_str(),
    ]
    .iter()
    .any(|value| value.trim().is_empty())
        || !input.request_payload.is_object()
    {
        return Err(ProjectWorkspaceTaskRunError::InvalidRequest);
    }
    Ok(())
}

fn verify_conversation_scope(
    conversation: &LocalConversation,
    input: &ProjectWorkspaceTaskRunInput,
) -> Result<(), ProjectWorkspaceTaskRunError> {
    if conversation.id != input.conversation_id
        || conversation.tenant_id != input.tenant_id
        || conversation.project_id != input.project_id
        || conversation.workspace_id.as_deref() != Some(input.workspace_id.as_str())
    {
        return Err(ProjectWorkspaceTaskRunError::AuthorityConflict);
    }
    Ok(())
}

fn upsert_conversation(
    transaction: &Transaction<'_>,
    conversation: &LocalConversation,
) -> Result<(), ProjectWorkspaceTaskRunError> {
    let value_json = serde_json::to_string(conversation).map_err(storage)?;
    transaction
        .execute(
            "INSERT INTO desktop_conversations(id, project_id, workspace_id, updated_at, value_json)
             VALUES (?1, ?2, ?3, ?4, ?5)
             ON CONFLICT(id) DO UPDATE SET project_id = excluded.project_id,
               workspace_id = excluded.workspace_id, updated_at = excluded.updated_at,
               value_json = excluded.value_json",
            params![
                conversation.id,
                conversation.project_id,
                conversation.workspace_id,
                conversation.updated_at,
                value_json,
            ],
        )
        .map(|_| ())
        .map_err(storage)
}

fn project_llm_route(
    transaction: &Transaction<'_>,
    input: &ProjectWorkspaceTaskRunInput,
) -> Result<(), ProjectWorkspaceTaskRunError> {
    let existing = transaction
        .query_row(
            "SELECT provider_id, model_id FROM desktop_conversation_llm_routes
             WHERE conversation_id = ?1",
            [input.conversation_id.as_str()],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        )
        .optional()
        .map_err(storage)?;
    if existing.as_ref().is_some_and(|(provider_id, model_id)| {
        provider_id != &input.llm_route.provider_id || model_id != &input.llm_route.model_id
    }) {
        return Err(ProjectWorkspaceTaskRunError::AuthorityConflict);
    }
    if existing.is_none() {
        transaction
            .execute(
                "INSERT INTO desktop_conversation_llm_routes(
                   conversation_id, provider_id, model_id, created_at
                 ) VALUES (?1, ?2, ?3, ?4)",
                params![
                    input.conversation_id,
                    input.llm_route.provider_id,
                    input.llm_route.model_id,
                    input.now,
                ],
            )
            .map_err(storage)?;
    }
    Ok(())
}

fn project_execution_selection(
    transaction: &Transaction<'_>,
    input: &ProjectWorkspaceTaskRunInput,
) -> Result<(), ProjectWorkspaceTaskRunError> {
    let existing = transaction
        .query_row(
            "SELECT agent_id, forced_skill_id, subagent_id
             FROM desktop_conversation_execution_selections WHERE conversation_id = ?1",
            [input.conversation_id.as_str()],
            |row| {
                Ok((
                    row.get::<_, Option<String>>(0)?,
                    row.get::<_, Option<String>>(1)?,
                    row.get::<_, Option<String>>(2)?,
                ))
            },
        )
        .optional()
        .map_err(storage)?;
    if existing
        .as_ref()
        .is_some_and(|(agent_id, skill_id, subagent_id)| {
            agent_id.as_deref() != Some(input.agent_id.as_str())
                || skill_id.is_some()
                || subagent_id.is_some()
        })
    {
        return Err(ProjectWorkspaceTaskRunError::AuthorityConflict);
    }
    if existing.is_none() {
        transaction
            .execute(
                "INSERT INTO desktop_conversation_execution_selections(
                   conversation_id, agent_id, forced_skill_id, subagent_id, message_id, updated_at
                 ) VALUES (?1, ?2, NULL, NULL, ?3, ?4)",
                params![
                    input.conversation_id,
                    input.agent_id,
                    input.request_id,
                    input.now,
                ],
            )
            .map_err(storage)?;
    }
    Ok(())
}

fn load_and_verify_projection(
    transaction: &Transaction<'_>,
    input: &ProjectWorkspaceTaskRunInput,
    response: Value,
) -> Result<ProjectWorkspaceTaskRunOutcome, ProjectWorkspaceTaskRunError> {
    let run_id = response
        .get("provider_run_id")
        .and_then(Value::as_str)
        .ok_or(ProjectWorkspaceTaskRunError::AuthorityMissing)?;
    if run_id != input.request_id {
        return Err(ProjectWorkspaceTaskRunError::AuthorityConflict);
    }
    let run_json = transaction
        .query_row(
            "SELECT value_json FROM desktop_runs WHERE id = ?1",
            [run_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(storage)?
        .ok_or(ProjectWorkspaceTaskRunError::AuthorityMissing)?;
    let run: DesktopRun = serde_json::from_str(&run_json).map_err(storage)?;
    let conversation = query_conversation(transaction, &input.conversation_id)
        .map_err(|error| storage(error.to_string()))?
        .ok_or(ProjectWorkspaceTaskRunError::AuthorityMissing)?;
    let plan = query_plan_version(transaction, &run.plan_version_id)
        .map_err(|error| storage(error.to_string()))?
        .ok_or(ProjectWorkspaceTaskRunError::AuthorityMissing)?;
    verify_conversation_scope(&conversation, input)?;
    if conversation.current_mode != ConversationRunMode::Build
        || conversation.capability_mode != ConversationCapabilityMode::Code
        || plan.status != DesktopPlanStatus::Approved
        || run.id != input.request_id
        || run.conversation_id != input.conversation_id
        || run.project_id != input.project_id
        || run.plan_version_id != plan.id
        || run.request_message != input.message
        || run.message_id != input.request_id
        || run.permission_profile != DesktopPermissionProfile::WorkspaceWrite
        || run.authorization_snapshot["source"].as_str() != Some(AUTHORITY_SOURCE)
        || run.authorization_snapshot["task_id"].as_str() != Some(input.task_id.as_str())
        || run.authorization_snapshot["workspace_agent_binding_id"].as_str()
            != Some(input.workspace_agent_binding_id.as_str())
        || run.authorization_snapshot["agent_id"].as_str() != Some(input.agent_id.as_str())
        || run.authorization_snapshot["request_hash"].as_str() != Some(input.request_hash.as_str())
        || run.authorization_snapshot["provider_request"] != input.request_payload
        || run.authorization_snapshot["llm_provider_id"].as_str()
            != Some(input.llm_route.provider_id.as_str())
        || run.authorization_snapshot["llm_model_id"].as_str()
            != Some(input.llm_route.model_id.as_str())
    {
        return Err(ProjectWorkspaceTaskRunError::AuthorityConflict);
    }
    verify_llm_route(transaction, input)?;
    verify_execution_selection(transaction, input)?;
    Ok(ProjectWorkspaceTaskRunOutcome { run, response })
}

fn verify_llm_route(
    transaction: &Transaction<'_>,
    input: &ProjectWorkspaceTaskRunInput,
) -> Result<(), ProjectWorkspaceTaskRunError> {
    let route = transaction
        .query_row(
            "SELECT provider_id, model_id FROM desktop_conversation_llm_routes
             WHERE conversation_id = ?1",
            [input.conversation_id.as_str()],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        )
        .optional()
        .map_err(storage)?
        .ok_or(ProjectWorkspaceTaskRunError::AuthorityMissing)?;
    if route
        != (
            input.llm_route.provider_id.clone(),
            input.llm_route.model_id.clone(),
        )
    {
        return Err(ProjectWorkspaceTaskRunError::AuthorityConflict);
    }
    Ok(())
}

fn verify_execution_selection(
    transaction: &Transaction<'_>,
    input: &ProjectWorkspaceTaskRunInput,
) -> Result<(), ProjectWorkspaceTaskRunError> {
    let selection = transaction
        .query_row(
            "SELECT agent_id, forced_skill_id, subagent_id
             FROM desktop_conversation_execution_selections WHERE conversation_id = ?1",
            [input.conversation_id.as_str()],
            |row| {
                Ok((
                    row.get::<_, Option<String>>(0)?,
                    row.get::<_, Option<String>>(1)?,
                    row.get::<_, Option<String>>(2)?,
                ))
            },
        )
        .optional()
        .map_err(storage)?
        .ok_or(ProjectWorkspaceTaskRunError::AuthorityMissing)?;
    if selection.0.as_deref() != Some(input.agent_id.as_str())
        || selection.1.is_some()
        || selection.2.is_some()
    {
        return Err(ProjectWorkspaceTaskRunError::AuthorityConflict);
    }
    Ok(())
}

fn deterministic_id(kind: &str, request_id: &str) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("memstack-{kind}:{request_id}").as_bytes(),
    )
    .to_string()
}

fn storage(error: impl ToString) -> ProjectWorkspaceTaskRunError {
    ProjectWorkspaceTaskRunError::Storage(error.to_string())
}
