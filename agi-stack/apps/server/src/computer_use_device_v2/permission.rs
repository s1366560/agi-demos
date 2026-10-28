//! Authenticate permission provenance independently of model-visible device output.
use super::*;
use agistack_core::ports::{
    permission_input_digest, PermissionBinding, PermissionKind, PermissionRequired,
};

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WirePermission {
    pub kind: PermissionKind,
    #[serde(deserialize_with = "strict_binding")]
    pub binding: PermissionBinding,
    pub demand: Value,
}

fn strict_binding<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<PermissionBinding, D::Error> {
    let value = Value::deserialize(deserializer)?;
    let keys = [
        "tool_name",
        "input_digest",
        "engine_session_id",
        "cell_id",
        "step_id",
    ];
    if value.as_object().is_none_or(|object| {
        object.len() != keys.len() || keys.iter().any(|key| !object.contains_key(*key))
    }) {
        return Err(serde::de::Error::custom(
            "computer_use_permission_binding_invalid",
        ));
    }
    serde_json::from_value(value).map_err(serde::de::Error::custom)
}

/// Created only after authenticated async checks, then consumed under the request lock.
#[derive(Clone)]
pub(super) struct ValidatedPermission {
    permission: PermissionRequired,
    claim: broker::Claim,
    owner: Owner,
    run: authority::RunAuthority,
    connection: String,
}

impl ValidatedPermission {
    pub(super) fn matches(&self, connection: &str, request: &broker::Request) -> bool {
        self.connection == connection
            && self.claim == request.claim
            && self.owner == request.owner
            && self.run == request.run
    }

    pub(super) fn into_permission(self) -> PermissionRequired {
        self.permission
    }
}

fn invalid() -> CoreError {
    CoreError::Tool("computer_use_permission_result_invalid".into())
}

fn valid_identity(value: &Value) -> bool {
    value
        .as_str()
        .is_some_and(|value| !value.is_empty() && value.len() <= 4096)
}

impl WirePermission {
    fn validate_demand(&self) -> CoreResult<()> {
        let request = &self.demand["request"];
        let binding = &self.binding;
        if !matches!(
            self.kind,
            PermissionKind::NativeConsent | PermissionKind::CloudExecutionStep
        ) || binding
            .engine_session_id
            .as_deref()
            .is_none_or(str::is_empty)
            || binding.input_digest.len() != 64
            || !binding
                .input_digest
                .bytes()
                .all(|value| value.is_ascii_hexdigit() && !value.is_ascii_uppercase())
            || binding.cell_id.is_some() != binding.step_id.is_some()
            || binding.cell_id.as_deref().is_some_and(str::is_empty)
            || binding.step_id.as_deref().is_some_and(str::is_empty)
            || self.demand["error"] != "cua_permission_required"
            || request["engine_session_id"].as_str() != binding.engine_session_id.as_deref()
            || request["tool_name"] != binding.tool_name
            || [
                "request_id",
                "session_id",
                "app",
                "identity_digest",
                "capability",
                "tool_name",
                "input_digest",
            ]
            .iter()
            .any(|key| !valid_identity(&request[key]))
            || self.demand["scopes"].as_array().is_none_or(|scopes| {
                scopes.is_empty()
                    || scopes
                        .iter()
                        .any(|scope| !matches!(scope.as_str(), Some("once" | "session" | "always")))
            })
        {
            return Err(invalid());
        }
        match self.kind {
            PermissionKind::NativeConsent
                if agistack_adapters_cua::tool_effects()
                    .contains_key(binding.tool_name.as_str())
                    && !matches!(
                        request["capability"].as_str(),
                        Some("execution_step" | "mcp_tool")
                    ) =>
            {
                Ok(())
            }
            PermissionKind::CloudExecutionStep
                if binding.cell_id.is_some()
                    && request["capability"] == "execution_step"
                    && self.demand["scopes"] == json!(["once"]) =>
            {
                Ok(())
            }
            _ => Err(invalid()),
        }
    }
}

impl Broker {
    pub(super) async fn permission_from_device(
        &self,
        connection: &str,
        id: &str,
        revision: Option<i32>,
        wire: WirePermission,
    ) -> CoreResult<ValidatedPermission> {
        wire.validate_demand()?;
        let (claim, owner, run) = {
            let requests = self.requests.lock().expect("CUA requests");
            let request = requests.get(id).ok_or_else(invalid)?;
            if request.connection_id != connection
                || request.status != "claimed"
                || request.cancelled
                || request.claim.expires_at <= chrono::Utc::now().timestamp()
                || revision != Some(request.claim.authorization_revision)
            {
                return Err(invalid());
            }
            self.validate_request_device(request)?;
            (
                request.claim.clone(),
                request.owner.clone(),
                request.run.clone(),
            )
        };
        self.authority
            .as_ref()
            .ok_or_else(invalid)?
            .recheck(&owner, &claim.conversation_id, &run)
            .await?;
        self.validate_permission_claim(&claim, &wire).await?;
        Ok(ValidatedPermission {
            permission: PermissionRequired::new(wire.kind, wire.binding, wire.demand),
            claim,
            owner,
            run,
            connection: connection.into(),
        })
    }

    pub(super) async fn validate_permission_claim(
        &self,
        claim: &broker::Claim,
        wire: &WirePermission,
    ) -> CoreResult<()> {
        wire.validate_demand()?;
        let binding = &wire.binding;
        if binding.engine_session_id.as_deref() != Some(claim.session_id.as_str()) {
            return Err(invalid());
        }
        let Some(cell) = binding.cell_id.as_ref() else {
            if wire.kind != PermissionKind::NativeConsent
                || binding.tool_name != claim.tool_name
                || binding.input_digest != permission_input_digest(&claim.input_json)?
            {
                return Err(invalid());
            }
            return Ok(());
        };
        if claim.tool_name != "cua_repl_js" {
            return Err(invalid());
        }
        let key = self
            .permission_steps
            .lock()
            .expect("CUA permission steps")
            .get(&(
                claim.request_id.clone(),
                cell.clone(),
                binding.step_id.clone().ok_or_else(invalid)?,
            ))
            .cloned()
            .ok_or_else(invalid)?;
        let row: Value = serde_json::from_slice(
            &self
                .objects
                .as_ref()
                .ok_or_else(invalid)?
                .get(&key)
                .await?
                .ok_or_else(invalid)?,
        )
        .map_err(|_| invalid())?;
        let stored = &row["binding"];
        if row["current_request_id"] != claim.request_id
            || row["authorization_revision"] != claim.authorization_revision
            || row["permission_input_digest"] != binding.input_digest
            || stored["owner"]
                != json!({"user_id":claim.user_id,"tenant_id":claim.tenant_id,"project_id":claim.project_id})
            || stored["conversation_id"] != claim.conversation_id
            || stored["run_id"] != claim.run_id
            || stored["session_id"] != claim.session_id
            || stored["device_id"] != claim.device_id
            || stored["cell_id"] != *cell
            || stored["step_id"].as_str() != binding.step_id.as_deref()
            || stored["tool_name"] != binding.tool_name
        {
            return Err(invalid());
        }
        match wire.kind {
            PermissionKind::CloudExecutionStep
                if row["status"] == "pending" && steps::pending(&row) == wire.demand["request"] =>
            {
                Ok(())
            }
            PermissionKind::NativeConsent
                if row["status"] == "released" && row["last_outcome"] == "not_sent" =>
            {
                Ok(())
            }
            _ => Err(invalid()),
        }
    }
}
