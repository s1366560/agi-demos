//! Short-lived permission to resume an existing native session, never to replay a tool call.
use super::*;
use axum::extract::FromRef;

#[derive(Clone)]
pub(super) struct ResumeState {
    pub(super) broker: Broker,
    pub(super) auth: crate::auth::SharedAuthenticator,
}

impl FromRef<AppState> for ResumeState {
    fn from_ref(app: &AppState) -> Self {
        Self {
            broker: app.computer_use_devices.clone(),
            auth: app.auth.clone(),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ResumeInput {
    device_id: String,
    session_id: String,
}

#[derive(Debug, Serialize)]
pub(super) struct ResumeAuthority {
    request_id: String,
    user_id: String,
    tenant_id: String,
    project_id: String,
    device_id: String,
    conversation_id: String,
    run_id: String,
    session_id: String,
    authorization_revision: i32,
    expires_at: i64,
}

pub(super) async fn resume_authority(
    State(state): State<ResumeState>,
    Extension(identity): Extension<Identity>,
    Path(id): Path<String>,
    Json(input): Json<ResumeInput>,
) -> Result<Json<ResumeAuthority>, (StatusCode, Json<Value>)> {
    if [&input.device_id, &input.session_id]
        .iter()
        .any(|value| value.is_empty() || value.chars().count() > 256)
    {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({"detail":"computer_use_resume_input_invalid"})),
        ));
    }
    let (owner, _, _) = state
        .broker
        .resume_preview(&id, &identity.user_id, &input.device_id, &input.session_id)
        .map_err(|_| rejected())?;
    let tenant = state
        .auth
        .authorize_project_event_subscription(
            &identity.user_id,
            &owner.project_id,
            Some(&owner.tenant_id),
        )
        .await
        .map_err(|_| rejected())?;
    if tenant.as_deref() != Some(&owner.tenant_id) {
        return Err(rejected());
    }
    state
        .broker
        .resume_authority(&id, &identity.user_id, &input.device_id, &input.session_id)
        .await
        .map(Json)
        .map_err(|_| rejected())
}

impl Broker {
    fn resume_preview(
        &self,
        id: &str,
        user: &str,
        device: &str,
        session: &str,
    ) -> CoreResult<(Owner, broker::Claim, authority::RunAuthority)> {
        let requests = self.requests.lock().expect("CUA requests");
        let request = requests.get(id).ok_or_else(denied)?;
        if request.owner.user_id != user
            || request.claim.device_id != device
            || request.claim.session_id != session
            || request.status != "completed"
            || request.cancelled
            || request.failed
            || request.result.is_none()
        {
            return Err(denied());
        }
        self.validate_request_device(request)?;
        Ok((
            request.owner.clone(),
            request.claim.clone(),
            request.run.clone(),
        ))
    }

    pub(super) async fn resume_authority(
        &self,
        id: &str,
        user: &str,
        device: &str,
        session: &str,
    ) -> CoreResult<ResumeAuthority> {
        let (owner, claim, run) = self.resume_preview(id, user, device, session)?;
        self.authority
            .as_ref()
            .ok_or_else(denied)?
            .recheck_running(&owner, &claim.conversation_id, &run)
            .await?;
        // Cancellation, disconnect and catalog updates may race the authority read.
        self.resume_preview(id, user, device, session)?;
        Ok(ResumeAuthority {
            request_id: claim.request_id,
            user_id: claim.user_id,
            tenant_id: claim.tenant_id,
            project_id: claim.project_id,
            device_id: claim.device_id,
            conversation_id: claim.conversation_id,
            run_id: claim.run_id,
            session_id: claim.session_id,
            authorization_revision: claim.authorization_revision,
            expires_at: chrono::Utc::now().timestamp() + 30,
        })
    }
}

fn denied() -> CoreError {
    CoreError::Tool("computer_use_resume_authority_denied".into())
}
