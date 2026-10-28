//! Authenticated UI-only routes for ephemeral browser credentials.
use super::*;

pub(super) async fn pending(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
) -> LocalJsonResult {
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let pending = state
        .browser_auth
        .pending_for(&conversation_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({ "requests": pending })))
}

pub(super) async fn respond(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(request_id): Path<String>,
    Json(response): Json<browser_auth::AuthResponse>,
) -> LocalJsonResult {
    let owner = state
        .browser_auth
        .owner(&request_id)
        .map_err(local_bad_request)?;
    scoped_conversation(&state, &authenticated, &owner.conversation_id)?;
    let run = state
        .session_store
        .run(&owner.run_id)
        .map_err(local_store_error)?
        .filter(|run| {
            run.conversation_id == owner.conversation_id
                && run.revision == owner.run_revision
                && run.status == DesktopRunStatus::Running
        })
        .ok_or_else(|| local_bad_request("browser_auth_run_changed".into()))?;
    if state.control_for_run(&run).is_some_and(|control| {
        control.directive.load(Ordering::Acquire) != LocalRunControl::CONTINUE
    }) {
        return Err(local_bad_request("browser_auth_run_cancelled".into()));
    }
    state
        .browser_auth
        .respond(&request_id, &owner, response)
        .map_err(local_bad_request)?;
    Ok(Json(json!({ "accepted": true })))
}

impl LocalRuntimeService {
    /// These commands only cross the authenticated Electron control pipe.
    pub(crate) fn browser_auth_pending(&self, input: Value) -> Result<Value, String> {
        let conversation = input["conversation_id"]
            .as_str()
            .filter(|id| !id.is_empty())
            .ok_or("browser_auth_conversation_required")?;
        Ok(json!({"requests": self.state.browser_auth.pending_for_ui(conversation)?}))
    }

    pub(crate) fn browser_auth_respond(&self, input: Value) -> Result<Value, String> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Response {
            request_id: String,
            conversation_id: String,
            response: browser_auth::AuthResponse,
        }
        let response: Response =
            serde_json::from_value(input).map_err(|_| "browser_auth_response_invalid")?;
        let owner = self.state.browser_auth.owner(&response.request_id)?;
        if owner.conversation_id != response.conversation_id {
            return Err("browser_auth_conversation_changed".into());
        }
        self.state
            .browser_auth
            .respond(&response.request_id, &owner, response.response)?;
        Ok(json!({"accepted":true}))
    }
}
