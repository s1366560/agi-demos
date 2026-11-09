//! Exact, durable Once approval for an ordinary selected-device MCP invocation.
use super::*;

fn fail(code: &str) -> CoreError {
    CoreError::Tool(code.into())
}

fn pending(row: &Value) -> Value {
    let binding = &row["binding"];
    json!({"request_id":row["permission_id"],"session_id":binding["session_id"],
        "engine_session_id":binding["session_id"],"app":binding["mcp_binding"]["server_name"],
        "identity_digest":binding["catalog_digest"],"capability":"mcp_tool",
        "tool_name":binding["tool_name"],"input_digest":binding["input_digest"],
        "device_tool_permission":{"key":row["key"]}})
}

fn required(row: &Value, claim: &broker::Claim) -> CoreResult<ToolResult> {
    use agistack_core::ports::{
        permission_input_digest, PermissionBinding, PermissionKind, PermissionRequired,
    };
    Ok(PermissionRequired::new(PermissionKind::ServerMcpTool, PermissionBinding {
        tool_name: claim.tool_name.clone(), input_digest: permission_input_digest(&claim.input_json)?,
        engine_session_id: Some(claim.session_id.clone()), cell_id: None, step_id: None,
    }, json!({"error":"cua_permission_required","request":pending(row),"scopes":["once"],
        "hint":"Use the runtime's structured RequestHuman action with kind=permission. Copy target.kind=device_mcp_tool and target.id=request.request_id exactly. Include complete action, target, data, reason, risk, reversibility, scope and evidence. action.name must equal request.tool_name. Judge risk and reversibility from this exact proposed input. Offer only Once. Wait for the human, then retry this exact tool and arguments."})).into_result())
}

impl Broker {
    pub(super) async fn authorize_outer_mcp(
        &self,
        device: &broker::Device,
        run: &authority::RunAuthority,
        claim: &mut broker::Claim,
    ) -> CoreResult<Option<ToolResult>> {
        let definition = device
            .tools
            .iter()
            .find(|tool| tool.name == claim.tool_name)
            .ok_or_else(|| fail("computer_use_tool_unavailable"))?;
        if claim.mcp_binding.is_none() {
            return Err(fail("computer_use_run_permission_denied"));
        }
        let key = format!(
            "computer-use/outer-permissions/{}",
            broker::digest(
                &json!([
                    device.owner,
                    claim.conversation_id,
                    claim.run_id,
                    claim.session_id,
                    claim.tool_name,
                    broker::digest(&claim.input_json)
                ])
                .to_string()
            )
        );
        let binding = json!({"owner":device.owner,"conversation_id":claim.conversation_id,
            "run_id":claim.run_id,"session_id":claim.session_id,"device_id":claim.device_id,
            "connection_id":device.connection_id,"agent_profile":run.agent_profile,
            "allowed_mcp_servers":run.allowed_mcp_servers,"authorization_revision":run.authorization_revision,
            "tool_name":claim.tool_name,"input_digest":broker::digest(&claim.input_json),
            "catalog_digest":broker::digest(&serde_json::to_string(definition).map_err(|_|fail("computer_use_catalog_invalid"))?),
            "mcp_binding":claim.mcp_binding});
        let objects = self
            .objects
            .as_ref()
            .ok_or_else(|| fail("computer_use_permission_storage_unavailable"))?;
        let _guard = self.step_lock.lock().await;
        let mut row = objects.get(&key).await?
            .map(|bytes|serde_json::from_slice::<Value>(&bytes)).transpose()
            .map_err(|_|fail("computer_use_permission_record_invalid"))?
            .unwrap_or_else(||json!({"key":key,"binding":binding,"status":"pending",
                "permission_id":uuid::Uuid::new_v4().to_string(),"origin_request_id":claim.request_id,
                "created_at":chrono::Utc::now().timestamp()}));
        if row["binding"] != binding
            || row["created_at"]
                .as_i64()
                .is_none_or(|created| created + 30 * 60 <= chrono::Utc::now().timestamp())
        {
            return Err(fail("computer_use_permission_identity_changed"));
        }
        match row["status"].as_str() {
            Some("pending") => {}
            Some("approved") => {
                self.live_outer_origin(&row)?;
                // Persist consumption before a device can observe the request.
                row["status"] = json!("consumed");
                row["dispatch_request_id"] = json!(claim.request_id);
                claim.approved_tools = vec![claim.tool_name.clone()];
            }
            _ => return Err(fail("computer_use_permission_already_consumed")),
        }
        let pending_result = (row["status"] == "pending")
            .then(|| required(&row, claim))
            .transpose()?;
        objects
            .put(
                &key,
                serde_json::to_vec(&row)
                    .map_err(|_| fail("computer_use_permission_record_invalid"))?,
                Some("application/json"),
            )
            .await?;
        Ok(pending_result)
    }

    pub(super) async fn verify_pending_outer(
        &self,
        claim: &broker::Claim,
        request: &Value,
    ) -> CoreResult<Value> {
        let key = request
            .pointer("/device_tool_permission/key")
            .and_then(Value::as_str)
            .ok_or_else(|| fail("computer_use_permission_pending_invalid"))?;
        let row = self.read_outer_permission(key).await?;
        self.live_outer_origin(&row)?;
        if row["status"] != "pending"
            || pending(&row) != *request
            || row["origin_request_id"] != claim.request_id
            || row["binding"]["owner"]
                != json!({"user_id":claim.user_id,"tenant_id":claim.tenant_id,"project_id":claim.project_id})
            || row["binding"]["conversation_id"] != claim.conversation_id
            || row["binding"]["run_id"] != claim.run_id
            || row["binding"]["session_id"] != claim.session_id
            || row["binding"]["device_id"] != claim.device_id
            || row["binding"]["tool_name"] != claim.tool_name
            || row["binding"]["input_digest"] != broker::digest(&claim.input_json)
        {
            return Err(fail("computer_use_permission_pending_changed"));
        }
        Ok(row)
    }

    fn live_outer_origin(&self, row: &Value) -> CoreResult<()> {
        let requests = self.requests.lock().expect("CUA requests");
        let origin = row["origin_request_id"]
            .as_str()
            .and_then(|id| requests.get(id))
            .ok_or_else(|| fail("computer_use_permission_origin_missing"))?;
        if origin.cancelled
            || origin.failed
            || origin.status != "completed"
            || json!(origin.owner) != row["binding"]["owner"]
            || origin.claim.run_id != row["binding"]["run_id"]
            || origin.claim.session_id != row["binding"]["session_id"]
        {
            return Err(fail("computer_use_permission_origin_cancelled"));
        }
        Ok(())
    }

    async fn read_outer_permission(&self, key: &str) -> CoreResult<Value> {
        let objects = self
            .objects
            .as_ref()
            .ok_or_else(|| fail("computer_use_permission_storage_unavailable"))?;
        serde_json::from_slice(
            &objects
                .get(key)
                .await?
                .ok_or_else(|| fail("computer_use_permission_pending_missing"))?,
        )
        .map_err(|_| fail("computer_use_permission_record_invalid"))
    }

    pub(super) async fn resolve_outer_permission(
        &self,
        expected: &Value,
        granted: bool,
        hitl_id: &str,
    ) -> CoreResult<()> {
        if !broker::identifier(hitl_id) {
            return Err(fail("computer_use_permission_response_invalid"));
        }
        let _guard = self.step_lock.lock().await;
        let key = expected["key"]
            .as_str()
            .ok_or_else(|| fail("computer_use_permission_record_invalid"))?;
        let mut row = self.read_outer_permission(key).await?;
        if row != *expected || row["status"] != "pending" {
            return Err(fail("computer_use_permission_pending_changed"));
        }
        self.live_outer_origin(&row)?;
        row["status"] = json!(if granted { "approved" } else { "denied" });
        row["hitl_request_id"] = json!(hitl_id);
        self.objects
            .as_ref()
            .ok_or_else(|| fail("computer_use_permission_storage_unavailable"))?
            .put(
                key,
                serde_json::to_vec(&row)
                    .map_err(|_| fail("computer_use_permission_record_invalid"))?,
                Some("application/json"),
            )
            .await
    }
}
