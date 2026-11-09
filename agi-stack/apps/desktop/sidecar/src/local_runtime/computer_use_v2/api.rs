//! Device management stays local in both local and cloud conversation modes.
use super::{denials, store, Owner};
use crate::local_runtime::{AuthenticatedContext, LocalRuntimeState};
use axum::{
    extract::{Extension, Path, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::Arc;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ManagementRequest {
    pub action: String,
    pub expected_revision: Option<u64>,
    pub capability: Option<String>,
    pub enabled: Option<bool>,
    pub input_mode: Option<agistack_adapters_cua::CuaInputMode>,
    pub request_id: Option<String>,
    pub scope: Option<store::GrantScope>,
    pub grant_id: Option<String>,
    pub session_id: Option<String>,
    pub recording_id: Option<String>,
    pub artifact_id: Option<String>,
    pub offset: Option<u64>,
    pub provider: Option<String>,
    pub client_id: Option<String>,
    pub account_id: Option<String>,
}

fn owner(state: &LocalRuntimeState, auth: &AuthenticatedContext) -> Owner {
    Owner {
        user_id: auth.user.user_id.clone(),
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
        device_id: state.session_store.installation_id().into(),
    }
}

pub(in crate::local_runtime) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route("/api/v1/computer-use/v2/status", get(status))
        .route("/api/v1/computer-use/v2/manage", post(manage))
        .route(
            "/api/v1/computer-use/v2/sessions/:session_id/stop",
            post(stop),
        )
}

fn failure(error: String) -> (StatusCode, Json<Value>) {
    (
        StatusCode::CONFLICT,
        Json(json!({"code":error,"detail":"Computer-use device operation could not complete"})),
    )
}

async fn status(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let owner = owner(&state, &auth);
    super::input::refresh_status(&state, &owner)
        .await
        .map_err(failure)?;
    super::recordings::refresh_owner(&state, &owner).await;
    snapshot(&state, &owner).map(Json).map_err(failure)
}

async fn manage(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(input): Json<ManagementRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    operation(&state, &owner(&state, &auth), input)
        .await
        .map(Json)
        .map_err(failure)
}

async fn stop(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(id): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    operation(
        &state,
        &owner(&state, &auth),
        ManagementRequest {
            action: "stop".into(),
            session_id: Some(id),
            recording_id: None,
            expected_revision: None,
            capability: None,
            enabled: None,
            input_mode: None,
            request_id: None,
            scope: None,
            grant_id: None,
            artifact_id: None,
            offset: None,
            provider: None,
            client_id: None,
            account_id: None,
        },
    )
    .await
    .map(Json)
    .map_err(failure)
}

pub(super) fn snapshot(state: &LocalRuntimeState, owner: &Owner) -> Result<Value, String> {
    let (instance, grants) = {
        let db = state.session_store.connection()?;
        (store::instance(&db, owner)?, store::grants(&db, owner)?)
    };
    let mut sessions = state.computer_use.sessions_for(owner);
    for session in &mut sessions {
        if session["stopped"] == false {
            if let Some(status) = session["session_id"]
                .as_str()
                .zip(session["run_id"].as_str())
                .and_then(|(id, run)| state.computer_use.locked_use.session_status(id, run))
            {
                session["locked_use"] = status;
            }
        }
    }
    Ok(
        json!({"plugin_id":"memstack-computer-use","version":env!("CARGO_PKG_VERSION"),"device_id":owner.device_id,
        "execution":{"local":true,"cloud":super::cloud::ready(state,owner),"reason":if super::cloud::ready(state,owner){Value::Null}else{json!("device_bridge_unavailable")}},
        "scope":{"tenant_id":owner.tenant_id,"project_id":owner.project_id},"instance":instance,
        "helper_available":super::helper_path().is_some(),"grants":grants,
        "input_support":super::input::support(state),
        "locked_use":state.computer_use.locked_use.status(),
        "recent_presentation":super::presentation::recent(state,owner)?,
        "recordings":super::recordings::snapshot(state,owner)?,
        "pending":state.computer_use.pending_for(owner).into_iter().filter(|pending| super::consent::needs_approval(pending,&grants)).map(|pending| {let mut value=json!(pending);value["scopes"]=json!(super::consent::scopes(&pending.capability));value}).collect::<Vec<_>>(),"sessions":sessions,"connectors":super::connectors::list(state,owner)?,"accounts":super::accounts::list(state,owner)?,
        "permissions":state.computer_use.permissions.lock().map_err(|_|"cua_permission_status_unavailable")?.clone()}),
    )
}

pub(in crate::local_runtime) async fn operation(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
    input: ManagementRequest,
) -> Result<Value, String> {
    if input.action == "artifact_preview" {
        return super::artifacts::preview(
            state,
            owner,
            &input.artifact_id.ok_or("cua_artifact_required")?,
        );
    }
    if input.action == "audio_chunk" {
        return super::artifacts::audio_chunk(
            state,
            owner,
            &input.artifact_id.ok_or("cua_artifact_required")?,
            input.offset.unwrap_or(0),
        );
    }
    match input.action.as_str() {
        "locked_use_status" => {
            super::locked_use::probe(state).await?;
        }
        "locked_use_install" | "locked_use_uninstall" => {
            super::locked_use::manage(
                state,
                owner,
                input.action == "locked_use_install",
                input.expected_revision.ok_or("cua_revision_required")?,
            )
            .await?;
        }
        "permissions_status" | "permission_request" => {
            let _dispatch = state
                .computer_use
                .management
                .try_lock()
                .map_err(|_| "cua_device_busy")?;
            let client = state.computer_use.client()?;
            if input.action == "permission_request" {
                let capability = input
                    .capability
                    .as_deref()
                    .filter(|capability| {
                        matches!(
                            *capability,
                            "accessibility"
                                | "input_monitoring"
                                | "screen_capture"
                                | "microphone"
                                | "calendar"
                                | "contacts"
                                | "messages"
                                | "system_audio"
                        )
                    })
                    .ok_or("cua_capability_invalid")?;
                let mode = {
                    let db = state.session_store.connection()?;
                    store::instance(&db, owner)?.input_mode
                };
                let context = settings_context(owner, mode);
                let result = client
                    .request_in_session(
                        &context,
                        "permission_request",
                        json!({"capability":capability}),
                    )
                    .await;
                let _ = client.stop_session(&context.session_id).await;
                let _ = client.end_session(&context.session_id).await;
                if result.is_err() {
                    super::input::refresh_support(state, false).await;
                    state.computer_use.shutdown_if_idle().await;
                }
                result.map_err(|_| "cua_permission_request_unavailable")?;
            }
            let result = client
                .request("permissions_status", json!({}))
                .await
                .map_err(|_| "cua_permission_status_unavailable")?;
            *state
                .computer_use
                .permissions
                .lock()
                .map_err(|_| "cua_permission_status_unavailable")? = Some(result);
            let _ = super::locked_use::probe(state).await;
            state.computer_use.shutdown_if_idle().await;
        }
        "connector_connect" => {
            super::accounts::connect(
                state,
                owner,
                input
                    .provider
                    .as_deref()
                    .ok_or("cua_connector_provider_invalid")?,
                input
                    .client_id
                    .as_deref()
                    .ok_or("oauth_client_configuration_required")?,
            )
            .await?
        }
        "connector_start" | "connector_cancel" | "connector_disconnect" => {
            super::accounts::action(
                state,
                owner,
                input.account_id.as_deref().ok_or("cua_account_not_found")?,
                input
                    .action
                    .strip_prefix("connector_")
                    .expect("exact action prefix"),
            )
            .await?
        }
        "status" => {
            super::input::refresh_status(state, owner).await?;
            super::recordings::refresh_owner(state, owner).await;
            if state.computer_use.locked_use.status().is_some() {
                let _ = super::locked_use::probe(state).await;
            }
        }
        "audio_stop" => {
            super::recordings::stop(
                state,
                owner,
                input.session_id.as_deref().ok_or("cua_session_required")?,
                input
                    .recording_id
                    .as_deref()
                    .ok_or("cua_recording_required")?,
            )
            .await?;
        }
        "set_input_mode" => {
            let mode = input.input_mode.ok_or("cua_input_mode_required")?;
            {
                let db = state.session_store.connection()?;
                store::set_input_mode(
                    &db,
                    owner,
                    input.expected_revision.ok_or("cua_revision_required")?,
                    mode,
                )?;
            }
            state.computer_use.stop_owner(state, owner, "revoked").await;
        }
        "install" | "enable" | "disable" | "uninstall" | "configure" => {
            if input.action == "enable" {
                if !super::input::refresh_support(state, true).await {
                    return Err("cua_helper_unavailable_or_incompatible".into());
                }
            }
            if input.action == "configure"
                && input.capability.as_deref() == Some("locked_use")
                && input.enabled == Some(true)
            {
                let result = super::locked_use::probe(state).await?;
                if result["installed"] != true
                    || !matches!(result["state"].as_str(), Some("available" | "active"))
                {
                    return Err("cua_locked_use_unverified".into());
                }
            }
            let value = {
                let db = state.session_store.connection()?;
                store::update(
                    &db,
                    owner,
                    input.expected_revision.ok_or("cua_revision_required")?,
                    &input.action,
                    input.capability.as_deref().zip(input.enabled),
                )?
            };
            // Revision changes revoke pinned sessions before another input can dispatch.
            state
                .computer_use
                .stop_owner(
                    state,
                    owner,
                    if value.enabled { "revoked" } else { "disabled" },
                )
                .await;
            super::accounts::plugin_enabled(state, owner, value.installed && value.enabled).await?;
            if !value.installed {
                state
                    .computer_use
                    .pending
                    .lock()
                    .expect("computer-use consent")
                    .retain(|_, p| p.owner != *owner);
            }
        }
        "grant" => {
            let id = input.request_id.ok_or("cua_request_required")?;
            let pending = state
                .computer_use
                .pending
                .lock()
                .expect("computer-use consent")
                .get(&id)
                .cloned()
                .filter(|pending| pending.owner == *owner)
                .ok_or("cua_request_expired")?;
            if !state
                .computer_use
                .sessions_for(owner)
                .iter()
                .any(|session| session["session_id"] == pending.session_id)
            {
                return Err("cua_request_expired".into());
            }
            let db = state.session_store.connection()?;
            if !store::pending_matches(&db, owner, &id, &json!(pending))? {
                return Err("cua_request_expired".into());
            }
            let scope = input.scope.ok_or("cua_scope_required")?;
            if !super::consent::scopes(&pending.capability).contains(&scope) {
                return Err("cua_action_requires_once".into());
            }
            store::grant(
                &db,
                owner,
                store::Grant {
                    id: String::new(),
                    app: pending.app,
                    identity_digest: pending.identity_digest,
                    capability: pending.capability,
                    scope,
                    session_id: Some(pending.session_id),
                    request_id: Some(id),
                },
            )?;
        }
        "decline" => {
            let id = input.request_id.ok_or("cua_request_required")?;
            let pending = state
                .computer_use
                .pending
                .lock()
                .expect("computer-use consent")
                .get(&id)
                .cloned()
                .filter(|pending| pending.owner == *owner)
                .ok_or("cua_request_expired")?;
            let session = state
                .computer_use
                .sessions
                .lock()
                .expect("CUA sessions")
                .get(&pending.session_id)
                .cloned()
                .ok_or("cua_session_expired")?;
            {
                let db = state.session_store.connection()?;
                if !store::pending_matches(&db, owner, &id, &json!(pending))? {
                    return Err("cua_request_expired".into());
                }
                denials::deny(&db, owner, &session.context.run_id, &id)?;
            }
            state
                .computer_use
                .stop_run(state, &session.context.run_id)
                .await;
        }
        "revoke" => {
            {
                let db = state.session_store.connection()?;
                store::revoke(&db, owner, &input.grant_id.ok_or("cua_grant_required")?)?;
            }
            state.computer_use.stop_owner(state, owner, "revoked").await;
        }
        "stop" => {
            let id = input.session_id.ok_or("cua_session_required")?;
            if !state
                .computer_use
                .sessions_for(owner)
                .iter()
                .any(|session| session["session_id"] == id)
            {
                return Err("cua_session_not_found".into());
            }
            state
                .computer_use
                .user_stop(state, owner, Some(&id))
                .await?;
        }
        "stop_all" => state.computer_use.user_stop(state, owner, None).await?,
        "pause" | "resume" => {
            super::presentation::pause_resume(
                state,
                owner,
                &input.session_id.ok_or("cua_session_required")?,
                input.action == "resume",
            )
            .await?;
        }
        _ => return Err("cua_management_action_invalid".into()),
    }
    snapshot(state, owner)
}

pub(super) fn settings_context(
    owner: &Owner,
    input_mode: agistack_adapters_cua::CuaInputMode,
) -> agistack_adapters_cua::CuaCallContext {
    let id = format!("cua-settings-{}", uuid::Uuid::new_v4());
    agistack_adapters_cua::CuaCallContext {
        user_id: owner.user_id.clone(),
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
        device_id: owner.device_id.clone(),
        conversation_id: "computer-use-settings".into(),
        run_id: id.clone(),
        session_id: id,
        input_mode,
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NativeRequest {
    mode: String,
    tenant_id: String,
    project_id: String,
    #[serde(default)]
    credential: String,
    operation: ManagementRequest,
}

/// Only the authenticated Electron control pipe invokes this. Identity is resolved
/// from the native vault or local session; renderer-supplied user IDs are never accepted.
pub(crate) async fn native_operation(
    state: &Arc<LocalRuntimeState>,
    broker: &crate::trusted_session::TrustedSessionBroker,
    input: Value,
) -> Result<Value, String> {
    let input: NativeRequest =
        serde_json::from_value(input).map_err(|_| "cua_management_request_invalid")?;
    if input.mode == "cloud" && input.operation.action == "audio_stop" {
        let verified = state.computer_use.cloud_cleanup.resolve_audio_stop(
            broker,
            &input.tenant_id,
            &input.project_id,
            state.session_store.installation_id(),
        )?;
        let result = operation(state, &verified.owner, input.operation).await?;
        // A logout or identity switch while cleanup completed must not expose the
        // previous owner's receipt. The completed action only released resources.
        if state.computer_use.cloud_cleanup.resolve_audio_stop(
            broker,
            &input.tenant_id,
            &input.project_id,
            state.session_store.installation_id(),
        )? != verified
        {
            return Err("cua_identity_changed".into());
        }
        return Ok(result);
    }
    let mut cloud_epoch = None;
    let user_id = match input.mode.as_str() {
        "local" => {
            let auth = state
                .session_store
                .validate_session_credential(
                    &input.credential,
                    chrono::Utc::now().timestamp_millis(),
                )?
                .ok_or("cua_session_required")?;
            if auth.workspace.tenant_id != input.tenant_id
                || auth.workspace.project_id != input.project_id
            {
                return Err("cua_scope_mismatch".into());
            }
            auth.user.user_id
        }
        "cloud" => {
            let saved = broker
                .snapshot()
                .map_err(|_| "cua_trusted_session_unavailable")?;
            let record = saved.record.ok_or("cua_trusted_session_unavailable")?;
            if record.runtime_mode != crate::trusted_session::TrustedSessionRuntimeMode::Cloud {
                return Err("cua_trusted_session_required".into());
            }
            let base = record.api_base_url.trim_end_matches('/');
            let base = base.strip_suffix("/api/v1").unwrap_or(base);
            let client = reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(15))
                .build()
                .map_err(|_| "cua_identity_unavailable")?;
            let me: Value = client
                .get(format!("{base}/api/v1/auth/me"))
                .bearer_auth(&record.credential)
                .send()
                .await
                .map_err(|_| "cua_identity_unavailable")?
                .error_for_status()
                .map_err(|_| "cua_identity_unavailable")?
                .json()
                .await
                .map_err(|_| "cua_identity_invalid")?;
            let mut project_url = url::Url::parse(&format!("{base}/api/v1/projects/"))
                .map_err(|_| "cua_scope_invalid")?;
            project_url
                .path_segments_mut()
                .map_err(|_| "cua_scope_invalid")?
                .pop_if_empty()
                .push(&input.project_id);
            let project: Value = client
                .get(project_url)
                .bearer_auth(&record.credential)
                .send()
                .await
                .map_err(|_| "cua_scope_unavailable")?
                .error_for_status()
                .map_err(|_| "cua_scope_unavailable")?
                .json()
                .await
                .map_err(|_| "cua_scope_invalid")?;
            if project.get("tenant_id").and_then(Value::as_str) != Some(input.tenant_id.as_str()) {
                return Err("cua_scope_mismatch".into());
            }
            if broker
                .snapshot()
                .map_err(|_| "cua_trusted_session_unavailable")?
                .epoch
                != saved.epoch
            {
                return Err("cua_identity_changed".into());
            }
            cloud_epoch = Some(saved.epoch);
            me.get("user_id")
                .or_else(|| me.get("id"))
                .and_then(Value::as_str)
                .filter(|id| !id.is_empty())
                .ok_or("cua_identity_invalid")?
                .to_string()
        }
        _ => return Err("cua_runtime_mode_invalid".into()),
    };
    let owner = Owner {
        user_id,
        tenant_id: input.tenant_id,
        project_id: input.project_id,
        device_id: state.session_store.installation_id().into(),
    };
    if let Some(epoch) = cloud_epoch {
        state
            .computer_use
            .cloud_cleanup
            .remember(broker, epoch, &owner)?;
    }
    operation(state, &owner, input.operation).await
}
