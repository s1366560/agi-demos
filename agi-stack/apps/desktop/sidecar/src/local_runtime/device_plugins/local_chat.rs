//! The signed local-chat capability uses this device's P4 runtime and the workspace
//! reviewed during installation. The guest can submit messages, never paths or credentials.
use super::*;
use crate::local_runtime::{local_run_upload_command, LocalToolHost};
use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use agistack_local_run_upload::{production_limits, UploadQueue};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

const DESCRIPTOR: &str = "targets/desktop-capability.json";
pub(super) const PERMISSION: &str = "device.local-chat";
pub(super) const TOOL: &str = "local_chat";

pub(super) fn declares(archive: &VerifiedBundleArchiveV2) -> Result<bool, String> {
    let Some(bytes) = archive.artifact_at_path(DESCRIPTOR) else {
        return Ok(false);
    };
    if serde_json::from_slice::<Value>(bytes).ok()
        != Some(json!({
            "schema":"memstack.device-capability/1","permission":PERMISSION,"tool":TOOL
        }))
        || !archive.approved_permissions().contains(PERMISSION)
        || archive
            .artifact_at_path("targets/desktop-sidecar.mspkg")
            .is_some()
    {
        return Err("device_plugin_capability_invalid".into());
    }
    Ok(true)
}

/// An optional device-owned loopback provider approved in the native installation UI.
#[derive(Clone, Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LocalModel {
    pub base_url: String,
    pub model: String,
}

impl LocalModel {
    pub fn validate(&self) -> Result<(), String> {
        use url::{Host, Url};
        let url = Url::parse(&self.base_url).map_err(|_| "device_local_model_invalid")?;
        let loopback = matches!(url.host(), Some(Host::Ipv4(ip)) if ip.is_loopback())
            || matches!(url.host(),Some(Host::Ipv6(ip)) if ip.is_loopback());
        if !loopback
            || !matches!(url.scheme(), "http" | "https")
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || !matches!(url.path(), "/v1" | "/v1/")
            || self.model.trim() != self.model
            || self.model.is_empty()
            || self.model.len() > 128
            || self.model.chars().any(char::is_control)
        {
            return Err("device_local_model_invalid".into());
        }
        Ok(())
    }
    fn llm(&self) -> Result<Arc<dyn agistack_core::ports::LlmPort>, String> {
        self.validate()?;
        let client = reqwest::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(std::time::Duration::from_secs(90))
            .build()
            .map_err(|_| "device_local_model_invalid")?;
        Ok(Arc::new(
            crate::local_runtime::HttpLlm::new(self.base_url.clone(), self.model.clone())
                .with_http_client(client),
        ))
    }
}

pub(super) struct Workspace {
    pub root: PathBuf,
    pub token: String,
}
impl Workspace {
    pub fn offer(&self) -> Value {
        json!({"label":self.root.file_name().and_then(|s|s.to_str()),"token":self.token})
    }
}
fn digest(data: &Value) -> String {
    format!("{:x}", Sha256::digest(data.to_string().as_bytes()))
}
pub(super) fn current_workspace(state: &LocalRuntimeState) -> Result<PathBuf, String> {
    let root = state
        .workspace_root
        .lock()
        .map_err(|_| "device_local_workspace_required")?
        .clone();
    root.canonicalize()
        .ok()
        .filter(|p| {
            p.is_dir()
                && p.file_name()
                    .and_then(|s| s.to_str())
                    .is_some_and(|s| !s.contains(['/', '\\', ':']))
        })
        .ok_or_else(|| "device_local_workspace_required".into())
}
pub(super) async fn review(
    state: &LocalRuntimeState,
    scope: &ScopeV2,
    archive: VerifiedBundleArchiveV2,
    release: &str,
    context: &str,
) -> Result<(BTreeSet<String>, Vec<String>, Option<Workspace>), String> {
    if declares(&archive)? {
        let root = current_workspace(state)?;
        let token = digest(&json!([context, release, root]));
        return Ok((
            BTreeSet::from([PERMISSION.into()]),
            vec![TOOL.into()],
            Some(Workspace { root, token }),
        ));
    }
    let permissions = archive.approved_permissions().clone();
    let prepared = runtime::Prepared::stage(scope, archive).await?;
    let tools = prepared.names();
    prepared.close().await;
    let workspace = if permissions
        .iter()
        .any(|p| p.starts_with("device.workspace.read."))
    {
        let root = current_workspace(state)?;
        let token = digest(&json!([context, release, root]));
        Some(Workspace { root, token })
    } else {
        None
    };
    Ok((permissions, tools, workspace))
}

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum Call {
    Execute {
        conversation_id: String,
        idempotency_key: String,
        message: String,
    },
    Stop {
        conversation_id: String,
        idempotency_key: String,
        run_id: Option<String>,
        expected_revision: Option<u64>,
    },
}
struct Admission {
    state: Arc<LocalRuntimeState>,
    owner: CloudOwner,
    device: Device,
    selection: Selection,
}
impl Admission {
    async fn check(&self) -> Result<(), String> {
        if self.selection.approved_permissions != BTreeSet::from([PERMISSION.into()])
            || self.selection.workspace.as_deref()
                != Some(current_workspace(&self.state)?.as_path())
        {
            return Err("device_local_workspace_review_required".into());
        }
        self.owner.recheck().await?;
        self.device
            .check(
                &self.owner,
                &self.selection.reference,
                &self.selection.generation_id,
                &self.selection.approved_permissions,
                Some(&self.selection.grant_id),
            )
            .await?;
        self.owner.fence(|| Ok(()))
    }
}
struct ScopedTools {
    tools: LocalToolHost,
    admission: Arc<Admission>,
}
#[async_trait::async_trait]
impl ToolHost for ScopedTools {
    fn list_tools(&self) -> Vec<String> {
        self.tools.list_tools()
    }
    fn tool_definition(&self, tool: &str) -> Option<agistack_core::ports::ToolDefinition> {
        self.tools.tool_definition(tool)
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
        self.admission.check().await.map_err(CoreError::Tool)?;
        self.tools.call(tool, input).await
    }
}

struct ScopedModel {
    inner: Arc<dyn agistack_core::ports::LlmPort>,
    admission: Arc<Admission>,
}
#[async_trait::async_trait]
impl agistack_core::ports::LlmPort for ScopedModel {
    async fn extract_memory(
        &self,
        _: &agistack_core::model::Episode,
    ) -> CoreResult<agistack_core::ports::MemoryDraft> {
        Err(CoreError::Llm("device_local_chat_operation_invalid".into()))
    }
    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[agistack_core::agent::types::TranscriptEntry],
        tools: &[String],
    ) -> CoreResult<agistack_core::agent::types::AgentAction> {
        self.admission.check().await.map_err(CoreError::Llm)?;
        self.inner.decide(goal, round, transcript, tools).await
    }
    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[agistack_core::agent::types::TranscriptEntry],
        tools: &[agistack_core::ports::ToolDefinition],
        on_text: &(dyn for<'s> Fn(&'s str) + Send + Sync),
    ) -> CoreResult<agistack_core::agent::types::AgentAction> {
        self.admission.check().await.map_err(CoreError::Llm)?;
        self.inner
            .decide_with_tools_stream(goal, round, transcript, tools, on_text)
            .await
    }
}

static ACTIVE: std::sync::LazyLock<std::sync::Mutex<BTreeSet<String>>> =
    std::sync::LazyLock::new(|| std::sync::Mutex::new(BTreeSet::new()));
struct ActiveRun(String);
impl ActiveRun {
    fn acquire(key: &str) -> Result<Self, String> {
        let mut active = ACTIVE.lock().map_err(|_| "device_local_executor_busy")?;
        if active.len() >= 2 || !active.insert(key.to_string()) {
            return Err("device_local_executor_busy".into());
        }
        Ok(Self(key.into()))
    }
}
impl Drop for ActiveRun {
    fn drop(&mut self) {
        if let Ok(mut active) = ACTIVE.lock() {
            active.remove(&self.0);
        }
    }
}

pub(super) async fn invoke(
    state: Arc<LocalRuntimeState>,
    owner: CloudOwner,
    device: Device,
    selection: Selection,
    input: Value,
) -> Result<Value, String> {
    let a = Arc::new(Admission {
        state: state.clone(),
        owner,
        device,
        selection,
    });
    a.check().await?;
    if input == json!({"action": "placement"}) {
        let label = a
            .selection
            .workspace
            .as_deref()
            .and_then(Path::file_name)
            .and_then(|name| name.to_str())
            .ok_or("device_local_workspace_required")?;
        return Ok(json!({"local_root_label": label}));
    }
    let call: Call =
        serde_json::from_value(input).map_err(|_| "device_local_chat_input_invalid")?;
    let (conversation, key) = match &call {
        Call::Execute {
            conversation_id,
            idempotency_key,
            ..
        }
        | Call::Stop {
            conversation_id,
            idempotency_key,
            ..
        } => (conversation_id, idempotency_key),
    };
    if conversation.is_empty()
        || conversation.len() > 256
        || !conversation
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.~".contains(&b))
        || uuid::Uuid::parse_str(key).is_err()
    {
        return Err("device_local_chat_input_invalid".into());
    }
    let (base, bearer) = a.owner.local_run_session(conversation).await?;
    let run_key = digest(&json!([
        a.selection.reference.digest,
        a.owner.project,
        conversation,
        key
    ]));
    let mut args = json!({"user_id":a.owner.user_id,"tenant_id":a.owner.tenant,"device_id":a.device.machine,
        "conversation_id":conversation,"idempotency_key":run_key,"api_base_url":base,"authorization":bearer});
    let result = match call {
        Call::Execute { message, .. } => {
            let _active = ActiveRun::acquire(&run_key)?;
            if message.trim().is_empty() || message.len() > 128 * 1024 {
                return Err("device_local_chat_input_invalid".into());
            }
            let root = a
                .selection
                .workspace
                .as_deref()
                .ok_or("device_local_workspace_required")?;
            let tools = ScopedTools {
                tools: LocalToolHost::new(root).map_err(|_| "device_local_workspace_required")?,
                admission: a.clone(),
            };
            args["message"] = json!(message);
            args["local_root"] = json!(root);
            args["local_root_label"] = json!(root.file_name().and_then(|s| s.to_str()));
            local_run_upload_command::execute_in_workspace(
                &state,
                args,
                Some(Arc::new(tools)),
                Some(Arc::new(ScopedModel {
                    inner: match &a.selection.local_model {
                        Some(model) => model.llm()?,
                        None => local_run_upload_command::llm_for_tenant(&state, &a.owner.tenant),
                    },
                    admission: a.clone(),
                })),
            )
            .await
        }
        Call::Stop {
            run_id,
            expected_revision,
            ..
        } => {
            let path = state
                .app_data_dir
                .as_deref()
                .ok_or("device_plugin_store_unavailable")?
                .join("local-run-upload.db");
            let claim = claim_id(&path, &a, &run_key)?;
            if claim.is_none()
                && !ACTIVE
                    .lock()
                    .map_err(|_| "device_local_executor_busy")?
                    .contains(&run_key)
            {
                return Err("device_local_run_missing".into());
            }
            if run_id.as_ref().is_some_and(|id| Some(id) != claim.as_ref()) {
                return Err("device_local_run_mismatch".into());
            }
            args["run_id"] = json!(claim);
            args["expected_revision"] = json!(expected_revision);
            local_run_upload_command::stop_in_workspace(args).await
        }
    };
    a.check().await?;
    let db = state
        .session_store
        .connection()
        .map_err(|_| "device_plugin_store_unavailable")?;
    store::record_attempt(&db, &a.owner.scope.project_id, &a.selection, &result)?;
    result.map(|report| json!({"sync":report["sync"],"status":report["status"],"run_id":report["run_id"],"executed":report["executed"],"late_terminal":report["late_terminal"]}))
}

fn claim_id(path: &Path, a: &Admission, key: &str) -> Result<Option<String>, String> {
    let queue = UploadQueue::open(path, production_limits())
        .map_err(|_| "device_plugin_store_unavailable")?;
    Ok(queue
        .claim(&a.owner.user_id, &a.device.machine, key)
        .map_err(|_| "device_plugin_store_unavailable")?
        .and_then(|row| row.run_id))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn loopback_model_requires_an_exact_local_provider_endpoint() {
        let model = |base_url: &str| LocalModel {
            base_url: base_url.to_owned(),
            model: "device-model".into(),
        };
        for url in ["http://127.0.0.1:8080/v1", "http://[::1]/v1/"] {
            assert!(model(url).validate().is_ok());
        }
        for url in [
            "http://localhost/v1",
            "https://example.org/v1",
            "http://127.0.0.1/admin",
            "http://user@127.0.0.1/v1",
            "http://[::1]/v1?token=x",
        ] {
            assert!(model(url).validate().is_err());
        }
    }

    #[test]
    fn guest_chat_contribution_cannot_override_workspace_provider_or_identity() {
        let call =
            json!({"action":"execute","conversation_id":"c","idempotency_key":"k","message":"hi"});
        assert!(serde_json::from_value::<Call>(call.clone()).is_ok());
        for field in [
            "workspace",
            "workspace_root",
            "base_url",
            "local_model",
            "authorization",
            "user_id",
        ] {
            let mut input = call.clone();
            input[field] = json!("unauthorized");
            assert!(serde_json::from_value::<Call>(input).is_err());
        }
    }
}
