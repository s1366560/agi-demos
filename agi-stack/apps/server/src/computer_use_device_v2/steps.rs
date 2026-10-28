//! Persistent per-step receipts bound to a live, authenticated device claim.
use super::*;
use sha2::{Digest, Sha256};

#[derive(Clone)]
pub(super) struct StepState(pub(super) Broker);
impl axum::extract::FromRef<AppState> for StepState {
    fn from_ref(app: &AppState) -> Self {
        Self(app.computer_use_devices.clone())
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Input {
    device_id: String,
    cell_id: String,
    tool_name: String,
    input_json: String,
    target: Value,
    #[serde(default)]
    parent_request_id: Option<String>,
    #[serde(default)]
    receipt: Option<String>,
    #[serde(default)]
    outcome: Option<String>,
}
fn fail(code: &str) -> CoreError {
    CoreError::Tool(code.into())
}
pub(super) fn hash(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
fn code(claim: &broker::Claim) -> CoreResult<String> {
    let value: Value = serde_json::from_str(&claim.input_json)
        .map_err(|_| fail("computer_use_step_parent_invalid"))?;
    if claim.tool_name != "cua_repl_js" {
        return Err(fail("computer_use_step_parent_invalid"));
    }
    value["code"]
        .as_str()
        .filter(|code| !code.is_empty())
        .map(hash)
        .ok_or_else(|| fail("computer_use_step_parent_invalid"))
}
fn scope_equal(a: &broker::Claim, b: &broker::Claim) -> bool {
    a.user_id == b.user_id
        && a.tenant_id == b.tenant_id
        && a.project_id == b.project_id
        && a.conversation_id == b.conversation_id
        && a.run_id == b.run_id
        && a.session_id == b.session_id
        && a.device_id == b.device_id
}
fn validate(input: &Input, step_id: &str) -> CoreResult<Value> {
    if ![input.device_id.as_str(), input.cell_id.as_str(), step_id]
        .iter()
        .all(|id| broker::identifier(id))
        || input.tool_name.is_empty()
        || input.tool_name.len() > 256
        || input.input_json.len() > 256 * 1024
        || input.target.to_string().len() > 32 * 1024
        || catalog::EXECUTE.contains(&input.tool_name.as_str())
        || !input.target["kind"]
            .as_str()
            .is_some_and(|s| !s.is_empty() && s.len() <= 64)
        || !input.target["id"]
            .as_str()
            .is_some_and(|s| !s.is_empty() && s.len() <= 2048)
    {
        return Err(fail("computer_use_step_invalid"));
    }
    serde_json::from_str::<Value>(&input.input_json)
        .ok()
        .filter(Value::is_object)
        .ok_or_else(|| fail("computer_use_step_invalid"))
}

pub(super) async fn authorize(
    State(state): State<StepState>,
    Extension(identity): Extension<Identity>,
    Path((request_id, step_id)): Path<(String, String)>,
    Json(input): Json<Input>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    state
        .0
        .authorize_step(&identity.user_id, &request_id, &step_id, input)
        .await
        .map(Json)
        .map_err(|_| rejected())
}

impl Broker {
    fn live_step_parent(
        &self,
        user: &str,
        id: &str,
        device: &str,
    ) -> CoreResult<(Owner, broker::Claim, authority::RunAuthority, String)> {
        let requests = self.requests.lock().expect("CUA requests");
        let parent = requests
            .get(id)
            .ok_or_else(|| fail("computer_use_step_parent_missing"))?;
        if parent.owner.user_id != user
            || parent.claim.device_id != device
            || parent.status != "claimed"
            || parent.cancelled
            || parent.claim.expires_at <= chrono::Utc::now().timestamp()
        {
            return Err(fail("computer_use_step_parent_inactive"));
        }
        self.validate_request_device(parent)?;
        Ok((
            parent.owner.clone(),
            parent.claim.clone(),
            parent.run.clone(),
            parent.connection_id.clone(),
        ))
    }
    pub(super) async fn authorize_step(
        &self,
        user: &str,
        request_id: &str,
        step_id: &str,
        input: Input,
    ) -> CoreResult<Value> {
        let arguments = validate(&input, step_id)?;
        let (owner, parent, run, connection) =
            self.live_step_parent(user, request_id, &input.device_id)?;
        let authority = self
            .authority
            .as_ref()
            .ok_or_else(|| fail("computer_use_authority_unavailable"))?;
        authority
            .recheck(&owner, &parent.conversation_id, &run)
            .await?;
        if !run.agent_profile.permits(&input.tool_name) {
            return Err(fail("computer_use_agent_tool_denied"));
        }
        let device = self
            .devices
            .lock()
            .expect("CUA devices")
            .get(&connection)
            .cloned()
            .ok_or_else(|| fail("computer_use_device_disconnected"))?;
        let definition = device
            .tools
            .iter()
            .find(|tool| tool.name == input.tool_name)
            .cloned()
            .ok_or_else(|| fail("computer_use_tool_unavailable"))?;
        let effect = catalog::validate_call(&definition, &arguments, &run.allowed_mcp_servers)?;
        let catalog_digest = hash(
            &serde_json::to_string(&definition)
                .map_err(|_| fail("computer_use_catalog_invalid"))?,
        );
        let origin_id = input.parent_request_id.as_deref().unwrap_or(request_id);
        let origin = {
            let requests = self.requests.lock().expect("CUA requests");
            let origin = requests
                .get(origin_id)
                .ok_or_else(|| fail("computer_use_step_origin_missing"))?;
            if origin.owner != owner
                || origin.connection_id != connection
                || !scope_equal(&origin.claim, &parent)
                || origin.run.agent_profile != run.agent_profile
                || origin.run.allowed_mcp_servers != run.allowed_mcp_servers
                || (origin_id != request_id && (origin.status != "completed" || origin.cancelled))
                || code(&origin.claim)? != code(&parent)?
            {
                return Err(fail("computer_use_step_origin_changed"));
            }
            origin.claim.clone()
        };
        let key = format!(
            "computer-use/steps/{}/{}",
            hash(
                &json!([
                    owner,
                    parent.conversation_id,
                    parent.run_id,
                    parent.session_id
                ])
                .to_string()
            ),
            hash(&json!([origin_id, input.cell_id, step_id]).to_string())
        );
        let binding = json!({"owner":owner,"conversation_id":parent.conversation_id,"run_id":parent.run_id,
            "session_id":parent.session_id,"device_id":parent.device_id,"connection_id":connection,
            "agent_profile":run.agent_profile,"allowed_mcp_servers":run.allowed_mcp_servers,
            "cell_id":input.cell_id,"step_id":step_id,"tool_name":input.tool_name,"input_digest":hash(&input.input_json),
            "target":input.target,"code_digest":code(&origin)?,"catalog_digest":catalog_digest,
            "effect":if effect == catalog::Effect::Read {"read"} else {"mutate"}});
        let objects = self
            .objects
            .as_ref()
            .ok_or_else(|| fail("computer_use_step_storage_unavailable"))?;
        let _step_guard = self.step_lock.lock().await;
        self.live_step_parent(user, request_id, &input.device_id)?;
        let stored = objects
            .get(&key)
            .await?
            .map(|bytes| serde_json::from_slice::<Value>(&bytes))
            .transpose()
            .map_err(|_| fail("computer_use_step_record_invalid"))?;
        if stored.is_none() && origin_id != request_id {
            return Err(fail("computer_use_step_resume_missing"));
        }
        let mut row = stored.unwrap_or_else(|| json!({"binding":binding,"status":if effect == catalog::Effect::Read || run.permission_profile == "full_access" {"approved"} else {"pending"},
            "authorization_revision":run.authorization_revision,"origin_request_id":origin_id,"current_request_id":request_id,
            "permission_id":uuid::Uuid::new_v4().to_string(),"step_key":key,"created_at":chrono::Utc::now().timestamp()}));
        if row["binding"] != binding
            || (row["authorization_revision"] != run.authorization_revision
                && row["status"] != "released")
            || row["created_at"]
                .as_i64()
                .is_none_or(|created| created + 7 * 24 * 3600 <= chrono::Utc::now().timestamp())
        {
            return Err(fail("computer_use_step_identity_changed"));
        }
        if row["status"] == "released" && input.receipt.is_none() && input.outcome.is_none() {
            row["authorization_revision"] = json!(run.authorization_revision);
            row["status"] = json!("approved");
        }
        transition(
            &mut row,
            request_id,
            input.receipt.as_deref(),
            input.outcome.as_deref(),
        )?;
        authority
            .recheck(&owner, &parent.conversation_id, &run)
            .await?;
        self.live_step_parent(user, request_id, &input.device_id)?;
        let current = self
            .devices
            .lock()
            .expect("CUA devices")
            .get(&connection)
            .and_then(|device| {
                device
                    .tools
                    .iter()
                    .find(|tool| tool.name == input.tool_name)
            })
            .cloned();
        if current.as_ref() != Some(&definition) {
            return Err(fail("computer_use_catalog_changed"));
        }
        // Persist consumed before granting dispatch: a crash can lose a result, never replay an action.
        // Preserve ordinary receipt execution for inputs outside the witness digest domain.
        // A null digest can never match an authenticated permission binding.
        row["permission_input_digest"] = json!(agistack_core::ports::permission_input_digest(&input.input_json).ok());
        objects
            .put(
                &key,
                serde_json::to_vec(&row).map_err(|_| fail("computer_use_step_record_invalid"))?,
                Some("application/json"),
            )
            .await?;
        self.live_step_parent(user, request_id, &input.device_id)?;
        self.permission_steps.lock().expect("CUA permission steps").insert(
            (request_id.into(), input.cell_id.clone(), step_id.into()), key.clone(),
        );
        if row["status"] == "pending" {
            return Ok(
                json!({"status":"pending","error":"cua_permission_required","request":pending(&row),"scopes":["once"]}),
            );
        }
        let mut result = json!({"status":if row["status"]=="consumed" {json!("authorized")} else {row["status"].clone()},"receipt":row["receipt"],"cell_id":input.cell_id,"step_id":step_id,
            "input_digest":binding["input_digest"],"catalog_digest":catalog_digest,"authorization_revision":run.authorization_revision});
        if let Some(continuation) = row.get("continuation") {
            result["continuation"] = continuation.clone();
        }
        Ok(result)
    }
    pub(super) async fn verify_pending_step(
        &self,
        claim: &broker::Claim,
        request: &Value,
    ) -> CoreResult<Value> {
        let key = request
            .pointer("/execution_step/key")
            .and_then(Value::as_str)
            .ok_or_else(|| fail("computer_use_step_pending_invalid"))?;
        let objects = self
            .objects
            .as_ref()
            .ok_or_else(|| fail("computer_use_step_storage_unavailable"))?;
        let row: Value = serde_json::from_slice(
            &objects
                .get(key)
                .await?
                .ok_or_else(|| fail("computer_use_step_pending_missing"))?,
        )
        .map_err(|_| fail("computer_use_step_pending_invalid"))?;
        if row["status"] != "pending"
            || row["origin_request_id"] != claim.request_id
            || pending(&row) != *request
            || row["binding"]["owner"]
                != json!({"user_id":claim.user_id,"tenant_id":claim.tenant_id,"project_id":claim.project_id})
            || row["binding"]["conversation_id"] != claim.conversation_id
            || row["binding"]["run_id"] != claim.run_id
            || row["binding"]["session_id"] != claim.session_id
            || row["binding"]["device_id"] != claim.device_id
        {
            return Err(fail("computer_use_step_pending_changed"));
        }
        Ok(row)
    }
    pub(super) async fn resolve_step_permission(
        &self,
        expected: &Value,
        granted: bool,
        hitl_request_id: &str,
    ) -> CoreResult<()> {
        if !broker::identifier(hitl_request_id) {
            return Err(fail("computer_use_step_permission_changed"));
        }
        let _guard = self.step_lock.lock().await;
        let key = expected["step_key"]
            .as_str()
            .ok_or_else(|| fail("computer_use_step_record_invalid"))?;
        let objects = self
            .objects
            .as_ref()
            .ok_or_else(|| fail("computer_use_step_storage_unavailable"))?;
        let mut row: Value = serde_json::from_slice(
            &objects
                .get(key)
                .await?
                .ok_or_else(|| fail("computer_use_step_pending_missing"))?,
        )
        .map_err(|_| fail("computer_use_step_record_invalid"))?;
        if &row != expected || row["status"] != "pending" {
            return Err(fail("computer_use_step_pending_changed"));
        }
        row["status"] = json!(if granted { "approved" } else { "denied" });
        if granted {
            row["continuation"] = json!({"kind":"hitl","hitl_request_id":hitl_request_id,
                "origin_request_id":row["origin_request_id"],
                "previous_authorization_revision":row["authorization_revision"],
                "authorization_revision":row["authorization_revision"],
                "cell_id":row["binding"]["cell_id"],"step_id":row["binding"]["step_id"]});
        }
        objects
            .put(
                key,
                serde_json::to_vec(&row).map_err(|_| fail("computer_use_step_record_invalid"))?,
                Some("application/json"),
            )
            .await
    }
}
fn transition(
    row: &mut Value,
    request_id: &str,
    receipt: Option<&str>,
    outcome: Option<&str>,
) -> CoreResult<()> {
    if let Some(outcome) = outcome {
        if outcome != "not_sent"
            || !matches!(row["status"].as_str(), Some("consumed" | "released"))
            || receipt.is_none()
            || row["receipt"].as_str() != receipt
            || row["current_request_id"] != request_id
        {
            return Err(fail("computer_use_step_release_invalid"));
        }
        row["status"] = json!("released");
        row["last_outcome"] = json!("not_sent");
        row.as_object_mut().expect("step record").remove("continuation");
        return Ok(());
    }
    if row["status"] == "consumed" || row["status"] == "denied" {
        return Err(fail("computer_use_step_already_consumed"));
    }
    if let Some(receipt) = receipt {
        if row["status"] != "ready"
            || row["receipt"].as_str() != Some(receipt)
            || row["current_request_id"] != request_id
        {
            return Err(fail("computer_use_step_receipt_invalid"));
        }
        row["status"] = json!("consumed");
    } else if row["status"] == "approved" {
        row["status"] = json!("ready");
        row["receipt"] = json!(format!(
            "{}{}",
            uuid::Uuid::new_v4().simple(),
            uuid::Uuid::new_v4().simple()
        ));
        row["current_request_id"] = json!(request_id);
    } else if row["status"] == "ready" && row["current_request_id"] != request_id {
        return Err(fail("computer_use_step_receipt_parent_changed"));
    }
    Ok(())
}
pub(super) fn pending(row: &Value) -> Value {
    let binding = &row["binding"];
    json!({"request_id":row["permission_id"],"session_id":binding["cell_id"],"engine_session_id":binding["session_id"],
        "app":binding["target"]["id"],"identity_digest":binding["catalog_digest"],"capability":"execution_step","tool_name":binding["tool_name"],"input_digest":binding["input_digest"],
        "execution_step":{"key":row["step_key"],"cell_id":binding["cell_id"],"step_id":binding["step_id"],"target":binding["target"],"code_digest":binding["code_digest"]}})
}
