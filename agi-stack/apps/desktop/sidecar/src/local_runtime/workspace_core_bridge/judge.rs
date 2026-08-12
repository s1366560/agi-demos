use std::{sync::Arc, time::Instant};

use agistack_core::agent::types::AgentAction;
use axum::{extract::State, http::HeaderMap, Json};
use serde_json::{json, Value};

use super::{
    authorize, bad_request,
    contracts::{AutonomyJudgeRequest, ContextJudgeRequest, PlanJudgeRequest},
    ensure_workspace_scope,
    registry::{ensure_agent_available, ensure_project_scope},
    unavailable, BridgeResult, TokenKind,
};
use crate::local_runtime::{LlmWorkloadRole, LocalRuntimeState};

const JUDGE_AGENT_ID: &str = "builtin:all-access";
const CONTEXT_TOOL: &str = "judge_workspace_context";
const PLAN_TOOL: &str = "judge_workspace_plan";
const AUTONOMY_TOOL: &str = "judge_workspace_autonomy";

pub(super) async fn context(
    State(state): State<Arc<LocalRuntimeState>>,
    headers: HeaderMap,
    Json(request): Json<ContextJudgeRequest>,
) -> BridgeResult {
    authorize(&state, &headers, TokenKind::Registry)?;
    if request.user_id.trim().is_empty() || request.candidates.is_empty() {
        return Err(bad_request("Workspace Context judgment request is invalid"));
    }
    for candidate in &request.candidates {
        ensure_project_scope(&state, &candidate.tenant_id, &candidate.project_id)?;
    }
    let (tenant_id, project_id, workspace_id) = context_runtime_scope(&state, &request)?;
    ensure_agent_available(&state, &project_id, JUDGE_AGENT_ID)?;
    let input = serde_json::to_value(&request)
        .map_err(|_| unavailable("Workspace Context judge input is unavailable"))?;
    let schema = "Call judge_workspace_context exactly once with JSON fields: selected \
                  {tenant_id, project_id, membership_role}, rationale, evidence (string array).";
    let (output, latency_ms) = structured_judgment(
        &state,
        &tenant_id,
        &project_id,
        &workspace_id,
        CONTEXT_TOOL,
        schema,
        &input,
    )
    .await?;
    let selected = output
        .get("selected")
        .cloned()
        .ok_or_else(|| unavailable("Workspace Context judge omitted its selection"))?;
    let selected_candidate = serde_json::from_value(selected.clone())
        .map_err(|_| unavailable("Workspace Context judge selection is invalid"))?;
    if !request.candidates.contains(&selected_candidate) {
        return Err(unavailable(
            "Workspace Context judge selected an unauthorized candidate",
        ));
    }
    let rationale = required_string(&output, "rationale")?;
    let evidence = string_array(&output, "evidence")?;
    Ok(Json(json!({
        "selected": selected,
        "rationale": rationale,
        "evidence": evidence,
        "agent_id": JUDGE_AGENT_ID,
        "tool_name": CONTEXT_TOOL,
        "input_json": input,
        "output_json": output,
        "latency_ms": latency_ms
    })))
}

pub(super) async fn plan(
    State(state): State<Arc<LocalRuntimeState>>,
    headers: HeaderMap,
    Json(request): Json<PlanJudgeRequest>,
) -> BridgeResult {
    authorize(&state, &headers, TokenKind::Registry)?;
    ensure_workspace_scope(
        &state,
        &request.tenant_id,
        &request.project_id,
        &request.workspace_id,
    )?;
    validate_plan_request(&request)?;
    ensure_agent_available(&state, &request.project_id, JUDGE_AGENT_ID)?;
    let input = serde_json::to_value(&request)
        .map_err(|_| unavailable("Workspace Plan judge input is unavailable"))?;
    let schema = "Call judge_workspace_plan exactly once with JSON fields: proceed (boolean), \
                  selected_node_id (string or null), rationale (non-empty string).";
    let (output, latency_ms) = structured_judgment(
        &state,
        &request.tenant_id,
        &request.project_id,
        &request.workspace_id,
        PLAN_TOOL,
        schema,
        &input,
    )
    .await?;
    let proceed = output
        .get("proceed")
        .and_then(Value::as_bool)
        .ok_or_else(|| unavailable("Workspace Plan judge omitted its verdict"))?;
    let selected_node_id = optional_string(&output, "selected_node_id")?;
    if selected_node_id
        .as_ref()
        .is_some_and(|selected| !request.candidate_node_ids.contains(selected))
    {
        return Err(unavailable(
            "Workspace Plan judge selected an unauthorized node",
        ));
    }
    if request.kind == "select_pipeline_target" && proceed && selected_node_id.is_none() {
        return Err(unavailable(
            "Workspace Plan judge omitted its required target",
        ));
    }
    let rationale = required_string(&output, "rationale")?;
    Ok(Json(json!({
        "proceed": proceed,
        "selected_node_id": selected_node_id,
        "rationale": rationale,
        "agent_id": JUDGE_AGENT_ID,
        "tool_name": PLAN_TOOL,
        "input_json": input,
        "output_json": output,
        "latency_ms": latency_ms
    })))
}

pub(super) async fn autonomy(
    State(state): State<Arc<LocalRuntimeState>>,
    headers: HeaderMap,
    Json(request): Json<AutonomyJudgeRequest>,
) -> BridgeResult {
    authorize(&state, &headers, TokenKind::Registry)?;
    ensure_workspace_scope(
        &state,
        &request.tenant_id,
        &request.project_id,
        &request.workspace_id,
    )?;
    if request.actor_id.trim().is_empty() || request.candidates.is_empty() {
        return Err(bad_request(
            "Workspace Autonomy judgment request is invalid",
        ));
    }
    ensure_agent_available(&state, &request.project_id, JUDGE_AGENT_ID)?;
    let input = serde_json::to_value(&request)
        .map_err(|_| unavailable("Workspace Autonomy judge input is unavailable"))?;
    let schema = "Call judge_workspace_autonomy exactly once with JSON fields: verdict \
                  (continue, block, or escalate), selected_root_task_id (string or null), \
                  rationale (non-empty string).";
    let (output, latency_ms) = structured_judgment(
        &state,
        &request.tenant_id,
        &request.project_id,
        &request.workspace_id,
        AUTONOMY_TOOL,
        schema,
        &input,
    )
    .await?;
    let verdict = required_string(&output, "verdict")?;
    if !matches!(verdict.as_str(), "continue" | "block" | "escalate") {
        return Err(unavailable("Workspace Autonomy judge verdict is invalid"));
    }
    let selected_root_task_id = optional_string(&output, "selected_root_task_id")?;
    if selected_root_task_id.as_ref().is_some_and(|selected| {
        !request
            .candidates
            .iter()
            .any(|candidate| &candidate.root_task_id == selected)
    }) {
        return Err(unavailable(
            "Workspace Autonomy judge selected an unauthorized task",
        ));
    }
    if verdict == "continue" && selected_root_task_id.is_none() {
        return Err(unavailable(
            "Workspace Autonomy judge omitted its required root task",
        ));
    }
    let rationale = required_string(&output, "rationale")?;
    Ok(Json(json!({
        "verdict": verdict,
        "selected_root_task_id": selected_root_task_id,
        "rationale": rationale,
        "agent_id": JUDGE_AGENT_ID,
        "tool_name": AUTONOMY_TOOL,
        "input_json": input,
        "output_json": output,
        "latency_ms": latency_ms
    })))
}

async fn structured_judgment(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    tool_name: &str,
    schema: &str,
    input: &Value,
) -> Result<(Value, u64), super::BridgeError> {
    let prompt = format!(
        "You are an auditable Workspace judge. Base the verdict only on the supplied structured \
         request. {schema}\n\nStructured request:\n{input}"
    );
    let llm = state.llm_for_scope(
        tenant_id,
        project_id,
        workspace_id,
        LlmWorkloadRole::Default,
    );
    let started = Instant::now();
    let action = llm
        .decide(&prompt, 0, &[], &[tool_name.to_string()])
        .await
        .map_err(|_| unavailable("Workspace judge Agent is unavailable"))?;
    let latency_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    let AgentAction::CallTool { tool, input_json } = action else {
        return Err(unavailable(
            "Workspace judge did not return a structured tool call",
        ));
    };
    if tool != tool_name {
        return Err(unavailable(
            "Workspace judge returned an unauthorized tool call",
        ));
    }
    let output = serde_json::from_str::<Value>(&input_json)
        .map_err(|_| unavailable("Workspace judge tool output is invalid"))?;
    if !output.is_object() {
        return Err(unavailable("Workspace judge tool output must be an object"));
    }
    Ok((output, latency_ms))
}

fn context_runtime_scope(
    state: &LocalRuntimeState,
    request: &ContextJudgeRequest,
) -> Result<(String, String, String), super::BridgeError> {
    let scopes = request
        .current
        .iter()
        .map(|current| (&current.tenant_id, &current.project_id))
        .chain(
            request
                .candidates
                .iter()
                .map(|candidate| (&candidate.tenant_id, &candidate.project_id)),
        );
    for (tenant_id, project_id) in scopes {
        let workspace = state
            .session_store
            .list_workspaces(project_id)
            .map_err(super::store_error)?
            .into_iter()
            .find(|workspace| workspace["tenant_id"] == *tenant_id);
        if let Some(workspace_id) = workspace
            .as_ref()
            .and_then(|workspace| workspace.get("id"))
            .and_then(Value::as_str)
        {
            return Ok((
                tenant_id.clone(),
                project_id.clone(),
                workspace_id.to_string(),
            ));
        }
    }
    Err(unavailable(
        "Workspace Context judge has no configured Agent runtime scope",
    ))
}

fn validate_plan_request(request: &PlanJudgeRequest) -> Result<(), super::BridgeError> {
    const KINDS: [&str; 6] = [
        "recover_stale_attempts",
        "trigger_next_iteration",
        "select_pipeline_target",
        "regenerate_delivery_contract",
        "request_node_replan",
        "accept_node_review",
    ];
    if request.actor_id.trim().is_empty()
        || request.plan_id.trim().is_empty()
        || !KINDS.contains(&request.kind.as_str())
        || !request.evidence.is_object()
        || request
            .candidate_node_ids
            .iter()
            .any(|candidate| candidate.trim().is_empty())
    {
        Err(bad_request("Workspace Plan judgment request is invalid"))
    } else {
        Ok(())
    }
}

fn required_string(value: &Value, field: &str) -> Result<String, super::BridgeError> {
    value
        .get(field)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty() && value.len() <= 16_384)
        .map(ToString::to_string)
        .ok_or_else(|| unavailable("Workspace judge omitted required output"))
}

fn optional_string(value: &Value, field: &str) -> Result<Option<String>, super::BridgeError> {
    match value.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) if !value.trim().is_empty() && value.len() <= 512 => {
            Ok(Some(value.clone()))
        }
        _ => Err(unavailable("Workspace judge optional output is invalid")),
    }
}

fn string_array(value: &Value, field: &str) -> Result<Vec<String>, super::BridgeError> {
    let values = value
        .get(field)
        .and_then(Value::as_array)
        .ok_or_else(|| unavailable("Workspace judge evidence is invalid"))?;
    if values.len() > 128 {
        return Err(unavailable("Workspace judge evidence is too large"));
    }
    values
        .iter()
        .map(|value| {
            value
                .as_str()
                .filter(|value| !value.trim().is_empty() && value.len() <= 4096)
                .map(ToString::to_string)
                .ok_or_else(|| unavailable("Workspace judge evidence is invalid"))
        })
        .collect()
}
