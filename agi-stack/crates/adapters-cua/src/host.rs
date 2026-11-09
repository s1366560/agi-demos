//! Scoped tool contracts and ownership-checked model media for computer use.
use crate::{
    catalog::*,
    client::{CuaCallContext, CuaClient},
};
use agistack_core::{
    agent::types::MediaAttachment,
    ports::{ToolHost, ToolResult},
    tool_definition::ToolDefinition,
    CoreError, CoreResult,
};
use async_trait::async_trait;
use serde_json::{json, Value};
use std::{collections::BTreeMap, path::PathBuf, sync::Arc};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CuaToolEffect {
    Read,
    Mutate,
}

/// Validate model arguments before any target resolution, consent or connector dispatch.
pub fn validate_tool_input(tool: &str, input: &Value) -> CoreResult<()> {
    if !input.is_object()
        || input.get("_cua_call_id").is_some()
        || input.get("_cua_expected_identity").is_some()
    {
        return Err(CoreError::Tool(
            "cua_invalid_params: model arguments cannot contain host identity".into(),
        ));
    }
    let definitions = tool_definitions();
    let definition = definitions
        .get(tool)
        .ok_or_else(|| CoreError::Tool(format!("unknown computer-use tool: {tool}")))?;
    let validator = jsonschema::draft202012::new(&definition["inputSchema"])
        .map_err(|_| CoreError::Tool("cua_invalid_schema".into()))?;
    if !validator.is_valid(input) {
        return Err(CoreError::Tool(
            "cua_invalid_params: input violates tool schema".into(),
        ));
    }
    validate_bounds(tool, input)?;
    if input
        .get("app")
        .and_then(Value::as_str)
        .is_some_and(target_is_forbidden)
    {
        return Err(CoreError::Tool("cua_target_forbidden".into()));
    }
    Ok(())
}

pub struct CuaToolHost {
    client: Arc<CuaClient>,
    context: Option<CuaCallContext>,
    definitions: BTreeMap<&'static str, Value>,
}
impl CuaToolHost {
    pub fn new(client: Arc<CuaClient>) -> Self {
        Self {
            client,
            context: None,
            definitions: tool_definitions(),
        }
    }
    #[must_use]
    pub fn with_context(mut self, context: CuaCallContext) -> Self {
        self.context = Some(context);
        self
    }
    fn context(&self) -> CoreResult<&CuaCallContext> {
        self.context
            .as_ref()
            .ok_or_else(|| CoreError::Tool("cua_session_required".into()))
    }
    pub async fn resolve_target(&self, app: &str) -> CoreResult<Value> {
        self.client
            .request_in_session(self.context()?, "resolve_app", json!({"app":app}))
            .await
            .map_err(Into::into)
    }
    /// Read-only preflight for the durable side-effect admission boundary.
    /// The actual dispatch still consumes the snapshot and checks the native target.
    pub async fn validate_observed_action(&self, tool: &str, input: &Value) -> CoreResult<()> {
        if !matches!(
            tool,
            TOOL_CLICK
                | TOOL_TYPE_TEXT
                | TOOL_PRESS_KEY
                | TOOL_SCROLL
                | TOOL_SET_VALUE
                | TOOL_DRAG
                | TOOL_SECONDARY_ACTION
                | TOOL_PASTE
                | "computer_select_text"
                | "computer_key_down"
                | "computer_key_up"
                | "computer_move"
                | "computer_drag_step"
        ) {
            return Ok(());
        }
        let mut action = input
            .as_object()
            .cloned()
            .ok_or_else(|| CoreError::Tool("cua_invalid_params".into()))?;
        let app = action.remove("app");
        let snapshot = action.remove("snapshot_id");
        let window = action.remove("window_id");
        let mut params =
            json!({"app":app,"window_id":window,"snapshot_id":snapshot,"action":action});
        self.client
            .validate_observed_action(self.context()?, &mut params)
            .await
    }
    async fn execute(&self, tool: &str, input_json: &str) -> CoreResult<ToolResult> {
        let mut input: Value = serde_json::from_str(if input_json.trim().is_empty() {
            "{}"
        } else {
            input_json
        })
        .map_err(|_| CoreError::Tool("cua_invalid_params: invalid JSON".into()))?;
        let object = input
            .as_object_mut()
            .ok_or_else(|| CoreError::Tool("cua_invalid_params: object required".into()))?;
        let call_id = object.remove("_cua_call_id");
        let expected_identity = object.remove("_cua_expected_identity");
        validate_tool_input(tool, &input)?;
        let requested_app = input["app"].as_str().map(str::to_owned);
        let (method, mut params) = match tool {
            TOOL_LIST_APPS => ("list_apps", input),
            TOOL_GET_APP_STATE => ("get_app_state", input),
            "computer_locked_use" => (
                if input["enabled"] == true {
                    "locked_use_enable"
                } else {
                    "locked_use_disable"
                },
                input,
            ),
            _ if crate::extra_tools::method(tool).is_some() => (
                crate::extra_tools::method(tool).expect("declared method"),
                input,
            ),
            _ => {
                let kind = match tool {
                    TOOL_CLICK => "click",
                    TOOL_TYPE_TEXT => "type_text",
                    TOOL_PRESS_KEY => "press_key",
                    TOOL_SCROLL => "scroll",
                    TOOL_SET_VALUE => "set_value",
                    TOOL_DRAG => "drag",
                    TOOL_SECONDARY_ACTION => "secondary_action",
                    TOOL_PASTE => "paste",
                    "computer_select_text" => "select_text",
                    "computer_key_down" => "key_down",
                    "computer_key_up" => "key_up",
                    "computer_move" => "move",
                    "computer_drag_step" => "drag_step",
                    _ => return Err(CoreError::Tool("cua_unknown_action".into())),
                };
                let mut action = input
                    .as_object()
                    .cloned()
                    .ok_or_else(|| CoreError::Tool("cua_invalid_params".into()))?;
                let app = action.remove("app");
                let snapshot = action.remove("snapshot_id");
                let window = action.remove("window_id");
                action.insert("kind".into(), json!(kind));
                (
                    "perform_action",
                    json!({"app":app,"window_id":window,"snapshot_id":snapshot,"action":action}),
                )
            }
        };
        if let Some(call_id) = call_id {
            params["request_id"] = call_id;
        }
        if let Some(identity) = expected_identity {
            params["expected_identity_digest"] = identity;
        }
        let context = self.context()?;
        if method == "perform_action" {
            self.client.normalize_action(context, &mut params).await?;
        }
        let mut output = self
            .client
            .request_in_session(context, method, params)
            .await?;
        let mut media = Vec::new();
        let mut image_size = None;
        if let Some(icon) = output.get("app_icon").filter(|v| v.is_object()) {
            let url = icon["url"]
                .as_str()
                .ok_or_else(|| CoreError::Tool("cua_icon_invalid".into()))?;
            let path = self.owned_artifact(url).await?;
            if icon["mime_type"] != "image/png" || icon["kind"] != "app_icon" {
                return Err(CoreError::Tool("cua_icon_invalid".into()));
            }
            let dimensions = tokio::task::spawn_blocking(move || image::image_dimensions(path))
                .await
                .map_err(|_| CoreError::Tool("cua_icon_invalid".into()))?
                .map_err(|_| CoreError::Tool("cua_icon_invalid".into()))?;
            if dimensions != (64, 64) || icon["width"] != 64 || icon["height"] != 64 {
                return Err(CoreError::Tool("cua_icon_invalid".into()));
            }
            // Decorative identity metadata deliberately stays out of model media.
        }
        if tool == TOOL_GET_APP_STATE {
            crate::ax_tree::validate_output(&output)?;
            // Icons are a UI decoration and must not carry base64 into transcripts.
            if let Some(object) = output.as_object_mut() {
                object.remove("icon");
            }
            if let Some(screenshot) = output.get_mut("screenshot").filter(|v| v.is_object()) {
                if let Some(object) = screenshot.as_object_mut() {
                    object.remove("data_url");
                }
                if let Some(url) = screenshot.get("url").and_then(Value::as_str) {
                    let path = self.owned_artifact(url).await?;
                    let mime = screenshot
                        .get("mime_type")
                        .and_then(Value::as_str)
                        .unwrap_or("image/png")
                        .to_owned();
                    if !matches!(mime.as_str(), "image/png" | "image/jpeg" | "image/webp") {
                        return Err(CoreError::Tool("cua_invalid_image_type".into()));
                    }
                    let dimensions_path = path.clone();
                    let dimensions = tokio::task::spawn_blocking(move || {
                        image::image_dimensions(dimensions_path)
                    })
                    .await
                    .map_err(|_| CoreError::Tool("cua_image_dimension_probe_failed".into()))?
                    .map_err(|_| CoreError::Tool("cua_invalid_image".into()))?;
                    if dimensions.0 == 0
                        || dimensions.1 == 0
                        || dimensions.0 > 1_000_000
                        || dimensions.1 > 1_000_000
                    {
                        return Err(CoreError::Tool("cua_invalid_image_dimensions".into()));
                    }
                    for (key, actual) in [("width", dimensions.0), ("height", dimensions.1)] {
                        if screenshot[key]
                            .as_u64()
                            .is_some_and(|declared| declared != actual as u64)
                        {
                            return Err(CoreError::Tool("cua_image_dimension_mismatch".into()));
                        }
                        screenshot[key] = json!(actual);
                    }
                    image_size = Some(dimensions);
                    media.push(MediaAttachment {
                        artifact_path: path.to_string_lossy().into_owned(),
                        mime_type: mime,
                    });
                }
            }
        }
        if tool == TOOL_GET_APP_STATE {
            let observation = crate::coordinates::ObservationCoordinates::new(
                context.clone(),
                requested_app
                    .as_deref()
                    .ok_or_else(|| CoreError::Tool("cua_observation_app_missing".into()))?,
                &output,
                image_size,
            )?;
            output["coordinate_spaces"] = observation.declaration();
            self.client.remember_observation(observation).await?;
        }
        Ok(ToolResult {
            control_outcome: None,
            control_generation: None,
            permission_required: None,
            output_json: output.to_string(),
            media,
        })
    }
    async fn owned_artifact(&self, url: &str) -> CoreResult<PathBuf> {
        let path = url::Url::parse(url)
            .ok()
            .and_then(|url| url.to_file_path().ok())
            .ok_or_else(|| CoreError::Tool("cua_invalid_artifact_url".into()))?;
        let root = self
            .client
            .session_artifact_root(&self.context()?.session_id)
            .await
            .ok_or_else(|| CoreError::Tool("cua_artifact_owner_missing".into()))?;
        let root = tokio::fs::canonicalize(root)
            .await
            .map_err(|_| CoreError::Tool("cua_artifact_root_missing".into()))?;
        let metadata = tokio::fs::symlink_metadata(&path)
            .await
            .map_err(|_| CoreError::Tool("cua_artifact_missing".into()))?;
        let canonical = tokio::fs::canonicalize(&path)
            .await
            .map_err(|_| CoreError::Tool("cua_artifact_missing".into()))?;
        if !canonical.starts_with(&root)
            || metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() > 8 * 1024 * 1024
        {
            return Err(CoreError::Tool(
                "cua_artifact_not_owned_or_too_large".into(),
            ));
        }
        Ok(canonical)
    }
}
#[async_trait]
impl ToolHost for CuaToolHost {
    fn list_tools(&self) -> Vec<String> {
        tool_names().into_iter().map(str::to_string).collect()
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        let raw = self.definitions.get(name)?;
        Some(ToolDefinition {
            name: name.into(),
            description: raw["description"].as_str().map(str::to_string),
            input_schema: Some(raw["inputSchema"].clone()),
        })
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        Ok(self.execute(tool, input_json).await?.output_json)
    }
    async fn call_with_content(&self, tool: &str, input_json: &str) -> CoreResult<ToolResult> {
        self.execute(tool, input_json).await
    }
}
fn target_is_forbidden(app: &str) -> bool {
    matches!(
        app.trim().to_lowercase().as_str(),
        "com.apple.keychainaccess"
            | "com.apple.passwords"
            | "com.apple.systempreferences"
            | "keychain access"
            | "passwords"
            | "system settings"
            | "system preferences"
    )
}
fn validate_bounds(tool: &str, input: &Value) -> CoreResult<()> {
    for key in ["x", "y", "from_x", "from_y", "to_x", "to_y"] {
        if input.get(key).is_some_and(|v| {
            v.as_f64()
                .is_none_or(|n| !n.is_finite() || n.abs() > 1_000_000.0)
        }) {
            return Err(CoreError::Tool(
                "cua_invalid_params: coordinate out of range".into(),
            ));
        }
    }
    if input
        .get("element_index")
        .is_some_and(|v| v.as_u64().is_none())
    {
        return Err(CoreError::Tool(
            "cua_invalid_params: nonnegative index required".into(),
        ));
    }
    if input.get("pages").is_some_and(|v| {
        v.as_f64()
            .is_none_or(|n| !n.is_finite() || n <= 0.0 || n > 1000.0)
    }) {
        return Err(CoreError::Tool(
            "cua_invalid_params: pages out of range".into(),
        ));
    }
    if matches!(tool, TOOL_CLICK | TOOL_SCROLL)
        && input.get("element_index").is_none()
        && !(input.get("x").is_some() && input.get("y").is_some())
    {
        return Err(CoreError::Tool(
            "cua_invalid_params: element or complete coordinates required".into(),
        ));
    }
    Ok(())
}
