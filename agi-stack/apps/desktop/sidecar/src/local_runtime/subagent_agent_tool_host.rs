//! Synchronous, run-scoped SubAgent delegation for the desktop ReAct engine.
//!
//! The host exposes one structured `subagent` tool only when the selected
//! Agent's persisted spawn policy authorizes at least one active SubAgent in
//! the current project. Target selection is exact and structural; the model
//! decides which authorized target is appropriate for the task.

use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
    time::Instant,
};

use agistack_core::{
    agent::{react::ReActEngine, types::SessionStatus},
    ports::{CoreError, CoreResult, ToolHost},
};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::{json, Value};

use super::{
    authorized_tool_host, subagent_scope,
    tool_authority::{canonical_json_digest, ToolEffect, ToolMetadata},
};

pub(super) const SUBAGENT_TOOL_NAME: &str = "subagent";
const MAX_SELECTOR_BYTES: usize = 512;
const MAX_TASK_BYTES: usize = 64 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SubagentToolInput {
    #[serde(default)]
    subagent_id: Option<String>,
    #[serde(default)]
    subagent_name: Option<String>,
    task: String,
}

pub(super) trait SubagentLifecycleObserver: Send + Sync {
    fn on_started(
        &self,
        subagent_id: &str,
        subagent_name: &str,
        subagent_display_name: &str,
        task: &LifecyclePayloadMetadata,
    );

    fn on_completed(
        &self,
        subagent_id: &str,
        subagent_name: &str,
        subagent_display_name: &str,
        result: &LifecyclePayloadMetadata,
        success: bool,
        execution_time_ms: u64,
    );
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct LifecyclePayloadMetadata {
    pub(super) bytes: usize,
}

impl LifecyclePayloadMetadata {
    fn from_text(value: &str) -> Self {
        Self { bytes: value.len() }
    }
}

pub(super) struct SubagentToolTarget {
    id: String,
    name: String,
    display_name: String,
    identifiers: BTreeSet<String>,
    effect: ToolEffect,
    engine: ReActEngine,
    project_id: String,
    run_id: String,
    run_revision: u64,
}

impl SubagentToolTarget {
    pub(super) fn new(
        resource: Value,
        effect: ToolEffect,
        engine: ReActEngine,
        project_id: String,
        run_id: String,
        run_revision: u64,
    ) -> Result<Self, String> {
        if resource.get("status").and_then(Value::as_str) != Some("active")
            || resource.get("enabled").and_then(Value::as_bool) != Some(true)
            || !subagent_scope::is_visible_in_project(&resource, &project_id)
        {
            return Err("SubAgent target is not active in the current project".to_string());
        }
        let id = required_identifier(&resource, "id", "SubAgent")?;
        let name = required_identifier(&resource, "name", "SubAgent")?;
        let display_name =
            optional_identifier(&resource, "display_name")?.unwrap_or_else(|| name.clone());
        let identifiers = BTreeSet::from([id.clone(), name.clone(), display_name.clone()]);
        Ok(Self {
            id,
            name,
            display_name,
            identifiers,
            effect,
            engine,
            project_id,
            run_id,
            run_revision,
        })
    }

    async fn run(
        &self,
        task: &str,
        invocation: &authorized_tool_host::AuthorizedInvocationContext,
    ) -> CoreResult<String> {
        if invocation.run_id != self.run_id || invocation.run_revision != self.run_revision {
            return Err(CoreError::Tool(
                "SubAgent invocation authority does not match the active run".to_string(),
            ));
        }
        let digest = canonical_json_digest(&json!({
            "run_id": self.run_id,
            "run_revision": self.run_revision,
            "invocation_id": invocation.invocation_id,
            "subagent_id": self.id,
        }))
        .map_err(|error| CoreError::Tool(error.to_string()))?;
        let session_id = format!("local-subagent-{digest}");
        let state = self
            .engine
            .run(&session_id, task, Some(&self.project_id))
            .await
            .map_err(opaque_child_error)?;
        match state.status {
            SessionStatus::Finished => state.answer.ok_or_else(|| {
                CoreError::Tool("SubAgent completed without a final answer".to_string())
            }),
            SessionStatus::AwaitingInput => Err(CoreError::Tool(
                "SubAgent requires human input and cannot suspend a synchronous delegation"
                    .to_string(),
            )),
            SessionStatus::Paused => Err(CoreError::Tool(
                "SubAgent paused before completing the delegated task".to_string(),
            )),
            SessionStatus::Failed => Err(CoreError::Tool(
                "SubAgent failed before completing the delegated task".to_string(),
            )),
            SessionStatus::Cancelled => Err(CoreError::Tool(
                "SubAgent delegation was cancelled".to_string(),
            )),
            SessionStatus::Running => Err(CoreError::Tool(
                "SubAgent returned while still running".to_string(),
            )),
        }
    }
}

pub(super) struct SubagentAgentToolHost {
    targets: Vec<SubagentToolTarget>,
    metadata: ToolMetadata,
    lifecycle_observer: Option<Arc<dyn SubagentLifecycleObserver>>,
}

impl SubagentAgentToolHost {
    pub(super) fn new(targets: Vec<SubagentToolTarget>) -> Result<Self, String> {
        if targets.is_empty() {
            return Err("SubAgent tool requires at least one authorized target".to_string());
        }
        let mut ids = BTreeSet::new();
        for target in &targets {
            if !ids.insert(target.id.as_str()) {
                return Err("SubAgent tool target ids must be unique".to_string());
            }
        }
        let effect = if targets
            .iter()
            .any(|target| target.effect == ToolEffect::Mutate)
        {
            ToolEffect::Mutate
        } else {
            ToolEffect::Read
        };
        Ok(Self {
            targets,
            metadata: ToolMetadata {
                name: SUBAGENT_TOOL_NAME.to_string(),
                effect,
                sensitive_input_fields: BTreeSet::from([
                    "subagent_id".to_string(),
                    "subagent_name".to_string(),
                    "task".to_string(),
                ]),
            },
            lifecycle_observer: None,
        })
    }

    pub(super) fn with_lifecycle_observer(
        mut self,
        lifecycle_observer: Arc<dyn SubagentLifecycleObserver>,
    ) -> Self {
        self.lifecycle_observer = Some(lifecycle_observer);
        self
    }

    pub(super) fn authority_metadata_by_name(&self) -> BTreeMap<String, ToolMetadata> {
        BTreeMap::from([(SUBAGENT_TOOL_NAME.to_string(), self.metadata.clone())])
    }

    fn resolve(&self, input: &SubagentToolInput) -> CoreResult<(&SubagentToolTarget, String)> {
        let subagent_id = input
            .subagent_id
            .as_deref()
            .map(validated_selector)
            .transpose()?;
        let subagent_name = input
            .subagent_name
            .as_deref()
            .map(validated_selector)
            .transpose()?;
        if subagent_id.is_none() && subagent_name.is_none() {
            return Err(CoreError::Tool(
                "subagent requires subagent_id or subagent_name".to_string(),
            ));
        }
        let matches = self
            .targets
            .iter()
            .filter(|target| {
                subagent_id
                    .as_ref()
                    .map_or(true, |subagent_id| target.id == *subagent_id)
                    && subagent_name.as_ref().map_or(true, |subagent_name| {
                        target.identifiers.contains(subagent_name)
                    })
            })
            .collect::<Vec<_>>();
        let [target] = matches.as_slice() else {
            return Err(CoreError::Tool(
                "subagent target is not uniquely authorized for this run".to_string(),
            ));
        };
        let task = input.task.trim();
        if task.is_empty() || task.len() > MAX_TASK_BYTES || task.chars().any(|value| value == '\0')
        {
            return Err(CoreError::Tool(
                "subagent task must be a non-empty bounded string".to_string(),
            ));
        }
        Ok((target, task.to_string()))
    }
}

#[async_trait]
impl ToolHost for SubagentAgentToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec![SUBAGENT_TOOL_NAME.to_string()]
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        if tool != SUBAGENT_TOOL_NAME {
            return Err(CoreError::Tool(format!("unknown SubAgent tool: {tool}")));
        }
        let input: SubagentToolInput = serde_json::from_str(input_json)
            .map_err(|error| CoreError::Tool(format!("invalid subagent input: {error}")))?;
        let (target, task) = self.resolve(&input)?;
        let invocation =
            authorized_tool_host::current_authorized_invocation_context().ok_or_else(|| {
                CoreError::Tool(
                    "SubAgent execution requires an authorized invocation context".to_string(),
                )
            })?;
        let task_metadata = LifecyclePayloadMetadata::from_text(&task);
        if let Some(observer) = self.lifecycle_observer.as_ref() {
            observer.on_started(
                &target.id,
                &target.name,
                &target.display_name,
                &task_metadata,
            );
        }
        let started_at = Instant::now();
        let content = match target.run(&task, &invocation).await {
            Ok(content) => {
                let result_metadata = LifecyclePayloadMetadata::from_text(&content);
                if let Some(observer) = self.lifecycle_observer.as_ref() {
                    observer.on_completed(
                        &target.id,
                        &target.name,
                        &target.display_name,
                        &result_metadata,
                        true,
                        elapsed_millis(started_at),
                    );
                }
                content
            }
            Err(error) => {
                let result_metadata = LifecyclePayloadMetadata::from_text(&error.to_string());
                if let Some(observer) = self.lifecycle_observer.as_ref() {
                    observer.on_completed(
                        &target.id,
                        &target.name,
                        &target.display_name,
                        &result_metadata,
                        false,
                        elapsed_millis(started_at),
                    );
                }
                return Err(error);
            }
        };
        serde_json::to_string(&json!({
            "subagent_id": target.id,
            "subagent_name": target.name,
            "subagent_display_name": target.display_name,
            "status": "completed",
            "content": content,
        }))
        .map_err(|error| CoreError::Tool(error.to_string()))
    }
}

fn elapsed_millis(started_at: Instant) -> u64 {
    u64::try_from(started_at.elapsed().as_millis()).unwrap_or(u64::MAX)
}

fn opaque_child_error(_error: CoreError) -> CoreError {
    CoreError::Tool("SubAgent execution failed".to_string())
}

pub(super) fn authorized_subagent_resources(
    agent: &Value,
    resources: &[Value],
    project_id: &str,
) -> Result<Vec<Value>, String> {
    let can_spawn = agent
        .get("can_spawn")
        .and_then(Value::as_bool)
        .ok_or_else(|| "agent can_spawn is required".to_string())?;
    if !can_spawn {
        return Ok(Vec::new());
    }
    let allowed = agent
        .pointer("/spawn_policy/allowed_subagents")
        .ok_or_else(|| "agent spawn_policy.allowed_subagents is required".to_string())?;
    let allowed = allowed_identifiers(allowed)?;
    Ok(resources
        .iter()
        .filter(|resource| {
            resource.get("status").and_then(Value::as_str) == Some("active")
                && resource.get("enabled").and_then(Value::as_bool) == Some(true)
                && subagent_scope::is_visible_in_project(resource, project_id)
                && resource_identifiers(resource).is_some_and(|identifiers| {
                    allowed.as_ref().map_or(true, |allowed| {
                        allowed.contains("*")
                            || identifiers
                                .iter()
                                .any(|identifier| allowed.contains(identifier))
                    })
                })
        })
        .cloned()
        .collect())
}

pub(super) fn effect_for_execution_profile(
    allowed_tools: &[String],
    allowed_mcp_servers: &[String],
) -> ToolEffect {
    if !allowed_mcp_servers.is_empty()
        || allowed_tools.iter().any(|tool| {
            authorized_tool_host::tool_metadata(tool)
                .map_or(true, |metadata| metadata.effect == ToolEffect::Mutate)
        })
    {
        ToolEffect::Mutate
    } else {
        ToolEffect::Read
    }
}

fn allowed_identifiers(value: &Value) -> Result<Option<BTreeSet<String>>, String> {
    if value.is_null() {
        return Ok(None);
    }
    let values = value.as_array().ok_or_else(|| {
        "agent spawn_policy.allowed_subagents must be null or a string array".to_string()
    })?;
    values
        .iter()
        .map(|value| {
            let value = value.as_str().ok_or_else(|| {
                "agent spawn_policy.allowed_subagents must contain strings".to_string()
            })?;
            validated_identifier(value, "agent spawn_policy.allowed_subagents")
        })
        .collect::<Result<BTreeSet<_>, _>>()
        .map(Some)
}

fn resource_identifiers(resource: &Value) -> Option<BTreeSet<String>> {
    ["id", "name", "display_name"]
        .into_iter()
        .filter_map(|field| resource.get(field).and_then(Value::as_str))
        .map(|value| validated_identifier(value, "SubAgent identity"))
        .collect::<Result<BTreeSet<_>, _>>()
        .ok()
        .filter(|identifiers| !identifiers.is_empty())
}

fn required_identifier(value: &Value, field: &str, kind: &str) -> Result<String, String> {
    let raw = value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{kind} {field} is required"))?;
    validated_identifier(raw, &format!("{kind} {field}"))
}

fn optional_identifier(value: &Value, field: &str) -> Result<Option<String>, String> {
    value
        .get(field)
        .filter(|value| !value.is_null())
        .map(|value| {
            value
                .as_str()
                .ok_or_else(|| format!("SubAgent {field} must be a string"))
                .and_then(|value| validated_identifier(value, &format!("SubAgent {field}")))
        })
        .transpose()
}

fn validated_identifier(value: &str, field: &str) -> Result<String, String> {
    let trimmed = value.trim();
    if trimmed.is_empty()
        || trimmed != value
        || trimmed.len() > MAX_SELECTOR_BYTES
        || trimmed.chars().any(char::is_control)
    {
        return Err(format!("{field} must be a bounded non-empty identifier"));
    }
    Ok(trimmed.to_string())
}

fn validated_selector(value: &str) -> CoreResult<String> {
    validated_identifier(value, "subagent selector").map_err(CoreError::Tool)
}

#[cfg(test)]
mod tests;
