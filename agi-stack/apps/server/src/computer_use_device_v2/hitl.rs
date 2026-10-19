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
}
fn consent_matches(output: &Value, pending_id: &str, session: &str, tool: &str) -> bool {
    output["error"] == "cua_permission_required"
        && output["request"]["request_id"] == pending_id
        && output["request"]["engine_session_id"] == session
        && output["request"]["session_id"]
            .as_str()
            .is_some_and(|id| !id.is_empty())
        && output["request"]["tool_name"] == tool
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
    let Some(request) = state.pending_hitl.as_ref().filter(|request| {
        request.kind == agistack_core::agent::types::HitlKind::Permission
            && request
                .decision
                .as_deref()
                .is_some_and(|decision| decision.target.kind == "computer_app")
    }) else {
        return Ok(None);
    };
    let decision = request
        .decision
        .as_deref()
        .filter(|decision| decision.is_complete())
        .ok_or_else(|| CoreError::Tool("computer_use_decision_incomplete".into()))?;
    let actual = {
        let requests = app
            .computer_use_devices
            .requests
            .lock()
            .expect("CUA requests");
        requests
            .values()
            .filter(|tool| {
                tool.owner == bound.owner
                    && tool.claim.run_id == bound.run.run_id
                    && tool.claim.conversation_id == conversation
                    && tool.claim.session_id == state.session_id
            })
            .find_map(|tool| {
                tool.result
                    .as_ref()
                    .and_then(|result| serde_json::from_str::<Value>(&result.output_json).ok())
                    .filter(|output| {
                        consent_matches(
                            output,
                            &decision.target.id,
                            &tool.claim.session_id,
                            &tool.claim.tool_name,
                        )
                    })
                    .map(|output| {
                        (
                            tool.claim.clone(),
                            output["request"].clone(),
                            output["scopes"].clone(),
                        )
                    })
            })
            .ok_or_else(|| CoreError::Tool("computer_use_pending_consent_not_bound".into()))?
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
    let metadata = json!({"hitl_type":"permission","decision":decision,"tool_name":actual.0.tool_name,"action":decision.action.name,"description":decision.data.summary,"risk_level":decision.risk.level,"allow_remember":scopes.iter().any(|scope| scope!="once"),"native_computer_use":{"schema_version":1,"owner":bound.owner,"run_id":bound.run.run_id,"session_id":state.session_id,"native_session_id":actual.1["session_id"],"device_id":actual.0.device_id,"message_id":message_id,"pending_request_id":decision.target.id}});
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
    bound.parked = true;
    let event = json!({"conversation_id":conversation,"message_id":message_id,"project_id":bound.owner.project_id,"request_id":request.id,"hitl_type":"permission","kind":"permission","question":request.prompt,"prompt":request.prompt,"decision":decision,"authority_revision":1,"created_at":chrono::Utc::now().to_rfc3339(),"expires_at":expires.to_rfc3339(),"answered":false});
    app.computer_use_devices
        .pending
        .lock()
        .expect("CUA pending decisions")
        .insert(
            request.id.clone(),
            Pending {
                owner: bound.owner.clone(),
                bound,
                engine,
                observer,
                session_id: state.session_id.clone(),
                conversation_id: conversation.into(),
                message_id: message_id.map(str::to_owned),
                goal: state.goal.clone(),
                scopes,
            },
        );
    Ok(Some(event))
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
                    _ => {}
                }
            }
            result => {
                let (event_type, data) = match result {
                    Ok(state) => (
                        agistack_core::agent::events::AgentEventType::Complete,
                        json!({"conversation_id":pending.conversation_id,"message_id":pending.message_id,"project_id":pending.owner.project_id,"answer":state.answer,"session":state}),
                    ),
                    Err(error) => (
                        agistack_core::agent::events::AgentEventType::Error,
                        json!({"conversation_id":pending.conversation_id,"error":error.to_string(),"is_error":true}),
                    ),
                };
                let _ =
                    crate::agent_ws::append_event(&app, &pending.conversation_id, event_type, data)
                        .await;
                super::finish(&app, pending.bound, &pending.conversation_id).await;
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
        assert_ne!(logical, physical);
        assert!(consent_matches(
            &output,
            pending,
            logical,
            "computer_get_app_state"
        ));
        assert!(!consent_matches(
            &output,
            pending,
            physical,
            "computer_get_app_state"
        ));
        assert!(!consent_matches(
            &output,
            pending,
            logical,
            "computer_click"
        ));
        assert!(!consent_matches(
            &output,
            "forged",
            logical,
            "computer_get_app_state"
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
