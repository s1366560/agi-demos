//! A socket-owned broker. Device inputs are claimed over authenticated HTTP, never WS input.
use super::*;
use agistack_core::agent::types::MediaAttachment;
use base64::{engine::general_purpose::STANDARD, Engine as _};
use sha2::{Digest, Sha256};
use std::path::PathBuf;
use tokio::sync::{mpsc, Notify};

#[derive(Clone)]
pub(super) struct Device {
    pub connection_id: String,
    pub owner: Owner,
    pub device_id: String,
    pub tools: Vec<ToolDefinition>,
    pub send: mpsc::Sender<Value>,
}
#[derive(Clone, Serialize)]
pub(super) struct Claim {
    pub request_id: String,
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub device_id: String,
    pub conversation_id: String,
    pub run_id: String,
    pub run_kind: String,
    pub session_id: String,
    pub round: u64,
    pub tool_name: String,
    pub input_json: String,
    pub permission_profile: String,
    pub approved_tools: Vec<String>,
    pub expires_at: i64,
    pub authorization_revision: i32,
    pub plan_version_id: String,
    pub allowed_mcp_servers: Vec<String>,
}
pub(super) struct Request {
    pub connection_id: String,
    pub owner: Owner,
    pub run: authority::RunAuthority,
    pub claim: Claim,
    pub status: &'static str,
    pub result: Option<ToolResult>,
    pub failed: bool,
    pub cancelled: bool,
    pub output: Option<String>,
    pub media: Vec<Artifact>,
    pub notify: Arc<Notify>,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Descriptor {
    pub artifact_id: String,
    pub mime_type: String,
    pub size_bytes: u64,
}
pub(super) struct Artifact {
    pub descriptor: Descriptor,
    pub bytes: Vec<u8>,
    pub complete: bool,
}
#[derive(Clone, Default)]
pub(crate) struct Broker {
    pub(super) devices: Arc<Mutex<HashMap<String, Device>>>,
    pub(super) requests: Arc<Mutex<HashMap<String, Request>>>,
    pub(super) authority: Option<Arc<dyn authority::Authority>>,
    pub(super) objects: Option<Arc<dyn agistack_core::ports::ObjectStore>>,
    pub(super) cache: Arc<Mutex<Option<PathBuf>>>,
    pub(super) pending: Arc<Mutex<HashMap<String, hitl::Pending>>>,
    pub(super) control_receipts: Arc<Mutex<HashMap<(String, String), String>>>,
}
fn fail(code: &str) -> CoreError {
    CoreError::Tool(code.into())
}
pub(super) fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
}
fn digest(input: &str) -> String {
    format!("{:x}", Sha256::digest(input.as_bytes()))
}
fn operation_effect(
    device: &Device,
    tool: &str,
    input: &str,
) -> CoreResult<agistack_adapters_cua::CuaToolEffect> {
    let definition = device
        .tools
        .iter()
        .find(|definition| definition.name == tool)
        .ok_or_else(|| fail("computer_use_tool_unavailable"))?;
    if tool == "computer_connector_call" {
        let input: Value =
            serde_json::from_str(input).map_err(|_| fail("computer_use_input_invalid"))?;
        Ok(agistack_adapters_cua::connector_operation_effect(
            definition.input_schema.as_ref().unwrap_or(&Value::Null),
            &input,
        ))
    } else {
        agistack_adapters_cua::tool_effects()
            .get(tool)
            .copied()
            .ok_or_else(|| fail("computer_use_tool_unknown"))
    }
}
fn validate_connector_access(
    device: &Device,
    tool: &str,
    input: &str,
    allowed: &[String],
) -> CoreResult<()> {
    if tool != "computer_connector_call" {
        return Ok(());
    }
    let definition = device
        .tools
        .iter()
        .find(|definition| definition.name == tool)
        .ok_or_else(|| fail("computer_use_tool_unavailable"))?;
    let input: Value =
        serde_json::from_str(input).map_err(|_| fail("computer_use_input_invalid"))?;
    if !agistack_adapters_cua::connector_operation_allowed(
        definition.input_schema.as_ref().unwrap_or(&Value::Null),
        &input,
        allowed,
    ) {
        return Err(fail("computer_use_connector_not_allowed_by_agent"));
    }
    Ok(())
}
impl Broker {
    pub(super) fn new(
        authority: Arc<dyn authority::Authority>,
        objects: Arc<dyn agistack_core::ports::ObjectStore>,
    ) -> Self {
        Self {
            authority: Some(authority),
            objects: Some(objects),
            ..Self::default()
        }
    }
    pub(super) fn device(&self, owner: &Owner) -> CoreResult<Device> {
        let devices = self.devices.lock().expect("CUA devices");
        let mut matching = devices
            .values()
            .filter(|device| device.owner == *owner && !device.tools.is_empty());
        let device = matching
            .next()
            .cloned()
            .ok_or_else(|| fail("computer_use_device_unavailable"))?;
        if matching.next().is_some() {
            return Err(fail("computer_use_device_selection_required"));
        }
        Ok(device)
    }
    pub(super) async fn request(
        &self,
        owner: &Owner,
        conversation: &str,
        run: &authority::RunAuthority,
        context: &CallIdentity,
        input: &str,
    ) -> CoreResult<ToolResult> {
        self.authority
            .as_ref()
            .ok_or_else(|| fail("computer_use_authority_unavailable"))?
            .recheck(owner, conversation, run)
            .await?;
        let device = self.device(owner)?;
        if !run.agent_profile.permits(&context.tool) {
            return Err(fail("computer_use_tool_not_allowed_by_agent"));
        }
        let effect = operation_effect(&device, &context.tool, input)?;
        validate_connector_access(&device, &context.tool, input, &run.allowed_mcp_servers)?;
        if effect != agistack_adapters_cua::CuaToolEffect::Read
            && run.permission_profile != "full_access"
        {
            return Err(fail("computer_use_run_permission_denied"));
        }
        if !device.tools.iter().any(|tool| tool.name == context.tool) {
            return Err(fail("computer_use_tool_unavailable"));
        }
        let id = digest(
            &serde_json::to_string(&(
                owner,
                conversation,
                &run.run_id,
                &context.session_id,
                context.round,
            ))
            .unwrap(),
        );
        let claim = Claim {
            request_id: id.clone(),
            user_id: owner.user_id.clone(),
            tenant_id: owner.tenant_id.clone(),
            project_id: owner.project_id.clone(),
            device_id: device.device_id.clone(),
            conversation_id: conversation.into(),
            run_id: run.run_id.clone(),
            run_kind: run.run_kind.clone(),
            session_id: context.session_id.clone(),
            round: context.round,
            tool_name: context.tool.clone(),
            input_json: input.into(),
            permission_profile: run.permission_profile.clone(),
            approved_tools: vec![],
            expires_at: chrono::Utc::now().timestamp() + 90,
            authorization_revision: run.authorization_revision,
            plan_version_id: run.plan_version_id.clone(),
            allowed_mcp_servers: run.allowed_mcp_servers.clone(),
        };
        let notify = {
            let mut requests = self.requests.lock().expect("CUA requests");
            if let Some(previous) = requests.get(&id) {
                if previous.claim.input_json != input
                    || previous.claim.tool_name != context.tool
                    || previous.owner != *owner
                {
                    return Err(fail("computer_use_call_identity_conflict"));
                }
                if previous.failed {
                    return Err(CoreError::ToolObservation(
                        previous
                            .result
                            .as_ref()
                            .map(|r| r.output_json.clone())
                            .unwrap_or_else(|| "cua_outcome_unknown".into()),
                    ));
                }
                return previous
                    .result
                    .clone()
                    .ok_or_else(|| fail("cua_outcome_unknown"));
            }
            let notify = Arc::new(Notify::new());
            requests.insert(
                id.clone(),
                Request {
                    connection_id: device.connection_id.clone(),
                    owner: owner.clone(),
                    run: run.clone(),
                    claim,
                    status: "requested",
                    result: None,
                    failed: false,
                    cancelled: false,
                    output: None,
                    media: vec![],
                    notify: notify.clone(),
                },
            );
            notify
        };
        let mut guard = RequestGuard {
            broker: self.clone(),
            id: id.clone(),
            finished: false,
        };
        device
            .send
            .send(json!({"type":"computer_use_request","request_id":id}))
            .await
            .map_err(|_| fail("computer_use_device_disconnected"))?;
        let wait = async {
            loop {
                let notified = notify.notified();
                {
                    let requests = self.requests.lock().expect("CUA requests");
                    let request = requests
                        .get(&id)
                        .ok_or_else(|| fail("cua_outcome_unknown"))?;
                    if let Some(result) = &request.result {
                        if request.failed {
                            return Err(CoreError::ToolObservation(result.output_json.clone()));
                        }
                        return Ok(result.clone());
                    }
                    if request.status == "unknown" {
                        return Err(fail("cua_outcome_unknown"));
                    }
                }
                notified.await;
            }
        };
        let result = tokio::time::timeout(std::time::Duration::from_secs(90), wait)
            .await
            .map_err(|_| fail("cua_outcome_unknown"))?;
        guard.finished = result.is_ok();
        result
    }
    pub(super) fn claim(
        &self,
        id: &str,
        user: &str,
        device: &str,
    ) -> CoreResult<(Claim, Owner, authority::RunAuthority)> {
        let mut requests = self.requests.lock().expect("CUA requests");
        let request = requests
            .get_mut(id)
            .ok_or_else(|| fail("computer_use_request_unavailable"))?;
        if request.owner.user_id != user
            || request.claim.device_id != device
            || request.status != "requested"
            || request.claim.expires_at <= chrono::Utc::now().timestamp()
        {
            return Err(fail("computer_use_claim_denied"));
        }
        self.validate_request_device(request)?;
        request.status = "claimed";
        Ok((
            request.claim.clone(),
            request.owner.clone(),
            request.run.clone(),
        ))
    }
    pub(super) fn validate_request_device(&self, request: &Request) -> CoreResult<()> {
        let registered = self
            .devices
            .lock()
            .expect("CUA devices")
            .get(&request.connection_id)
            .cloned()
            .ok_or_else(|| fail("computer_use_device_disconnected"))?;
        if registered.owner != request.owner
            || registered.device_id != request.claim.device_id
            || registered.tools.is_empty()
        {
            return Err(fail("computer_use_device_disconnected"));
        }
        if !request.run.agent_profile.permits(&request.claim.tool_name) {
            return Err(fail("computer_use_tool_not_allowed_by_agent"));
        }
        let effect = operation_effect(
            &registered,
            &request.claim.tool_name,
            &request.claim.input_json,
        )?;
        validate_connector_access(
            &registered,
            &request.claim.tool_name,
            &request.claim.input_json,
            &request.run.allowed_mcp_servers,
        )?;
        if effect != agistack_adapters_cua::CuaToolEffect::Read
            && request.run.permission_profile != "full_access"
        {
            return Err(fail("computer_use_run_permission_denied"));
        }
        Ok(())
    }
    pub(super) fn claim_preview(
        &self,
        id: &str,
        user: &str,
        device: &str,
    ) -> CoreResult<(Owner, Claim, authority::RunAuthority)> {
        let requests = self.requests.lock().expect("CUA requests");
        let request = requests
            .get(id)
            .ok_or_else(|| fail("computer_use_claim_denied"))?;
        if request.owner.user_id != user || request.claim.device_id != device {
            return Err(fail("computer_use_claim_denied"));
        }
        Ok((
            request.owner.clone(),
            request.claim.clone(),
            request.run.clone(),
        ))
    }
    pub(super) fn disconnect(&self, connection: &str) {
        self.devices.lock().expect("CUA devices").remove(connection);
        let mut requests = self.requests.lock().expect("CUA requests");
        for request in requests
            .values_mut()
            .filter(|request| request.connection_id == connection)
        {
            request.cancelled = true;
            if request.status != "completed" {
                request.status = "unknown";
                request.notify.notify_one();
            }
        }
    }
    pub(super) fn cancel(&self, id: &str) {
        let send = {
            let mut requests = self.requests.lock().expect("CUA requests");
            let Some(request) = requests.get_mut(id) else {
                return;
            };
            request.cancelled = true;
            if request.status != "completed" {
                request.status = "unknown";
                request.notify.notify_one();
            }
            self.devices
                .lock()
                .expect("CUA devices")
                .get(&request.connection_id)
                .map(|device| device.send.clone())
        };
        if let Some(send) = send {
            let id = id.to_owned();
            tokio::spawn(async move {
                let _ = send
                    .send(json!({"type":"computer_use_cancel","request_id":id}))
                    .await;
            });
        }
    }
    pub(super) fn cancel_conversation(&self, owner: &Owner, conversation: &str) {
        let ids: Vec<_> = self
            .requests
            .lock()
            .expect("CUA requests")
            .iter()
            .filter(|(_, request)| {
                request.owner == *owner && request.claim.conversation_id == conversation
            })
            .map(|(id, _)| id.clone())
            .collect();
        for id in ids {
            self.cancel(&id);
        }
    }
    pub(super) fn cancel_run(&self, owner: &Owner, run_id: &str) {
        let ids: Vec<_> = self
            .requests
            .lock()
            .expect("CUA requests")
            .iter()
            .filter(|(_, request)| request.owner == *owner && request.claim.run_id == run_id)
            .map(|(id, _)| id.clone())
            .collect();
        for id in ids {
            self.cancel(&id);
        }
    }
    pub(super) fn receive_result(
        &self,
        connection: &str,
        id: &str,
        output: String,
        is_error: bool,
        descriptors: Vec<Descriptor>,
    ) -> CoreResult<bool> {
        self.receive_control_result(connection, id, output, is_error, descriptors, None, None)
    }
    pub(super) fn receive_control_result(
        &self,
        connection: &str,
        id: &str,
        output: String,
        is_error: bool,
        descriptors: Vec<Descriptor>,
        control_outcome: Option<agistack_core::ports::ToolControlOutcome>,
        control_generation: Option<String>,
    ) -> CoreResult<bool> {
        let mut result = ToolResult::text(output.clone());
        if let Some(outcome) = control_outcome {
            if is_error
                || !descriptors.is_empty()
                || !outcome.matches_result(&result)
                || match outcome {
                    agistack_core::ports::ToolControlOutcome::UserPaused => control_generation
                        .as_deref()
                        .is_none_or(|generation| uuid::Uuid::parse_str(generation).is_err()),
                    agistack_core::ports::ToolControlOutcome::UserStopped => {
                        control_generation.is_some()
                    }
                }
            {
                return Err(fail("computer_use_control_result_invalid"));
            }
            result.control_outcome = Some(outcome);
            result.control_generation = control_generation;
        } else if control_generation.is_some() {
            return Err(fail("computer_use_control_result_invalid"));
        }
        if output.len() > 1024 * 1024
            || descriptors.len() > 21
            || descriptors
                .iter()
                .filter(|d| d.mime_type != "audio/wav")
                .count()
                > 20
            || descriptors
                .iter()
                .try_fold(0u64, |total, d| total.checked_add(d.size_bytes))
                .is_none_or(|total| total > 64 * 1024 * 1024)
        {
            return Err(fail("computer_use_result_invalid"));
        }
        let mut ids = std::collections::BTreeSet::new();
        for descriptor in &descriptors {
            if !identifier(&descriptor.artifact_id)
                || !ids.insert(&descriptor.artifact_id)
                || descriptor.size_bytes == 0
                || descriptor.size_bytes
                    > if descriptor.mime_type == "audio/wav" {
                        64 * 1024 * 1024
                    } else {
                        8 * 1024 * 1024
                    }
                || !matches!(
                    descriptor.mime_type.as_str(),
                    "image/png" | "image/jpeg" | "image/webp" | "audio/wav"
                )
            {
                return Err(fail("computer_use_media_invalid"));
            }
        }
        serde_json::from_str::<Value>(&output).map_err(|_| fail("computer_use_output_invalid"))?;
        let mut requests = self.requests.lock().expect("CUA requests");
        let request = requests
            .get_mut(id)
            .ok_or_else(|| fail("computer_use_result_denied"))?;
        if request.connection_id != connection
            || request.status != "claimed"
            || request.claim.expires_at <= chrono::Utc::now().timestamp()
        {
            return Err(fail("computer_use_result_denied"));
        }
        if control_outcome.is_some()
            && !agistack_adapters_cua::tool_effects().contains_key(request.claim.tool_name.as_str())
        {
            return Err(fail("computer_use_control_result_invalid"));
        }
        request.output = Some(output.clone());
        request.failed = is_error;
        request.media = descriptors
            .into_iter()
            .map(|descriptor| Artifact {
                descriptor,
                bytes: vec![],
                complete: false,
            })
            .collect();
        if is_error || request.media.is_empty() {
            request.result = Some(result);
            request.status = "completed";
            request.notify.notify_one();
            return Ok(false);
        }
        request.status = "receiving";
        Ok(true)
    }
    pub(super) fn receive_media(
        &self,
        connection: &str,
        id: &str,
        artifact_id: &str,
        mime: &str,
        offset: u64,
        data: &str,
        eof: bool,
    ) -> CoreResult<bool> {
        if data.len() > 176 * 1024 {
            return Err(fail("computer_use_media_invalid"));
        }
        let bytes = STANDARD
            .decode(data)
            .map_err(|_| fail("computer_use_media_invalid"))?;
        if bytes.len() > 128 * 1024 {
            return Err(fail("computer_use_media_invalid"));
        }
        let mut requests = self.requests.lock().expect("CUA requests");
        let request = requests
            .get_mut(id)
            .ok_or_else(|| fail("computer_use_media_denied"))?;
        if request.connection_id != connection
            || request.status != "receiving"
            || request.claim.expires_at <= chrono::Utc::now().timestamp()
        {
            return Err(fail("computer_use_media_denied"));
        }
        let artifact = request
            .media
            .iter_mut()
            .find(|media| media.descriptor.artifact_id == artifact_id)
            .ok_or_else(|| fail("computer_use_media_invalid"))?;
        if artifact.complete
            || artifact.descriptor.mime_type != mime
            || offset != artifact.bytes.len() as u64
            || offset + bytes.len() as u64 > artifact.descriptor.size_bytes
            || (!eof && bytes.is_empty())
        {
            return Err(fail("computer_use_media_invalid"));
        }
        artifact.bytes.extend(bytes);
        if eof {
            if artifact.bytes.len() as u64 != artifact.descriptor.size_bytes {
                return Err(fail("computer_use_media_incomplete"));
            }
            artifact.complete = true;
        }
        let complete = request.media.iter().all(|artifact| artifact.complete);
        if complete {
            request.status = "saving";
        }
        Ok(complete)
    }
    pub(super) async fn complete(&self, id: &str) -> CoreResult<()> {
        let (owner, claim, run, output, media) = {
            let requests = self.requests.lock().expect("CUA requests");
            let request = requests
                .get(id)
                .ok_or_else(|| fail("computer_use_request_unavailable"))?;
            (
                request.owner.clone(),
                request.claim.clone(),
                request.run.clone(),
                request
                    .output
                    .clone()
                    .ok_or_else(|| fail("computer_use_output_invalid"))?,
                request
                    .media
                    .iter()
                    .map(|media| (media.descriptor.clone(), media.bytes.clone()))
                    .collect::<Vec<_>>(),
            )
        };
        self.authority
            .as_ref()
            .ok_or_else(|| fail("computer_use_authority_unavailable"))?
            .recheck(&owner, &claim.conversation_id, &run)
            .await?;
        let root = {
            let mut cache = self.cache.lock().expect("CUA cache");
            cache
                .get_or_insert_with(|| {
                    std::env::temp_dir()
                        .join(format!("memstack-cloud-cua-{}", uuid::Uuid::new_v4()))
                })
                .clone()
        };
        std::fs::create_dir_all(&root).map_err(|_| fail("computer_use_artifact_save_failed"))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
                .map_err(|_| fail("computer_use_artifact_save_failed"))?;
        }
        let mut attachments = vec![];
        for (descriptor, bytes) in media {
            let valid = match descriptor.mime_type.as_str() {
                "image/png" => bytes.starts_with(b"\x89PNG\r\n\x1a\n"),
                "image/jpeg" => bytes.starts_with(b"\xff\xd8\xff"),
                "image/webp" => bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WEBP"),
                "audio/wav" => bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WAVE"),
                _ => false,
            };
            if !valid {
                return Err(fail("computer_use_media_invalid"));
            }
            let key = format!(
                "computer-use/{}/{}/{}",
                digest(&serde_json::to_string(&owner).unwrap()),
                id,
                descriptor.artifact_id
            );
            self.objects
                .as_ref()
                .ok_or_else(|| fail("computer_use_artifact_store_unavailable"))?
                .put(&key, bytes.clone(), Some(&descriptor.mime_type))
                .await?;
            if descriptor.mime_type != "audio/wav" {
                let path = root.join(digest(&key));
                std::fs::write(&path, bytes)
                    .map_err(|_| fail("computer_use_artifact_save_failed"))?;
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
                        .map_err(|_| fail("computer_use_artifact_save_failed"))?;
                }
                attachments.push(MediaAttachment {
                    artifact_path: path.to_string_lossy().into_owned(),
                    mime_type: descriptor.mime_type,
                });
            }
        }
        let mut requests = self.requests.lock().expect("CUA requests");
        let request = requests
            .get_mut(id)
            .ok_or_else(|| fail("computer_use_request_unavailable"))?;
        if request.status != "saving" {
            return Err(fail("cua_outcome_unknown"));
        }
        request.result = Some(ToolResult {
            control_outcome: None,
            control_generation: None,
            output_json: output,
            media: attachments,
        });
        request.status = "completed";
        request.notify.notify_one();
        Ok(())
    }
}
struct RequestGuard {
    broker: Broker,
    id: String,
    finished: bool,
}
impl Drop for RequestGuard {
    fn drop(&mut self) {
        if !self.finished {
            self.broker.cancel(&self.id);
        }
    }
}
