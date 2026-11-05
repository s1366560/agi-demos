//! Five-second continuity authority; tool claims and their expiry are never extended.
use super::resume_authority::ResumeState;
use super::*;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Input {
    pub(super) device_id: String,
    pub(super) session_id: String,
    pub(super) cell_id: Option<String>,
    pub(super) step_id: Option<String>,
    pub(super) parent_request_id: Option<String>,
}

pub(super) async fn continuity_authority(
    State(state): State<ResumeState>,
    Extension(identity): Extension<Identity>,
    Path(id): Path<String>,
    Json(input): Json<Input>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let (owner, _, _) = state
        .broker
        .continuity_source(&id, &identity.user_id, &input)
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
        .continuity_authority(&id, &identity.user_id, &input)
        .await
        .map(Json)
        .map_err(|_| rejected())
}

fn denied() -> CoreError {
    CoreError::Tool("computer_use_continuity_denied".into())
}

impl Broker {
    fn continuity_source(
        &self,
        id: &str,
        user: &str,
        input: &Input,
    ) -> CoreResult<(Owner, broker::Claim, authority::RunAuthority)> {
        if [&input.device_id, &input.session_id]
            .iter()
            .any(|value| !broker::identifier(value))
            || input.cell_id.is_some() != input.step_id.is_some()
            || [&input.cell_id, &input.step_id, &input.parent_request_id]
                .iter()
                .any(|value| {
                    value
                        .as_ref()
                        .is_some_and(|value| !broker::identifier(value))
                })
        {
            return Err(denied());
        }
        let requests = self.requests.lock().expect("CUA requests");
        let request = requests.get(id).ok_or_else(denied)?;
        if request.owner.user_id != user
            || request.claim.device_id != input.device_id
            || request.claim.session_id != input.session_id
            || request.cancelled
            || request.failed
            || !matches!(
                request.status,
                "claimed" | "receiving" | "saving" | "completed"
            )
            || request.result.as_ref().is_some_and(|result| {
                result.permission_required.is_some() || result.control_outcome.is_some()
            })
            || !request.run.agent_profile.permits("computer_locked_use")
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

    async fn continuity_enable(
        &self,
        id: &str,
        claim: &broker::Claim,
        input: &Input,
    ) -> CoreResult<()> {
        if claim.tool_name == "computer_locked_use" {
            if input.cell_id.is_some()
                || input.step_id.is_some()
                || input.parent_request_id.is_some()
                || serde_json::from_str::<Value>(&claim.input_json).ok()
                    != Some(json!({"enabled":true}))
            {
                return Err(denied());
            }
            return Ok(());
        }
        if claim.tool_name != "cua_repl_js" {
            return Err(denied());
        }
        let cell = input.cell_id.as_ref().ok_or_else(denied)?;
        let step = input.step_id.as_ref().ok_or_else(denied)?;
        let key = self
            .permission_steps
            .lock()
            .expect("CUA permission steps")
            .get(&(id.into(), cell.clone(), step.clone()))
            .cloned()
            .ok_or_else(denied)?;
        let bytes = self
            .objects
            .as_ref()
            .ok_or_else(denied)?
            .get(&key)
            .await?
            .ok_or_else(denied)?;
        let row: Value = serde_json::from_slice(&bytes).map_err(|_| denied())?;
        let binding = &row["binding"];
        if row["status"] != "consumed"
            || row["current_request_id"] != id
            || row["origin_request_id"] != input.parent_request_id.as_deref().unwrap_or(id)
            || row["authorization_revision"] != claim.authorization_revision
            || binding["tool_name"] != "computer_locked_use"
            || binding["cell_id"] != *cell
            || binding["step_id"] != *step
            || binding["run_id"] != claim.run_id
            || binding["session_id"] != claim.session_id
            || binding["device_id"] != claim.device_id
            || binding["owner"]["user_id"] != claim.user_id
            || binding["owner"]["tenant_id"] != claim.tenant_id
            || binding["owner"]["project_id"] != claim.project_id
            || row["permission_input_digest"]
                != agistack_core::ports::permission_input_digest("{\"enabled\":true}")?
        {
            return Err(denied());
        }
        Ok(())
    }

    pub(super) async fn continuity_authority(
        &self,
        id: &str,
        user: &str,
        input: &Input,
    ) -> CoreResult<Value> {
        let (owner, claim, run) = self.continuity_source(id, user, input)?;
        self.continuity_enable(id, &claim, input).await?;
        self.authority
            .as_ref()
            .ok_or_else(denied)?
            .recheck_running(&owner, &claim.conversation_id, &run)
            .await?;
        let (_, current, current_run) = self.continuity_source(id, user, input)?;
        if current_run != run || current.authorization_revision != claim.authorization_revision {
            return Err(denied());
        }
        self.continuity_enable(id, &current, input).await?;
        Ok(
            json!({"request_id":claim.request_id,"user_id":claim.user_id,"tenant_id":claim.tenant_id,
            "project_id":claim.project_id,"device_id":claim.device_id,"conversation_id":claim.conversation_id,
            "run_id":claim.run_id,"session_id":claim.session_id,"authorization_revision":claim.authorization_revision,
            "expires_at_ms":chrono::Utc::now().timestamp_millis()+5000}),
        )
    }
}
