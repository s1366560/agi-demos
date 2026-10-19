//! The model supplies semantic decisions; the host validates persisted request identity.
use super::{Owner, PendingConsent, api::ManagementRequest, store};
use crate::local_runtime::{AuthenticatedContext, DesktopHitlRequest, LocalRuntimeState};
use agistack_core::agent::types::HitlKind;
use serde_json::{Value, json};

pub(super) struct Binding<'a> {
    pub owner: &'a Owner,
    pub conversation_id: &'a str,
    pub run_id: Option<&'a str>,
    pub engine_session_id: Option<&'a str>,
}

pub(super) fn resolve(
    state: &LocalRuntimeState,
    binding: Binding<'_>,
    kind: HitlKind,
    decision: Option<&agistack_core::agent::types::DecisionContext>,
) -> Result<Option<PendingConsent>, String> {
    let Some(decision) = decision.filter(|decision| decision.target.kind == "computer_app") else {
        return Ok(None);
    };
    if kind != HitlKind::Permission || !decision.is_complete() {
        return Err("cua_decision_required".into());
    }
    let pending = state
        .computer_use
        .pending
        .lock()
        .map_err(|_| "cua_runtime_unavailable")?
        .get(&decision.target.id)
        .cloned()
        .filter(|value| value.owner == *binding.owner)
        .ok_or("cua_request_expired")?;
    let session = state
        .computer_use
        .sessions
        .lock()
        .map_err(|_| "cua_runtime_unavailable")?
        .get(&pending.session_id)
        .cloned()
        .ok_or("cua_session_expired")?;
    if session.owner != *binding.owner
        || session.stopped.load(std::sync::atomic::Ordering::SeqCst)
        || session.context.conversation_id != binding.conversation_id
        || binding
            .run_id
            .is_some_and(|run| run != session.context.run_id)
        || binding
            .engine_session_id
            .is_some_and(|id| pending.engine_session_id.as_deref() != Some(id))
        || decision.action.name != pending.tool_name
        || !agistack_adapters_cua::tool_effects().contains_key(pending.tool_name.as_str())
        || !store::CAPABILITIES.contains(&pending.capability.as_str())
    {
        return Err("cua_scope_mismatch".into());
    }
    if let Some(child) = session.child.as_ref() {
        let run = state
            .session_store
            .run(&child.run_id)
            .map_err(|_| "cua_store_unavailable")?
            .ok_or("cua_child_scope_mismatch")?;
        if run.revision != child.revision
            || !state.subagent_controls.plugin_execution_current(
                &child.execution_id,
                binding.conversation_id,
                &run,
                &child.subagent_id,
                state.control_for_run(&run).as_ref(),
            )
        {
            return Err("cua_child_scope_mismatch".into());
        }
    }
    let db = state
        .session_store
        .connection()
        .map_err(|_| "cua_store_unavailable")?;
    let instance = store::instance(&db, binding.owner).map_err(|_| "cua_store_unavailable")?;
    if !instance.installed
        || !instance.enabled
        || instance.revision != session.revision
        || !store::pending_matches(&db, binding.owner, &pending.request_id, &json!(pending))
            .map_err(|_| "cua_store_unavailable")?
    {
        return Err("cua_request_expired".into());
    }
    Ok(Some(pending))
}

pub(in crate::local_runtime) fn validate_creation(
    state: &LocalRuntimeState,
    conversation_id: &str,
    run_id: Option<&str>,
    engine_session_id: &str,
    request: &agistack_core::agent::types::HitlRequest,
) -> Result<(), String> {
    if !request
        .decision
        .as_ref()
        .is_some_and(|decision| decision.target.kind == "computer_app")
    {
        return Ok(());
    }
    let conversation = state
        .session_store
        .conversation(conversation_id)?
        .ok_or("cua_scope_mismatch")?;
    let run = run_id
        .map(|id| state.session_store.run(id))
        .transpose()?
        .flatten();
    let identity = crate::local_runtime::knowledge_authority_v2::agent_access::PluginNativeIdentityV2::capture(
        state, &conversation, run.as_ref()).ok_or("cua_native_authority_required")?;
    let auth = identity.auth();
    let owner = Owner {
        user_id: auth.user.user_id.clone(),
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
        device_id: state.session_store.installation_id().into(),
    };
    resolve(
        state,
        Binding {
            owner: &owner,
            conversation_id,
            run_id: Some(run_id.unwrap_or(identity.message_id())),
            engine_session_id: Some(engine_session_id),
        },
        request.kind,
        request.decision.as_deref(),
    )
    .map(|_| ())
}

pub(in crate::local_runtime) fn is_permission(request: &DesktopHitlRequest) -> bool {
    request.kind == HitlKind::Permission
        && request
            .decision
            .as_ref()
            .is_some_and(|decision| decision.target.kind == "computer_app")
}
pub(in crate::local_runtime) fn prepare(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    request: &DesktopHitlRequest,
    response: &Value,
) -> Result<Option<(Owner, ManagementRequest)>, String> {
    if !is_permission(request) {
        return Ok(None);
    }
    let id = &request
        .decision
        .as_ref()
        .ok_or("cua_decision_required")?
        .target
        .id;
    let owner = Owner {
        user_id: auth.user.user_id.clone(),
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
        device_id: state.session_store.installation_id().into(),
    };
    let pending = resolve(
        state,
        Binding {
            owner: &owner,
            conversation_id: &request.conversation_id,
            run_id: request.run_id.as_deref(),
            engine_session_id: None,
        },
        request.kind,
        request.decision.as_ref(),
    )?
    .ok_or("cua_decision_required")?;
    let granted = response
        .get("granted")
        .and_then(Value::as_bool)
        .ok_or("cua_response_invalid")?;
    let action = response
        .get("action")
        .and_then(Value::as_str)
        .ok_or("cua_response_invalid")?;
    let scope = match response.get("scope").and_then(Value::as_str) {
        Some("once") => store::GrantScope::Once,
        Some("session") => store::GrantScope::Session,
        Some("always") => store::GrantScope::Always,
        _ => return Err("cua_scope_invalid".into()),
    };
    if !matches!((action, granted), ("allow", true) | ("deny", false)) {
        return Err("cua_response_invalid".into());
    }
    if granted && !super::consent::scopes(&pending.capability).contains(&scope) {
        return Err("cua_action_requires_once".into());
    }
    Ok(Some((
        owner,
        ManagementRequest {
            action: if granted { "grant" } else { "decline" }.into(),
            expected_revision: None,
            capability: None,
            enabled: None,
            request_id: Some(id.clone()),
            scope: Some(scope),
            grant_id: None,
            session_id: None,
            recording_id: None,
            artifact_id: None,
            offset: None,
            provider: None,
            client_id: None,
            account_id: None,
        },
    )))
}
