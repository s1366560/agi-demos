//! Cloud requests are admitted by the authenticated server, then executed on this device.
use super::*;
use crate::trusted_session::{TrustedSessionBroker, TrustedSessionRuntimeMode};
use serde::Deserialize;
use std::collections::BTreeSet;

#[path = "cloud_resume.rs"]
mod resume;
#[path = "cloud_repl.rs"]
mod repl;
pub(super) use resume::{authorize_resume, resume_available};

#[derive(Clone)]
pub(super) struct SessionBinding {
    pub connection_id: String,
    pub engine_session_id: String,
    resume: Arc<Mutex<Option<resume::ResumeBinding>>>,
}
pub(super) struct Connection {
    pub owner: Owner,
    pub epoch: u64,
    pub conversation_id: Option<String>,
    pub ready: bool,
    pub broker: TrustedSessionBroker,
    pub alive: Arc<AtomicBool>,
}
pub(super) struct RequestBinding {
    pub owner: Owner,
    pub connection_id: String,
    pub session_id: String,
    pub artifacts: BTreeSet<String>,
    pub cancelled: Arc<AtomicBool>,
    pub control: Option<user_control::Receipt>,
}
#[derive(Clone)]
pub(super) struct CloudLease {
    broker: TrustedSessionBroker,
    epoch: u64,
    expires_at: i64,
    profile: String,
    approved_tools: BTreeSet<String>,
    pub(super) allowed_mcp_servers: Vec<String>,
    alive: Arc<AtomicBool>,
    cancelled: Arc<AtomicBool>,
    factory: Arc<super::super::platform_plugin_authority_v2::ActivePlatformPluginGenerationLeaseV2>,
}
impl CloudLease {
    pub(super) fn current(&self, state: &LocalRuntimeState) -> bool {
        !self.cancelled.load(Ordering::SeqCst)
            && self.alive.load(Ordering::SeqCst)
            && self.expires_at > chrono::Utc::now().timestamp()
            && self
                .broker
                .snapshot()
                .is_ok_and(|snapshot| snapshot.epoch == self.epoch && snapshot.record.is_some())
            && state
                .platform_plugin_authority_v2
                .acquire_generation()
                .is_ok_and(|generation| generation.descriptor() == self.factory.descriptor())
    }
    pub(super) fn permits(&self, tool: &str, effect: agistack_adapters_cua::CuaToolEffect) -> bool {
        matches!(effect, agistack_adapters_cua::CuaToolEffect::Read)
            || self.profile == "full_access"
            || self.approved_tools.contains(tool)
    }
}
pub(super) fn factory_lease(
    state: &LocalRuntimeState,
    owner: &Owner,
) -> Result<
    Arc<super::super::platform_plugin_authority_v2::ActivePlatformPluginGenerationLeaseV2>,
    String,
> {
    let generation = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .map_err(|_| "cua_factory_unavailable")?;
    generation
        .resolve_service::<module::ComputerUseFactoryV2>(
            module::SERVICE,
            module::VERSION,
            &ScopeV2 {
                kind: ScopeKindV2::Project,
                tenant_id: Some(owner.tenant_id.clone()),
                project_id: Some(owner.project_id.clone()),
                session_id: None,
            },
            None,
        )
        .map_err(|_| "cua_factory_disabled")?;
    Ok(Arc::new(generation))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Scope {
    tenant_id: String,
    project_id: String,
    conversation_id: Option<String>,
    #[serde(rename = "workspace_id")]
    _workspace_id: Option<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    action: String,
    connection_id: String,
    scope: Scope,
    request_id: Option<String>,
    artifact_id: Option<String>,
    offset: Option<u64>,
}
#[derive(Clone, Deserialize)]
struct Claim {
    request_id: String,
    user_id: String,
    tenant_id: String,
    project_id: String,
    device_id: String,
    conversation_id: String,
    run_id: String,
    run_kind: String,
    session_id: String,
    round: u64,
    tool_name: String,
    input_json: String,
    permission_profile: String,
    approved_tools: Vec<String>,
    #[serde(default)]
    allowed_mcp_servers: Vec<String>,
    #[serde(default)]
    mcp_binding: Option<Value>,
    expires_at: i64,
    authorization_revision: u64,
    plan_version_id: Option<String>,
}
struct Transport {
    client: reqwest::Client,
    base: String,
    credential: String,
    epoch: u64,
}
fn transport(broker: &TrustedSessionBroker) -> Result<Transport, String> {
    let snapshot = broker
        .snapshot()
        .map_err(|_| "cua_trusted_session_unavailable")?;
    let record = snapshot
        .record
        .filter(|record| record.runtime_mode == TrustedSessionRuntimeMode::Cloud)
        .ok_or("cua_trusted_session_required")?;
    let base = record.api_base_url.trim_end_matches('/');
    let base = base.strip_suffix("/api/v1").unwrap_or(base).to_string();
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .map_err(|_| "cua_cloud_transport_unavailable")?;
    Ok(Transport {
        client,
        base,
        credential: record.credential,
        epoch: snapshot.epoch,
    })
}
impl Transport {
    async fn get(&self, path: &str) -> Result<Value, String> {
        self.client
            .get(format!("{}{path}", self.base))
            .bearer_auth(&self.credential)
            .send()
            .await
            .map_err(|_| "cua_cloud_authority_unavailable")?
            .error_for_status()
            .map_err(|_| "cua_cloud_authority_rejected")?
            .json()
            .await
            .map_err(|_| "cua_cloud_authority_invalid".into())
    }
    async fn claim(&self, id: &str, device: &str) -> Result<Claim, String> {
        let mut url = url::Url::parse(&format!("{}/api/v1/agent/device/requests/", self.base))
            .map_err(|_| "cua_cloud_authority_invalid")?;
        url.path_segments_mut()
            .map_err(|_| "cua_cloud_authority_invalid")?
            .pop_if_empty()
            .push(id)
            .push("claim");
        self.client
            .post(url)
            .bearer_auth(&self.credential)
            .json(&json!({"device_id":device}))
            .send()
            .await
            .map_err(|_| "cua_cloud_authority_unavailable")?
            .error_for_status()
            .map_err(|_| "cua_cloud_authority_rejected")?
            .json()
            .await
            .map_err(|_| "cua_cloud_authority_invalid".into())
    }
}
fn checked_connection(
    state: &LocalRuntimeState,
    input: &Input,
    epoch: u64,
) -> Result<Owner, String> {
    state
        .computer_use
        .cloud_connections
        .lock()
        .map_err(|_| "cua_cloud_connection_unavailable")?
        .get(&input.connection_id)
        .filter(|connection| {
            connection.epoch == epoch
                && connection.owner.tenant_id == input.scope.tenant_id
                && connection.owner.project_id == input.scope.project_id
                && connection.conversation_id == input.scope.conversation_id
        })
        .map(|connection| connection.owner.clone())
        .ok_or("cua_cloud_connection_not_registered".into())
}
pub(in crate::local_runtime) async fn operation(
    state: &Arc<LocalRuntimeState>,
    broker: &TrustedSessionBroker,
    input: Value,
) -> Result<Value, String> {
    let input: Input = serde_json::from_value(input).map_err(|_| "cua_cloud_request_invalid")?;
    if input.connection_id.is_empty() || input.connection_id.len() > 128 {
        return Err("cua_cloud_connection_invalid".into());
    }
    if input.action == "close" {
        let connection = state
            .computer_use
            .cloud_connections
            .lock()
            .map_err(|_| "cua_cloud_connection_unavailable")?
            .remove(&input.connection_id);
        if let Some(connection) = connection {
            connection.alive.store(false, Ordering::SeqCst);
            let ids: Vec<_> = state
                .computer_use
                .sessions
                .lock()
                .expect("computer-use sessions")
                .values()
                .filter(|session| {
                    session.owner == connection.owner
                        && session
                            .cloud
                            .as_ref()
                            .is_some_and(|cloud| cloud.connection_id == input.connection_id)
                })
                .map(|session| session.context.session_id.clone())
                .collect();
            for id in ids {
                state.computer_use.close_session(state, &id).await;
            }
        }
        state
            .computer_use
            .cloud_requests
            .lock()
            .expect("cloud requests")
            .retain(|_, request| request.connection_id != input.connection_id);
        return Ok(json!({"closed":true}));
    }
    let transport = transport(broker)?;
    if input.action == "describe" {
        let me = transport.get("/api/v1/auth/me").await?;
        let user = me
            .get("user_id")
            .or_else(|| me.get("id"))
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
            .ok_or("cua_identity_invalid")?;
        let mut project_url = url::Url::parse(&format!("{}/api/v1/projects/", transport.base))
            .map_err(|_| "cua_scope_invalid")?;
        project_url
            .path_segments_mut()
            .map_err(|_| "cua_scope_invalid")?
            .pop_if_empty()
            .push(&input.scope.project_id);
        let project: Value = transport
            .client
            .get(project_url)
            .bearer_auth(&transport.credential)
            .send()
            .await
            .map_err(|_| "cua_scope_unavailable")?
            .error_for_status()
            .map_err(|_| "cua_scope_unavailable")?
            .json()
            .await
            .map_err(|_| "cua_scope_invalid")?;
        if project.get("tenant_id").and_then(Value::as_str) != Some(input.scope.tenant_id.as_str())
            || broker.snapshot().map_err(|_| "cua_identity_changed")?.epoch != transport.epoch
        {
            return Err("cua_scope_mismatch".into());
        }
        let owner = Owner {
            user_id: user.into(),
            tenant_id: input.scope.tenant_id,
            project_id: input.scope.project_id,
            device_id: state.session_store.installation_id().into(),
        };
        state.computer_use.cloud_cleanup.remember(broker, transport.epoch, &owner)?;
        let instance = {
            let db = state.session_store.connection()?;
            store::instance(&db, &owner)?
        };
        let factory = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .ok()
            .is_some_and(|generation| {
                generation
                    .resolve_service::<module::ComputerUseFactoryV2>(
                        module::SERVICE,
                        module::VERSION,
                        &ScopeV2 {
                            kind: ScopeKindV2::Project,
                            tenant_id: Some(owner.tenant_id.clone()),
                            project_id: Some(owner.project_id.clone()),
                            session_id: None,
                        },
                        None,
                    )
                    .is_ok()
            });
        let enabled = instance.installed && instance.enabled && helper_path().is_some() && factory;
        let mut tools = if enabled {
            let host = CuaToolHost::new(state.computer_use.client()?);
            host.list_tools().iter().filter_map(|name|host.tool_definition(name)).map(|mut tool|{
                if tool.name=="computer_connector_call" {tool.input_schema=Some(connectors::schema(state,&owner,&["*".into()],tool.input_schema.unwrap_or(Value::Null)));}
                json!({"name":tool.name,"description":tool.description,"inputSchema":tool.input_schema})
            }).collect::<Vec<_>>()
        } else {
            vec![]
        };
        if enabled { tools.extend(repl::catalog(state, &owner, broker, transport.epoch)?); }
        state
            .computer_use
            .cloud_connections
            .lock()
            .map_err(|_| "cua_cloud_connection_unavailable")?
            .entry(input.connection_id)
            .and_modify(|connection| {
                if !enabled || connection.owner != owner || connection.epoch != transport.epoch {
                    connection.ready = false;
                }
                connection.owner = owner.clone();
                connection.epoch = transport.epoch;
            })
            .or_insert(Connection {
                owner: owner.clone(),
                epoch: transport.epoch,
                conversation_id: input.scope.conversation_id,
                ready: false,
                broker: broker.clone(),
                alive: Arc::new(AtomicBool::new(true)),
            });
        return Ok(
            json!({"device_id":owner.device_id,"tool_definitions":tools,"scope":{"tenant_id":owner.tenant_id,"project_id":owner.project_id},"enabled":enabled,"revision":instance.revision}),
        );
    }
    let owner = checked_connection(state, &input, transport.epoch)?;
    if input.action == "ready" {
        let mut url = url::Url::parse(&format!("{}/api/v1/agent/device/status", transport.base))
            .map_err(|_| "cua_cloud_authority_invalid")?;
        url.query_pairs_mut()
            .append_pair("device_id", &owner.device_id)
            .append_pair("tenant_id", &owner.tenant_id)
            .append_pair("project_id", &owner.project_id);
        let status: Value = transport
            .client
            .get(url)
            .bearer_auth(&transport.credential)
            .send()
            .await
            .map_err(|_| "cua_cloud_authority_unavailable")?
            .error_for_status()
            .map_err(|_| "cua_cloud_authority_rejected")?
            .json()
            .await
            .map_err(|_| "cua_cloud_authority_invalid")?;
        if status["ready"] != true
            || status["device_id"] != owner.device_id
            || status["user_id"] != owner.user_id
            || status["tenant_id"] != owner.tenant_id
            || status["project_id"] != owner.project_id
        {
            return Err("cua_cloud_registration_mismatch".into());
        }
        if let Some(connection) = state
            .computer_use
            .cloud_connections
            .lock()
            .map_err(|_| "cua_cloud_connection_unavailable")?
            .get_mut(&input.connection_id)
        {
            connection.ready = true;
        }
        return Ok(json!({"ready":true}));
    }
    if input.action == "control_events" {
        let requests = state
            .computer_use
            .cloud_requests
            .lock()
            .map_err(|_| "cua_cloud_request_unavailable")?;
        let events = requests.iter().filter(|(_, request)| request.owner == owner && request.connection_id == input.connection_id && !request.cancelled.load(Ordering::SeqCst)).filter_map(|(id, request)| {
            let receipt = request.control.as_ref()?;
            let status = receipt.control.completed(&receipt.generation)?;
            Some(json!({"request_id":id,"session_id":receipt.engine_session_id,"control_generation":receipt.generation,"state":status}))
        }).collect::<Vec<_>>();
        return Ok(json!({"events":events}));
    }
    let request_id = input
        .request_id
        .clone()
        .ok_or("cua_cloud_request_id_required")?;
    if input.action == "cancel" {
        let session = {
            let mut requests = state
                .computer_use
                .cloud_requests
                .lock()
                .map_err(|_| "cua_cloud_request_unavailable")?;
            let request = requests
                .entry(request_id)
                .or_insert_with(|| RequestBinding {
                    owner: owner.clone(),
                    connection_id: input.connection_id.clone(),
                    session_id: String::new(),
                    artifacts: BTreeSet::new(),
                    cancelled: Arc::new(AtomicBool::new(true)),
                    control: None,
                });
            if request.owner != owner || request.connection_id != input.connection_id {
                return Err("cua_cloud_request_scope_invalid".into());
            }
            request.cancelled.store(true, Ordering::SeqCst);
            Some(request.session_id.clone())
        };
        if let Some(session) = session {
            state.computer_use.close_session(state, &session).await;
        }
        return Ok(json!({"stopped":true}));
    }
    if input.action == "media" {
        let artifact = input.artifact_id.ok_or("cua_artifact_required")?;
        if !state
            .computer_use
            .cloud_requests
            .lock()
            .map_err(|_| "cua_cloud_request_unavailable")?
            .get(&request_id)
            .is_some_and(|request| {
                request.owner == owner
                    && request.connection_id == input.connection_id
                    && request.artifacts.contains(&artifact)
            })
        {
            return Err("cua_cloud_artifact_scope_invalid".into());
        }
        return artifacts::cloud_chunk(state, &owner, &artifact, input.offset.unwrap_or(0));
    }
    if input.action != "call" {
        return Err("cua_cloud_action_invalid".into());
    }
    let alive = state
        .computer_use
        .cloud_connections
        .lock()
        .map_err(|_| "cua_cloud_connection_unavailable")?
        .get(&input.connection_id)
        .ok_or("cua_cloud_connection_not_registered")?
        .alive
        .clone();
    let cancelled = {
        let mut requests = state
            .computer_use
            .cloud_requests
            .lock()
            .map_err(|_| "cua_cloud_request_unavailable")?;
        let request = requests
            .entry(request_id.clone())
            .or_insert_with(|| RequestBinding {
                owner: owner.clone(),
                connection_id: input.connection_id.clone(),
                session_id: String::new(),
                artifacts: BTreeSet::new(),
                cancelled: Arc::new(AtomicBool::new(false)),
                control: None,
            });
        if request.owner != owner || request.connection_id != input.connection_id {
            return Err("cua_cloud_request_scope_invalid".into());
        }
        request.cancelled.clone()
    };
    if cancelled.load(Ordering::SeqCst) || !alive.load(Ordering::SeqCst) {
        return Err("cua_cloud_request_cancelled".into());
    }
    let claim = transport.claim(&request_id, &owner.device_id).await?;
    checked_connection(state, &input, transport.epoch)?;
    if cancelled.load(Ordering::SeqCst) || !alive.load(Ordering::SeqCst) {
        return Err("cua_cloud_request_cancelled".into());
    }
    if claim.request_id != request_id
        || claim.user_id != owner.user_id
        || claim.tenant_id != owner.tenant_id
        || claim.project_id != owner.project_id
        || claim.device_id != owner.device_id
        || input
            .scope
            .conversation_id
            .as_ref()
            .is_some_and(|id| id != &claim.conversation_id)
        || claim.expires_at <= chrono::Utc::now().timestamp()
        || !matches!(
            claim.permission_profile.as_str(),
            "read_only" | "workspace_write" | "full_access"
        )
    {
        return Err("cua_cloud_claim_scope_invalid".into());
    }
    if !matches!(claim.run_kind.as_str(), "chat" | "plan")
        || (claim.run_kind == "plan" && claim.plan_version_id.as_deref().is_none_or(str::is_empty))
        || claim.run_id.is_empty()
        || claim.session_id.is_empty()
        || claim.authorization_revision == 0
    {
        return Err("cua_cloud_run_authority_required".into());
    }
    let instance = {
        let db = state.session_store.connection()?;
        store::instance(&db, &owner)?
    };
    if !instance.installed || !instance.enabled {
        return Err("cua_instance_disabled".into());
    }
    denials::ensure(&*state.session_store.connection()?, &owner, &claim.run_id)
        .map_err(|error| error.to_string())?;
    if user_control::stopped(state, &owner, &claim.run_id).map_err(|error| error.to_string())? {
        return Ok(control_response(
            &request_id,
            claim.authorization_revision,
            agistack_core::ports::ToolControlOutcome::UserStopped.result(None),
        ));
    }
    let factory = factory_lease(state, &owner)?;
    let session = {
        let mut sessions = state
            .computer_use
            .sessions
            .lock()
            .expect("computer-use sessions");
        if state
            .computer_use
            .stopped_cloud_runs
            .lock()
            .map_err(|_| "cua_cloud_request_unavailable")?
            .contains(&(owner.clone(), claim.run_id.clone()))
        {
            return Ok(control_response(
                &request_id,
                claim.authorization_revision,
                agistack_core::ports::ToolControlOutcome::UserStopped.result(None),
            ));
        }
        if state.computer_use.shutting_down.load(Ordering::SeqCst)
            || state.computer_use.helper_closing.load(Ordering::SeqCst)
        {
            return Err("cua_device_stopping".into());
        }
        if let Some(session) = sessions.values().find(|session| {
            session.owner == owner
                && session.revision == instance.revision
                && session.context.run_id == claim.run_id
                && session.cloud.as_ref().is_some_and(|cloud| {
                    cloud.connection_id == input.connection_id
                        && cloud.engine_session_id == claim.session_id
                })
                && !session.stopped.load(Ordering::SeqCst)
        }) {
            session.clone()
        } else {
            let context = CuaCallContext {
                user_id: owner.user_id.clone(),
                tenant_id: owner.tenant_id.clone(),
                project_id: owner.project_id.clone(),
                device_id: owner.device_id.clone(),
                conversation_id: claim.conversation_id.clone(),
                run_id: claim.run_id.clone(),
                session_id: format!("cua-cloud-{}", Uuid::new_v4()),
                input_mode: instance.input_mode,
            };
            let session = Arc::new(Session {
                resources: Default::default(),
                dispatch: tokio::sync::Mutex::new(()),
                owner: owner.clone(),
                context,
                revision: instance.revision,
                stopped: AtomicBool::new(false),
                paused: AtomicBool::new(false),
                user_control: Default::default(),
                presentation: Mutex::new(json!({"phase":"idle","can_resume":false})),
                child: None,
                cloud: Some(SessionBinding {
                    connection_id: input.connection_id.clone(),
                    engine_session_id: claim.session_id.clone(),
                    resume: Default::default(),
                }),
            });
            sessions.insert(session.context.session_id.clone(), session.clone());
            session
        }
    };
    super::presentation::listen(state, &state.computer_use.client()?);
    if let Some(request) = state
        .computer_use
        .cloud_requests
        .lock()
        .map_err(|_| "cua_cloud_request_unavailable")?
        .get_mut(&request_id)
    {
        request.session_id = session.context.session_id.clone();
    }
    if cancelled.load(Ordering::SeqCst) || !alive.load(Ordering::SeqCst) {
        state
            .computer_use
            .close_session(state, &session.context.session_id)
            .await;
        return Err("cua_cloud_request_cancelled".into());
    }
    let lease = CloudLease {
        broker: broker.clone(),
        epoch: transport.epoch,
        expires_at: claim.expires_at,
        profile: claim.permission_profile.clone(),
        approved_tools: claim.approved_tools.iter().cloned().collect(),
        allowed_mcp_servers: claim.allowed_mcp_servers.clone(),
        alive,
        cancelled,
        factory,
    };
    let resume_binding = resume::ResumeBinding::new(
        request_id.clone(),
        claim.authorization_revision,
        lease.clone(),
    );
    resource_lease::renew(state, &session, lease.clone(), claim.expires_at).await?;
    let client = state.computer_use.client()?;
    let host = ScopedComputerUseHost {
        state: Arc::downgrade(state),
        native: NativeIdentity::Cloud(lease.clone()),
        session: session.clone(),
        client: client.clone(),
        inner: Arc::new(CuaToolHost::new(client).with_context(session.context.clone())),
    };
    let context = agistack_core::agent::tool_policy::ToolPolicyContext {
        session_id: &claim.session_id,
        round: claim.round,
        tool: &claim.tool_name,
    };
    let mut result = if crate::local_runtime::cua_repl::TOOLS.contains(&claim.tool_name.as_str()) || claim.mcp_binding.is_some() {
        repl::execute(state, &owner, claim.clone(), lease, session.clone()).await
    } else { call_identity::scope(
        &context,
        host.call_with_content(&claim.tool_name, &claim.input_json),
    )
    .await }
    .map_err(|error| error.to_string())?;
    if crate::local_runtime::cua_repl::TOOLS.contains(&claim.tool_name.as_str()) {
        artifacts::persist(state, &owner, &session.context, &mut result).await.map_err(|error|error.to_string())?;
    }
    if let Some(binding) = &session.cloud {
        *binding
            .resume
            .lock()
            .map_err(|_| "cua_cloud_resume_unavailable")? = Some(resume_binding);
    }
    if result.control_outcome.is_some() {
        if let Some(generation) = result.control_generation.as_ref() {
            if let Some(request) = state
                .computer_use
                .cloud_requests
                .lock()
                .map_err(|_| "cua_cloud_request_unavailable")?
                .get_mut(&request_id)
            {
                request.control = Some(user_control::Receipt {
                    engine_session_id: claim.session_id.clone(),
                    generation: generation.clone(),
                    control: session.user_control.clone(),
                });
            }
        }
        return Ok(control_response(
            &request_id,
            claim.authorization_revision,
            result,
        ));
    }
    let mut media = artifacts::media_descriptors(state, &owner, &result.media)?;
    let mut output: Value =
        serde_json::from_str(&result.output_json).map_err(|_| "cua_cloud_output_invalid")?;
    strip_inline_media(&mut output);
    if let Some(artifacts) = output.get_mut("artifacts").and_then(Value::as_array_mut) {
        for artifact in artifacts {
            if artifact["kind"] == "audio" && artifact["mime_type"] == "audio/wav" {
                let id = artifact["artifact_id"]
                    .as_str()
                    .ok_or("cua_cloud_audio_artifact_missing")?
                    .to_owned();
                if !media.iter().any(|descriptor| descriptor["artifact_id"] == id) {
                    media.push(artifacts::descriptor(state, &owner, &id)?);
                }
                if let Some(object) = artifact.as_object_mut() {
                    object.remove("url");
                }
            }
        }
    }
    if let Some(request) = state
        .computer_use
        .cloud_requests
        .lock()
        .map_err(|_| "cua_cloud_request_unavailable")?
        .get_mut(&request_id)
    {
        request.artifacts = media
            .iter()
            .filter_map(|media| media["artifact_id"].as_str().map(str::to_owned))
            .collect();
    }
    Ok(
        json!({"request_id":request_id,"output_json":output.to_string(),"is_error":false,"media":media,"authorization_revision":claim.authorization_revision,
            "permission_required":result.permission_required}),
    )
}

fn strip_inline_media(value: &mut Value) {
    match value {
        Value::Array(items) => items.iter_mut().for_each(strip_inline_media),
        Value::Object(object) => {
            object.remove("icon");
            object.remove("data_url");
            if let Some(screenshot) = object.get_mut("screenshot").and_then(Value::as_object_mut) {
                screenshot.remove("url");
            }
            object.values_mut().for_each(strip_inline_media);
        }
        _ => {}
    }
}

#[cfg(test)]
mod wire_tests {
    use super::*;
    #[test]
    fn cloud_observations_keep_owned_descriptors_and_strip_nested_inline_media() {
        let mut output = json!({"apps":[{"id":"app","icon":"inline-icon","state":{"screenshot":{"url":"file:///private/capture.png","data_url":"inline-image","artifact_id":"cua-image"}}}],"text":"observation"});
        strip_inline_media(&mut output);
        assert_eq!(output["apps"][0]["id"], "app");
        assert_eq!(
            output["apps"][0]["state"]["screenshot"]["artifact_id"],
            "cua-image"
        );
        let encoded = output.to_string();
        assert!(!encoded.contains("inline-"));
        assert!(!encoded.contains("file://"));
    }
}

pub(super) fn ready(state: &LocalRuntimeState, owner: &Owner) -> bool {
    state
        .computer_use
        .cloud_connections
        .lock()
        .is_ok_and(|connections| {
            connections.values().any(|connection| {
                connection.owner == *owner
                    && connection.ready
                    && connection.broker.snapshot().is_ok_and(|snapshot| {
                        snapshot.epoch == connection.epoch && snapshot.record.is_some()
                    })
            })
        })
}

fn control_response(request_id: &str, revision: u64, result: ToolResult) -> Value {
    let mut value = json!({"request_id":request_id,"output_json":result.output_json,"is_error":false,"media":[],"authorization_revision":revision,"control_outcome":result.control_outcome});
    if let Some(generation) = result.control_generation {
        value["control_generation"] = json!(generation);
    }
    value
}
