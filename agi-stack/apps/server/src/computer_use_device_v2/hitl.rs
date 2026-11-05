//! Persisted Computer Use decisions retain their device session across model suspension.
use super::*;
use agistack_adapters_postgres::{NewHitlRequestRecord, PgHitlRequestRepository};
use agistack_core::{
    agent::{ReActObserver, SessionState, SessionStatus},
    ReActEngine,
};
pub(super) struct Pending {
    owner: Owner,
    bound: BoundRun,
    engine: Arc<ReActEngine>,
    observer: Arc<dyn ReActObserver>,
    session_id: String,
    conversation_id: String,
    message_id: Option<String>,
    goal: String,
    scopes: Vec<String>,
    execution_step: Option<Value>,
    outer_permission: Option<Value>,
}
fn consent_matches(
    permission: &agistack_core::ports::PermissionRequired,
    pending_id: &str,
    session: &str,
    tool: &str,
    action: &str,
) -> bool {
    use agistack_core::ports::PermissionKind;
    let output = permission.demand();
    let binding = permission.binding();
    let source_matches = match permission.kind() {
        PermissionKind::NativeConsent => {
            tool == binding.tool_name || (tool == "cua_repl_js" && binding.cell_id.is_some())
        }
        PermissionKind::CloudExecutionStep => {
            tool == "cua_repl_js" && output["request"]["capability"] == "execution_step"
        }
        PermissionKind::ServerMcpTool => {
            tool == binding.tool_name && output["request"]["capability"] == "mcp_tool"
        }
        _ => false,
    };
    source_matches
        && binding.engine_session_id.as_deref() == Some(session)
        && binding.tool_name == action
        && output["error"] == "cua_permission_required"
        && output["request"]["request_id"] == pending_id
        && output["request"]["engine_session_id"] == session
        && output["request"]["tool_name"] == action
        && output["request"]["session_id"]
            .as_str()
            .is_some_and(|id| !id.is_empty())
}
pub(crate) async fn park(
    app: &AppState,
    mut bound: BoundRun,
    engine: Arc<ReActEngine>,
    observer: Arc<dyn ReActObserver>,
    state: &SessionState,
    conversation: &str,
    message_id: Option<&str>,
) -> CoreResult<Option<Value>> {
    let prepared = match prepare_park(app, &bound, state, conversation, message_id).await {
        Ok(prepared) => prepared,
        Err(error) => {
            super::cancellation::fail_bound(app, bound, "computer_use_human_request_not_parked")
                .await?;
            return Err(error);
        }
    };
    bound.parked = true;
    app.computer_use_devices
        .pending
        .lock()
        .expect("CUA pending decisions")
        .insert(
            prepared.request_id,
            Pending {
                owner: bound.owner.clone(),
                bound,
                engine,
                observer,
                session_id: state.session_id.clone(),
                conversation_id: conversation.into(),
                message_id: message_id.map(str::to_owned),
                goal: state.goal.clone(),
                scopes: prepared.scopes,
                execution_step: prepared.execution_step,
                outer_permission: prepared.outer_permission,
            },
        );
    Ok(Some(prepared.event))
}
struct PreparedDecision {
    request_id: String,
    scopes: Vec<String>,
    execution_step: Option<Value>,
    outer_permission: Option<Value>,
    event: Value,
}
async fn prepare_park(
    app: &AppState,
    bound: &BoundRun,
    state: &SessionState,
    conversation: &str,
    message_id: Option<&str>,
) -> CoreResult<PreparedDecision> {
    let request = state
        .pending_hitl
        .as_ref()
        .ok_or_else(|| CoreError::Tool("computer_use_human_request_unsupported".into()))?;
    let actual = matching_permission(
        &app.computer_use_devices,
        &bound.owner,
        &bound.run,
        conversation,
        &state.session_id,
        request,
    )?;
    app.computer_use_devices
        .authority
        .as_ref()
        .ok_or_else(|| CoreError::Tool("computer_use_authority_unavailable".into()))?
        .recheck_running(&bound.owner, conversation, &bound.run)
        .await?;
    let decision = request
        .decision
        .as_deref()
        .expect("validated complete decision");
    if actual.3.kind() != agistack_core::ports::PermissionKind::ServerMcpTool {
        app.computer_use_devices
            .validate_permission_claim(
                &actual.0,
                &permission::WirePermission {
                    kind: actual.3.kind(),
                    binding: actual.3.binding().clone(),
                    demand: actual.3.demand().clone(),
                },
            )
            .await?;
    }
    let execution_step = if actual.1["capability"] == "execution_step" {
        if actual.2 != json!(["once"]) {
            return Err(CoreError::Tool("computer_use_step_scopes_invalid".into()));
        }
        Some(
            app.computer_use_devices
                .verify_pending_step(&actual.0, &actual.1)
                .await?,
        )
    } else {
        None
    };
    let outer_permission = if actual.1["capability"] == "mcp_tool" {
        if decision.target.kind != "device_mcp_tool" {
            return Err(CoreError::Tool(
                "computer_use_permission_target_invalid".into(),
            ));
        }
        if actual.2 != json!(["once"]) {
            return Err(CoreError::Tool(
                "computer_use_permission_scopes_invalid".into(),
            ));
        }
        Some(
            app.computer_use_devices
                .verify_pending_outer(&actual.0, &actual.1)
                .await?,
        )
    } else {
        None
    };
    let pool = app
        .worker_postgres
        .clone()
        .ok_or_else(|| CoreError::Storage("computer_use_hitl_storage_unavailable".into()))?;
    let expires = chrono::Utc::now() + chrono::Duration::minutes(30);
    let scopes: Vec<String> = serde_json::from_value(actual.2)
        .map_err(|_| CoreError::Tool("computer_use_consent_scopes_invalid".into()))?;
    if scopes.is_empty()
        || scopes
            .iter()
            .any(|scope| !matches!(scope.as_str(), "once" | "session" | "always"))
    {
        return Err(CoreError::Tool(
            "computer_use_consent_scopes_invalid".into(),
        ));
    }
    let metadata = json!({"execution_step":execution_step,"hitl_type":"permission","decision":decision,"tool_name":actual.0.tool_name,"action":decision.action.name,"description":decision.data.summary,"risk_level":decision.risk.level,"allow_remember":scopes.iter().any(|scope| scope!="once"),"native_computer_use":{"schema_version":1,"owner":bound.owner,"run_id":bound.run.run_id,"session_id":state.session_id,"native_session_id":actual.1["session_id"],"device_id":actual.0.device_id,"message_id":message_id,"pending_request_id":decision.target.id}});
    PgHitlRequestRepository::new(pool)
        .insert_pending(&NewHitlRequestRecord {
            id: request.id.clone(),
            request_type: "permission".into(),
            conversation_id: conversation.into(),
            message_id: message_id.map(str::to_owned),
            tenant_id: bound.owner.tenant_id.clone(),
            project_id: bound.owner.project_id.clone(),
            user_id: Some(bound.owner.user_id.clone()),
            question: request.prompt.clone(),
            options: None,
            context: Some(json!({"decision":decision})),
            request_metadata: Some(metadata),
            expires_at: expires,
        })
        .await?;
    let event = json!({"conversation_id":conversation,"message_id":message_id,"project_id":bound.owner.project_id,"request_id":request.id,"hitl_type":"permission","kind":"permission","question":request.prompt,"prompt":request.prompt,"decision":decision,"authority_revision":1,"created_at":chrono::Utc::now().to_rfc3339(),"expires_at":expires.to_rfc3339(),"answered":false});
    Ok(PreparedDecision {
        request_id: request.id.clone(),
        scopes,
        execution_step,
        outer_permission,
        event,
    })
}

pub(super) fn matching_permission(
    broker: &Broker,
    owner: &Owner,
    run: &authority::RunAuthority,
    conversation: &str,
    session: &str,
    request: &agistack_core::HitlRequest,
) -> CoreResult<(
    broker::Claim,
    Value,
    Value,
    agistack_core::ports::PermissionRequired,
)> {
    if request.kind != agistack_core::HitlKind::Permission {
        return Err(CoreError::Tool(
            "computer_use_human_request_unsupported".into(),
        ));
    }
    let decision = request
        .decision
        .as_deref()
        .filter(|decision| decision.is_complete())
        .ok_or_else(|| CoreError::Tool("computer_use_decision_incomplete".into()))?;
    if !matches!(
        decision.target.kind.as_str(),
        "computer_app" | "device_mcp_tool"
    ) {
        return Err(CoreError::Tool(
            "computer_use_permission_target_invalid".into(),
        ));
    }
    let requests = broker.requests.lock().expect("CUA requests");
    requests
        .values()
        .filter(|tool| {
            tool.owner == *owner
                && tool.run == *run
                && tool.claim.conversation_id == conversation
                && tool.claim.session_id == session
                && tool.status == "completed"
                && !tool.cancelled
                && !tool.failed
        })
        .find_map(|tool| {
            tool.result
                .as_ref()
                .and_then(|result| result.permission_required.as_ref())
                .filter(|permission| {
                    let expected_kind = if permission.kind()
                        == agistack_core::ports::PermissionKind::ServerMcpTool
                    {
                        "device_mcp_tool"
                    } else {
                        "computer_app"
                    };
                    decision.target.kind == expected_kind
                        && consent_matches(
                            permission,
                            &decision.target.id,
                            session,
                            &tool.claim.tool_name,
                            &decision.action.name,
                        )
                })
                .map(|permission| {
                    (
                        tool.claim.clone(),
                        permission.demand()["request"].clone(),
                        permission.demand()["scopes"].clone(),
                        permission.clone(),
                    )
                })
        })
        .ok_or_else(|| CoreError::Tool("computer_use_permission_target_invalid".into()))
}

pub(super) fn cancel_run(broker: &Broker, owner: &Owner, run_id: &str) {
    let cancelled = {
        let mut pending = broker.pending.lock().expect("CUA pending decisions");
        let ids: Vec<_> = pending
            .iter()
            .filter(|(_, item)| item.owner == *owner && item.bound.run.run_id == run_id)
            .map(|(id, _)| id.clone())
            .collect();
        ids.into_iter()
            .filter_map(|id| pending.remove(&id))
            .collect::<Vec<_>>()
    };
    for mut item in cancelled {
        item.bound.parked = false;
        // Drop after releasing the pending lock; BoundRun revokes its exact broker run.
        drop(item);
    }
}

pub(crate) async fn resume(
    app: &AppState,
    user: &str,
    request: &crate::hitl_api::HitlResponsePayload,
) -> CoreResult<bool> {
    let pending = {
        let mut pending = app
            .computer_use_devices
            .pending
            .lock()
            .expect("CUA pending decisions");
        if pending
            .get(&request.request_id)
            .is_some_and(|pending| pending.owner.user_id != user)
        {
            return Err(CoreError::Tool("computer_use_hitl_scope_denied".into()));
        }
        pending.remove(&request.request_id)
    };
    let Some(mut pending) = pending else {
        return Ok(false);
    };
    // Once removed, any validation failure must release the original native run.
    pending.bound.parked = false;
    if request.hitl_type != "permission"
        || request.response_data["granted"] == true
            && !request.response_data["scope"]
                .as_str()
                .is_some_and(|scope| pending.scopes.iter().any(|allowed| allowed == scope))
        || !matches!(
            (
                request.response_data["action"].as_str(),
                request.response_data["granted"].as_bool(),
                request.response_data["scope"].as_str()
            ),
            (
                Some("allow"),
                Some(true),
                Some("once" | "session" | "always")
            ) | (Some("deny"), Some(false), Some("once"))
        )
    {
        pending.bound.parked = false;
        return Err(CoreError::Tool("computer_use_hitl_response_invalid".into()));
    }
    app.computer_use_devices
        .authority
        .as_ref()
        .ok_or_else(|| CoreError::Tool("computer_use_authority_unavailable".into()))?
        .recheck(&pending.owner, &pending.conversation_id, &pending.bound.run)
        .await?;
    if let Some(step) = &pending.execution_step {
        // hitl_api has already committed the bound human response before this resume hook.
        app.computer_use_devices
            .resolve_step_permission(
                step,
                request.response_data["granted"] == true,
                &request.request_id,
            )
            .await?;
    }
    if let Some(permission) = &pending.outer_permission {
        app.computer_use_devices
            .resolve_outer_permission(
                permission,
                request.response_data["granted"] == true,
                &request.request_id,
            )
            .await?;
    }
    pending
        .engine
        .accept_human_response(
            &pending.session_id,
            &request.request_id,
            &request.response_data.to_string(),
        )
        .await?;
    pending.bound.parked = false;
    let app = app.clone();
    tokio::spawn(async move {
        let result = pending
            .engine
            .run_observed(
                &pending.session_id,
                &pending.goal,
                Some(&pending.owner.project_id),
                pending.observer.clone(),
            )
            .await;
        match result {
            Ok(state) if state.status == SessionStatus::AwaitingInput => {
                match park(
                    &app,
                    pending.bound,
                    pending.engine,
                    pending.observer,
                    &state,
                    &pending.conversation_id,
                    pending.message_id.as_deref(),
                )
                .await
                {
                    Ok(Some(event)) => {
                        let _ = crate::agent_ws::append_event(
                            &app,
                            &pending.conversation_id,
                            agistack_core::agent::events::AgentEventType::PermissionAsked,
                            event,
                        )
                        .await;
                    }
                    Err(_) | Ok(None) => {
                        let _ = crate::agent_ws::append_event(&app, &pending.conversation_id,
                            agistack_core::agent::events::AgentEventType::Error,
                            json!({"conversation_id":pending.conversation_id,"error":"computer_use_human_request_not_parked","is_error":true})).await;
                    }
                }
            }
            result => {
                let failed = result
                    .as_ref()
                    .map_or(true, |state| state.status != SessionStatus::Finished);
                let (event_type, data) = match result {
                    Ok(state) if state.status == SessionStatus::Finished => (
                        agistack_core::agent::events::AgentEventType::Complete,
                        json!({"conversation_id":pending.conversation_id,"message_id":pending.message_id,"project_id":pending.owner.project_id,"answer":state.answer,"session":state}),
                    ),
                    Ok(state) => (
                        agistack_core::agent::events::AgentEventType::Error,
                        json!({"conversation_id":pending.conversation_id,"error":"agent_run_failed","is_error":true,"session":state}),
                    ),
                    Err(error) => (
                        agistack_core::agent::events::AgentEventType::Error,
                        json!({"conversation_id":pending.conversation_id,"error":error.to_string(),"is_error":true}),
                    ),
                };
                let _ =
                    crate::agent_ws::append_event(&app, &pending.conversation_id, event_type, data)
                        .await;
                if failed {
                    let _ =
                        super::cancellation::fail_bound(&app, pending.bound, "agent_run_failed")
                            .await;
                } else {
                    super::finish(&app, pending.bound, &pending.conversation_id).await;
                }
            }
        }
    });
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_sidecar_wire_binds_logical_engine_and_distinct_physical_native_session() {
        let output: Value = serde_json::from_str(include_str!(
            "../../../../../shared/fixtures/computer-use-cloud-consent.json"
        ))
        .unwrap();
        let pending = output["request"]["request_id"].as_str().unwrap();
        let logical = output["request"]["engine_session_id"].as_str().unwrap();
        let physical = output["request"]["session_id"].as_str().unwrap();
        let permission = agistack_core::ports::PermissionRequired::new(
            agistack_core::ports::PermissionKind::NativeConsent,
            agistack_core::ports::PermissionBinding {
                tool_name: "computer_get_app_state".into(),
                input_digest: "fixture".into(),
                engine_session_id: Some(logical.into()),
                cell_id: None,
                step_id: None,
            },
            output.clone(),
        );
        assert_ne!(logical, physical);
        assert!(consent_matches(
            &permission,
            pending,
            logical,
            "computer_get_app_state",
            "computer_get_app_state"
        ));
        assert!(!consent_matches(
            &permission,
            pending,
            physical,
            "computer_get_app_state",
            "computer_get_app_state"
        ));
        assert!(!consent_matches(
            &permission,
            pending,
            logical,
            "computer_click",
            "computer_click"
        ));
        assert!(!consent_matches(
            &permission,
            "forged",
            logical,
            "computer_get_app_state",
            "computer_get_app_state"
        ));
        assert!(!consent_matches(
            &permission,
            pending,
            logical,
            "computer_get_app_state",
            "different_action"
        ));
        assert!(
            output["request"].get("owner").is_none(),
            "owner comes from authenticated broker, not native payload"
        );
    }
}
pub(crate) async fn native_receipt(app: &AppState, request_id: &str) -> CoreResult<Value> {
    let pool = app
        .worker_postgres
        .clone()
        .ok_or_else(|| CoreError::Storage("computer_use_hitl_storage_unavailable".into()))?;
    let authority = PgHitlRequestRepository::new(pool)
        .get_authority_state(request_id)
        .await?
        .ok_or(CoreError::NotFound)?;
    Ok(
        json!({"success":true,"message":"HITL response received","status":"answered","duplicate":false,"request_id":request_id,"authority_revision":2,"authority_status":"answered","created_at":authority.created_at.to_rfc3339(),"answered_at":authority.answered_at.map(|time|time.to_rfc3339()),"expires_at":authority.expires_at.map(|time|time.to_rfc3339()),"observed_at":chrono::Utc::now().to_rfc3339()}),
    )
}
