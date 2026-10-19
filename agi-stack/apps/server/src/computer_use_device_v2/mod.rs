//! Authenticated device bridge for the Rust cloud agent. It never launches a native helper.
mod agent_profile;
mod authority;
mod broker;
mod control;
mod hitl;
mod resume_authority;
#[cfg(test)]
mod tests;
use crate::{auth::Identity, AppState};
use agistack_core::{
    agent::tool_policy::{
        ToolExecutionPolicy, ToolPolicyContext, ToolPolicyDecision, ToolPolicyResult,
    },
    ports::{CoreError, CoreResult, ToolDefinition, ToolHost, ToolResult},
};
use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    routing::{get, post},
    Extension, Json, Router,
};
pub(crate) use broker::Broker;
pub(crate) use hitl::{native_receipt, park, resume};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct Owner {
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
}
#[derive(Clone)]
pub(super) struct CallIdentity {
    session_id: String,
    round: u64,
    tool: String,
}
tokio::task_local! {static CALL:CallIdentity;}
fn rejected() -> (StatusCode, Json<Value>) {
    (
        StatusCode::CONFLICT,
        Json(json!({"detail":"computer_use_authority_changed"})),
    )
}
pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/agent/device/status", get(status))
        .route(
            "/api/v1/agent/device/requests/:request_id/claim",
            post(claim),
        )
        .route(
            "/api/v1/agent/device/requests/:request_id/resume-authority",
            post(resume_authority::resume_authority),
        )
}
#[derive(Deserialize)]
struct StatusQuery {
    device_id: String,
    tenant_id: String,
    project_id: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ClaimInput {
    device_id: String,
}
async fn project_owner(
    app: &AppState,
    user: &str,
    tenant: &str,
    project: &str,
) -> CoreResult<Owner> {
    let actual = app
        .auth
        .authorize_project_event_subscription(user, project, Some(tenant))
        .await
        .map_err(|_| CoreError::Tool("computer_use_scope_denied".into()))?;
    if actual.as_deref() != Some(tenant) {
        return Err(CoreError::Tool("computer_use_scope_denied".into()));
    }
    Ok(Owner {
        user_id: user.into(),
        tenant_id: tenant.into(),
        project_id: project.into(),
    })
}
async fn status(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(input): Query<StatusQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let owner = project_owner(&app, &identity.user_id, &input.tenant_id, &input.project_id)
        .await
        .map_err(|_| rejected())?;
    let ready = app
        .computer_use_devices
        .devices
        .lock()
        .expect("CUA devices")
        .values()
        .any(|device| {
            device.owner == owner && device.device_id == input.device_id && !device.tools.is_empty()
        });
    Ok(Json(
        json!({"ready":ready,"device_id":input.device_id,"user_id":owner.user_id,"tenant_id":owner.tenant_id,"project_id":owner.project_id}),
    ))
}
async fn claim(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(id): Path<String>,
    Json(input): Json<ClaimInput>,
) -> Result<Json<broker::Claim>, (StatusCode, Json<Value>)> {
    let broker = &app.computer_use_devices;
    let (owner, claim, run) = broker
        .claim_preview(&id, &identity.user_id, &input.device_id)
        .map_err(|_| rejected())?;
    project_owner(&app, &identity.user_id, &owner.tenant_id, &owner.project_id)
        .await
        .map_err(|_| rejected())?;
    broker
        .authority
        .as_ref()
        .ok_or_else(rejected)?
        .recheck(&owner, &claim.conversation_id, &run)
        .await
        .map_err(|_| rejected())?;
    let (claim, _, _) = broker
        .claim(&id, &identity.user_id, &input.device_id)
        .map_err(|_| rejected())?;
    Ok(Json(claim))
}

pub(crate) fn build(
    app_pool: Option<sqlx::PgPool>,
    workspace: crate::workspace_authority::SharedWorkspaceAuthority,
    objects: Arc<dyn agistack_core::ports::ObjectStore>,
) -> Broker {
    Broker::new(
        Arc::new(authority::PgAuthority {
            pool: app_pool,
            workspace,
        }),
        objects,
    )
}
pub(crate) fn disconnect(app: &AppState, connection: &str) {
    app.computer_use_devices.disconnect(connection);
}
pub(crate) fn cancel_conversation(app: &AppState, user: &str, conversation: &str) {
    let owners: Vec<_> = app
        .computer_use_devices
        .devices
        .lock()
        .expect("CUA devices")
        .values()
        .filter(|device| device.owner.user_id == user)
        .map(|device| device.owner.clone())
        .collect();
    for owner in owners {
        app.computer_use_devices
            .cancel_conversation(&owner, conversation);
    }
}
pub(crate) async fn handle_frame(
    app: &AppState,
    identity: &Identity,
    connection: &str,
    send: &tokio::sync::mpsc::Sender<Value>,
    text: &str,
) -> Option<CoreResult<Value>> {
    let value: Value = serde_json::from_str(text).ok()?;
    let kind = value.get("type")?.as_str()?;
    if !matches!(
        kind,
        "computer_use_device"
            | "computer_use_result"
            | "computer_use_media"
            | "computer_use_control_state"
    ) {
        return None;
    }
    Some(handle_device_frame(app, identity, connection, send, value).await)
}
async fn handle_device_frame(
    app: &AppState,
    identity: &Identity,
    connection: &str,
    send: &tokio::sync::mpsc::Sender<Value>,
    value: Value,
) -> CoreResult<Value> {
    #[derive(Deserialize)]
    struct Scope {
        tenant_id: String,
        project_id: String,
    }
    #[derive(Deserialize)]
    struct Announce {
        device_id: String,
        scope: Scope,
        tool_definitions: Vec<Value>,
    }
    match value["type"].as_str() {
        Some("computer_use_device") => {
            // The Rust WS/engine are socket-owned; a replica hop cannot claim a local socket.
            if std::env::var("AGISTACK_SERVER_REPLICA_COUNT")
                .ok()
                .and_then(|v| v.parse::<u64>().ok())
                .is_some_and(|n| n > 1)
                && std::env::var("AGISTACK_TERMINAL_INSTANCE_AFFINITY").as_deref() != Ok("true")
            {
                return Err(CoreError::Tool(
                    "computer_use_instance_affinity_required".into(),
                ));
            }
            let announce: Announce = serde_json::from_value(value)
                .map_err(|_| CoreError::Tool("computer_use_registration_invalid".into()))?;
            if !broker::identifier(&announce.device_id)
                || announce.tool_definitions.len() > agistack_adapters_cua::tool_names().len()
            {
                return Err(CoreError::Tool("computer_use_registration_invalid".into()));
            }
            let owner = project_owner(
                app,
                &identity.user_id,
                &announce.scope.tenant_id,
                &announce.scope.project_id,
            )
            .await?;
            let declared = agistack_adapters_cua::tool_definitions();
            let mut seen = std::collections::BTreeSet::new();
            let mut tools = vec![];
            for tool in announce.tool_definitions {
                let name = tool["name"]
                    .as_str()
                    .ok_or_else(|| CoreError::Tool("computer_use_tool_invalid".into()))?;
                let contract = declared
                    .get(name)
                    .ok_or_else(|| CoreError::Tool("computer_use_tool_invalid".into()))?;
                let mut standard_schema = tool["inputSchema"].clone();
                if name == "computer_connector_call" {
                    agistack_adapters_cua::validate_connector_operations(&standard_schema)
                        .map_err(|error| CoreError::Tool(error.into()))?;
                    if let Some(schema) = standard_schema.as_object_mut() {
                        schema.remove(agistack_adapters_cua::CONNECTOR_OPERATION_EFFECTS);
                    }
                }
                if standard_schema != contract["inputSchema"] || !seen.insert(name.to_owned()) {
                    return Err(CoreError::Tool(
                        "computer_use_tool_contract_mismatch".into(),
                    ));
                }
                let mut description = contract["description"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned();
                if name == agistack_adapters_cua::TOOL_GET_APP_STATE {
                    description.push_str("\n\n");
                    description.push_str(include_str!(
                        "../../../desktop/cua-plugin/skills/computer-use/SKILL.md"
                    ));
                }
                tools.push(ToolDefinition::new(
                    name,
                    description,
                    tool["inputSchema"].clone(),
                ));
            }
            let mut devices = app
                .computer_use_devices
                .devices
                .lock()
                .expect("CUA devices");
            if devices.get(connection).is_some_and(|device| {
                device.owner != owner || device.device_id != announce.device_id
            }) {
                return Err(CoreError::Tool(
                    "computer_use_connection_scope_changed".into(),
                ));
            }
            devices.insert(
                connection.into(),
                broker::Device {
                    connection_id: connection.into(),
                    owner,
                    device_id: announce.device_id.clone(),
                    tools,
                    send: send.clone(),
                },
            );
            Ok(json!({"type":"computer_use_device_ready","device_id":announce.device_id}))
        }
        Some("computer_use_result") => {
            #[derive(Deserialize)]
            struct ResultFrame {
                request_id: String,
                output_json: String,
                is_error: bool,
                media: Vec<broker::Descriptor>,
                control_outcome: Option<agistack_core::ports::ToolControlOutcome>,
                control_generation: Option<String>,
            }
            let frame: ResultFrame = serde_json::from_value(value)
                .map_err(|_| CoreError::Tool("computer_use_result_invalid".into()))?;
            app.computer_use_devices.receive_control_result(
                connection,
                &frame.request_id,
                frame.output_json,
                frame.is_error,
                frame.media,
                frame.control_outcome,
                frame.control_generation,
            )?;
            Ok(Value::Null)
        }
        Some("computer_use_control_state") => {
            let frame: control::Frame = serde_json::from_value(value)
                .map_err(|_| CoreError::Tool("computer_use_control_state_invalid".into()))?;
            app.computer_use_devices
                .receive_control_state(connection, frame)
                .await?;
            Ok(Value::Null)
        }
        Some("computer_use_media") => {
            #[derive(Deserialize)]
            struct MediaFrame {
                request_id: String,
                artifact_id: String,
                mime_type: String,
                offset: u64,
                data_base64: String,
                eof: bool,
            }
            let frame: MediaFrame = serde_json::from_value(value)
                .map_err(|_| CoreError::Tool("computer_use_media_invalid".into()))?;
            if app.computer_use_devices.receive_media(
                connection,
                &frame.request_id,
                &frame.artifact_id,
                &frame.mime_type,
                frame.offset,
                &frame.data_base64,
                frame.eof,
            )? {
                let broker = app.computer_use_devices.clone();
                tokio::spawn(async move {
                    if broker.complete(&frame.request_id).await.is_err() {
                        broker.cancel(&frame.request_id);
                    }
                });
            }
            Ok(Value::Null)
        }
        _ => Err(CoreError::Tool("computer_use_frame_invalid".into())),
    }
}

pub(crate) struct BoundRun {
    owner: Owner,
    run: authority::RunAuthority,
    pub tools: Arc<dyn ToolHost>,
    broker: Broker,
    parked: bool,
}
impl Drop for BoundRun {
    fn drop(&mut self) {
        if !self.parked {
            self.broker.cancel_run(&self.owner, &self.run.run_id);
        }
    }
}
pub(crate) async fn bind_run(
    app: &AppState,
    user: &str,
    tenant: &str,
    project: &str,
    conversation: &str,
    message_id: &str,
    message: &str,
) -> CoreResult<Option<BoundRun>> {
    let owner = project_owner(app, user, tenant, project).await?;
    if app.computer_use_devices.device(&owner).is_err() {
        return Ok(None);
    }
    let run = app
        .computer_use_devices
        .authority
        .as_ref()
        .ok_or_else(|| CoreError::Tool("computer_use_authority_unavailable".into()))?
        .prepare(&owner, conversation, message_id, message)
        .await?;
    Ok(Some(BoundRun {
        parked: false,
        broker: app.computer_use_devices.clone(),
        owner: owner.clone(),
        run: run.clone(),
        tools: Arc::new(Host {
            base: Arc::new(app.registry.clone()),
            broker: app.computer_use_devices.clone(),
            owner,
            conversation: conversation.into(),
            run,
        }),
    }))
}
struct Host {
    base: Arc<dyn ToolHost>,
    broker: Broker,
    owner: Owner,
    conversation: String,
    run: authority::RunAuthority,
}
impl Host {
    fn native_tools(&self) -> Vec<ToolDefinition> {
        self.broker
            .device(&self.owner)
            .map(|device| {
                device
                    .tools
                    .into_iter()
                    .filter(|tool| {
                        self.run.agent_profile.permits(&tool.name)
                            && (self.run.permission_profile == "full_access"
                                || (tool.name == "computer_connector_call"
                                    && tool.input_schema.as_ref().is_some_and(
                                        agistack_adapters_cua::has_read_connector_operation,
                                    ))
                                || agistack_adapters_cua::tool_effects().get(tool.name.as_str())
                                    == Some(&agistack_adapters_cua::CuaToolEffect::Read))
                    })
                    .collect()
            })
            .unwrap_or_default()
    }
}
#[async_trait]
impl ToolHost for Host {
    fn list_tools(&self) -> Vec<String> {
        let mut tools = self.base.list_tools();
        tools.extend(self.native_tools().into_iter().map(|tool| tool.name));
        tools
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        self.native_tools()
            .into_iter()
            .find(|tool| tool.name == name)
            .or_else(|| self.base.tool_definition(name))
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
        self.call_with_content(tool, input)
            .await
            .map(|result| result.output_json)
    }
    async fn call_with_content(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        if !agistack_adapters_cua::tool_effects().contains_key(tool) {
            return self.base.call_with_content(tool, input).await;
        }
        let identity = CALL
            .try_with(Clone::clone)
            .ok()
            .filter(|identity| identity.tool == tool)
            .ok_or_else(|| CoreError::Tool("computer_use_engine_identity_required".into()))?;
        self.broker
            .request(&self.owner, &self.conversation, &self.run, &identity, input)
            .await
    }
}
pub(crate) fn policy(inner: Arc<dyn ToolExecutionPolicy>) -> Arc<dyn ToolExecutionPolicy> {
    Arc::new(InvocationPolicy { inner })
}
struct InvocationPolicy {
    inner: Arc<dyn ToolExecutionPolicy>,
}
#[async_trait]
impl ToolExecutionPolicy for InvocationPolicy {
    async fn before_execute(
        &self,
        context: &ToolPolicyContext<'_>,
        input: &str,
        schema: Option<&Value>,
    ) -> CoreResult<ToolPolicyDecision> {
        self.inner.before_execute(context, input, schema).await
    }
    async fn execute(
        &self,
        context: &ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input: &str,
    ) -> CoreResult<String> {
        self.execute_with_content(context, tools, input)
            .await
            .map(|result| result.output_json)
    }
    async fn execute_with_content(
        &self,
        context: &ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input: &str,
    ) -> CoreResult<ToolResult> {
        CALL.scope(
            CallIdentity {
                session_id: context.session_id.into(),
                round: context.round,
                tool: context.tool.into(),
            },
            self.inner.execute_with_content(context, tools, input),
        )
        .await
    }
    async fn transform_result(
        &self,
        context: &ToolPolicyContext<'_>,
        result: ToolPolicyResult,
    ) -> CoreResult<ToolPolicyResult> {
        self.inner.transform_result(context, result).await
    }
}
pub(crate) async fn finish(app: &AppState, bound: BoundRun, conversation: &str) {
    let _ = conversation;
    app.computer_use_devices
        .cancel_run(&bound.owner, &bound.run.run_id);
    if let Some(authority) = &app.computer_use_devices.authority {
        authority.finish(&bound.owner, &bound.run).await;
    }
}
