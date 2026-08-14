use std::{collections::BTreeSet, sync::Arc};

use agistack_core::{
    agent::types::{AgentAction, TranscriptEntry},
    model::{Episode, Memory},
    ports::{CoreError, CoreResult, LlmPort, MemoryDraft, RelationshipDraft, ToolHost},
};
use async_trait::async_trait;
use serde_json::Value;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct SelectedResource {
    pub(super) id: String,
    pub(super) name: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct ExecutionProfile {
    pub(super) agent: SelectedResource,
    pub(super) skill: Option<SelectedResource>,
    pub(super) subagent: Option<SelectedResource>,
    pub(super) allowed_tools: Vec<String>,
    pub(super) allowed_mcp_servers: Vec<String>,
    pub(super) instructions: String,
}

impl ExecutionProfile {
    pub(super) fn resolve(
        agent_id: &str,
        agent: &Value,
        skill: Option<&Value>,
        subagent: Option<&Value>,
    ) -> Result<Self, String> {
        ensure_available(agent, "agent", true)?;
        let agent_resource = resource_identity(agent, agent_id, "agent")?;
        let mut tools = required_string_set(agent, "allowed_tools", "agent")?;
        let mut skills = required_string_set(agent, "allowed_skills", "agent")?;
        let mut mcp_servers = required_string_set(agent, "allowed_mcp_servers", "agent")?;
        let mut instruction_sections = Vec::new();
        push_instruction(
            &mut instruction_sections,
            "Agent instructions",
            agent.get("system_prompt").and_then(Value::as_str),
        );

        let selected_skill = if let Some(skill) = skill {
            ensure_available(skill, "skill", false)?;
            let identity = resource_identity(skill, "", "skill")?;
            if !set_allows(&skills, &identity.id) && !set_allows(&skills, &identity.name) {
                return Err(format!("skill is not allowed by agent: {}", identity.id));
            }
            let skill_tools = required_string_set(skill, "tools", "skill")?;
            tools = intersect_authority(&tools, &skill_tools);
            push_instruction(
                &mut instruction_sections,
                "Selected skill",
                skill
                    .get("full_content")
                    .or_else(|| skill.get("skill_md_content"))
                    .or_else(|| skill.get("description"))
                    .and_then(Value::as_str),
            );
            Some(identity)
        } else {
            None
        };

        let selected_subagent = if let Some(subagent) = subagent {
            if agent.get("can_spawn").and_then(Value::as_bool) != Some(true) {
                return Err("selected agent cannot spawn Sub Agents".to_string());
            }
            ensure_available(subagent, "Sub Agent", true)?;
            let identity = resource_identity(subagent, "", "Sub Agent")?;
            let allowed_subagents = agent
                .pointer("/spawn_policy/allowed_subagents")
                .ok_or_else(|| "agent spawn_policy.allowed_subagents is required".to_string())
                .and_then(subagent_allowlist)?;
            if !set_allows(&allowed_subagents, &identity.id)
                && !set_allows(&allowed_subagents, &identity.name)
            {
                return Err(format!(
                    "Sub Agent is not allowed by agent spawn policy: {}",
                    identity.id
                ));
            }
            tools = intersect_authority(
                &tools,
                &required_string_set(subagent, "allowed_tools", "Sub Agent")?,
            );
            skills = intersect_authority(
                &skills,
                &required_string_set(subagent, "allowed_skills", "Sub Agent")?,
            );
            mcp_servers = intersect_authority(
                &mcp_servers,
                &required_string_set(subagent, "allowed_mcp_servers", "Sub Agent")?,
            );
            if let Some(skill) = selected_skill.as_ref() {
                if !set_allows(&skills, &skill.id) && !set_allows(&skills, &skill.name) {
                    return Err(format!("skill is not allowed by Sub Agent: {}", skill.id));
                }
            }
            push_instruction(
                &mut instruction_sections,
                "Sub Agent instructions",
                subagent.get("system_prompt").and_then(Value::as_str),
            );
            Some(identity)
        } else {
            None
        };

        if tools.is_empty() {
            return Err("selected Agent, Skill, and Sub Agent have no shared tools".to_string());
        }

        Ok(Self {
            agent: agent_resource,
            skill: selected_skill,
            subagent: selected_subagent,
            allowed_tools: tools.into_iter().collect(),
            allowed_mcp_servers: mcp_servers.into_iter().collect(),
            instructions: instruction_sections.join("\n\n"),
        })
    }
}

fn ensure_available(value: &Value, kind: &str, enabled_required: bool) -> Result<(), String> {
    let status = value
        .get("status")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{kind} status is required"))?;
    if status != "active" {
        return Err(format!("selected {kind} is not active"));
    }
    if enabled_required && value.get("enabled").and_then(Value::as_bool) != Some(true) {
        return Err(format!("selected {kind} is not enabled"));
    }
    Ok(())
}

fn resource_identity(
    value: &Value,
    expected_id: &str,
    kind: &str,
) -> Result<SelectedResource, String> {
    let id = required_string(value, "id", kind)?;
    if !expected_id.is_empty() && id != expected_id {
        return Err(format!(
            "selected {kind} id does not match execution selection"
        ));
    }
    Ok(SelectedResource {
        name: required_string(value, "name", kind)?,
        id,
    })
}

fn required_string(value: &Value, field: &str, kind: &str) -> Result<String, String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| format!("{kind} {field} is required"))
}

fn required_string_set(value: &Value, field: &str, kind: &str) -> Result<BTreeSet<String>, String> {
    let value = value
        .get(field)
        .ok_or_else(|| format!("{kind} {field} is required"))?;
    string_set(value, &format!("{kind} {field}"))
}

fn string_set(value: &Value, field: &str) -> Result<BTreeSet<String>, String> {
    let values = value
        .as_array()
        .ok_or_else(|| format!("{field} must be a string array"))?;
    values
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(str::to_string)
                .ok_or_else(|| format!("{field} must contain non-empty strings"))
        })
        .collect()
}

fn subagent_allowlist(value: &Value) -> Result<BTreeSet<String>, String> {
    if value.is_null() {
        return Ok(BTreeSet::from(["*".to_string()]));
    }
    string_set(value, "agent spawn_policy.allowed_subagents")
}

fn set_allows(values: &BTreeSet<String>, candidate: &str) -> bool {
    values.contains("*") || values.contains(candidate)
}

fn intersect_authority(parent: &BTreeSet<String>, child: &BTreeSet<String>) -> BTreeSet<String> {
    match (parent.contains("*"), child.contains("*")) {
        (true, true) => BTreeSet::from(["*".to_string()]),
        (true, false) => child.clone(),
        (false, true) => parent.clone(),
        (false, false) => parent.intersection(child).cloned().collect(),
    }
}

fn push_instruction(sections: &mut Vec<String>, label: &str, instruction: Option<&str>) {
    if let Some(instruction) = instruction.map(str::trim).filter(|value| !value.is_empty()) {
        sections.push(format!("[{label}]\n{instruction}"));
    }
}

pub(super) struct ProfiledToolHost {
    inner: Arc<dyn ToolHost>,
    allowed_tools: BTreeSet<String>,
}

impl ProfiledToolHost {
    pub(super) fn new(inner: Arc<dyn ToolHost>, profile: &ExecutionProfile) -> Self {
        Self {
            inner,
            allowed_tools: profile.allowed_tools.iter().cloned().collect(),
        }
    }

    fn allows(&self, tool: &str) -> bool {
        self.allowed_tools.contains("*") || self.allowed_tools.contains(tool)
    }
}

#[async_trait]
impl ToolHost for ProfiledToolHost {
    fn list_tools(&self) -> Vec<String> {
        let mut advertised = self
            .inner
            .list_tools()
            .into_iter()
            .filter(|tool| self.allows(tool))
            .collect::<Vec<_>>();
        if self.allowed_tools.contains("*") {
            return advertised;
        }
        let mut seen = advertised.iter().cloned().collect::<BTreeSet<_>>();
        for tool in &self.allowed_tools {
            if !seen.contains(tool) && self.inner.can_dispatch(tool) {
                seen.insert(tool.clone());
                advertised.push(tool.clone());
            }
        }
        advertised
    }

    fn can_dispatch(&self, tool: &str) -> bool {
        self.allows(tool) && self.inner.can_dispatch(tool)
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        if !self.can_dispatch(tool) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' is not allowed by the selected execution profile"
            )));
        }
        self.inner.call(tool, input_json).await
    }
}

pub(super) struct ProfiledLlm {
    inner: Arc<dyn LlmPort>,
    instructions: String,
}

impl ProfiledLlm {
    pub(super) fn new(inner: Arc<dyn LlmPort>, profile: &ExecutionProfile) -> Self {
        Self {
            inner,
            instructions: profile.instructions.clone(),
        }
    }

    fn goal(&self, goal: &str) -> String {
        if self.instructions.is_empty() {
            return goal.to_string();
        }
        format!(
            "[Authoritative execution profile]\n{}\n\n[User goal]\n{goal}",
            self.instructions
        )
    }
}

#[async_trait]
impl LlmPort for ProfiledLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.inner.extract_memory(episode).await
    }

    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        self.inner.extract_relationships(memory).await
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        self.inner
            .decide(&self.goal(goal), round, transcript, available_tools)
            .await
    }
}

#[cfg(test)]
mod tests {
    use agistack_core::ports::ToolHost;
    use serde_json::json;

    use super::*;

    fn all_access_agent() -> serde_json::Value {
        json!({
            "id": "builtin:all-access",
            "name": "Local Agent",
            "system_prompt": "Coordinate the selected resources.",
            "enabled": true,
            "status": "active",
            "allowed_tools": ["*"],
            "allowed_skills": ["*"],
            "allowed_mcp_servers": ["*"],
            "can_spawn": true,
            "spawn_policy": { "allowed_subagents": ["*"] }
        })
    }

    #[test]
    fn execution_profile_fails_closed_when_agent_authority_fields_are_missing() {
        let mut agent = all_access_agent();
        agent.as_object_mut().unwrap().remove("allowed_tools");

        let error =
            ExecutionProfile::resolve("builtin:all-access", &agent, None, None).unwrap_err();

        assert!(error.contains("allowed_tools"));
    }

    #[test]
    fn selected_skill_and_subagent_only_narrow_agent_authority() {
        let skill = json!({
            "id": "code-exploration",
            "name": "Code exploration",
            "status": "active",
            "tools": ["read", "grep", "write"],
            "full_content": "Inspect before changing anything."
        });
        let subagent = json!({
            "id": "qa-reviewer",
            "name": "qa-reviewer",
            "display_name": "QA Reviewer",
            "enabled": true,
            "status": "active",
            "system_prompt": "Verify with direct evidence.",
            "allowed_tools": ["read", "grep"],
            "allowed_skills": ["code-exploration"],
            "allowed_mcp_servers": ["gitnexus"]
        });

        let profile = ExecutionProfile::resolve(
            "builtin:all-access",
            &all_access_agent(),
            Some(&skill),
            Some(&subagent),
        )
        .unwrap();

        assert_eq!(profile.allowed_tools, ["grep", "read"]);
        assert_eq!(profile.allowed_mcp_servers, ["gitnexus"]);
        assert_eq!(profile.skill.as_ref().unwrap().id, "code-exploration");
        assert_eq!(profile.subagent.as_ref().unwrap().id, "qa-reviewer");
        assert!(profile
            .instructions
            .contains("Inspect before changing anything."));
        assert!(profile
            .instructions
            .contains("Verify with direct evidence."));
    }

    #[test]
    fn null_subagent_allowlist_is_unrestricted() {
        let mut agent = all_access_agent();
        agent["spawn_policy"]["allowed_subagents"] = Value::Null;
        let subagent = json!({
            "id": "qa-reviewer",
            "name": "qa-reviewer",
            "enabled": true,
            "status": "active",
            "allowed_tools": ["read"],
            "allowed_skills": [],
            "allowed_mcp_servers": []
        });

        let profile =
            ExecutionProfile::resolve("builtin:all-access", &agent, None, Some(&subagent))
                .expect("null SubAgent allow-list must authorize every visible SubAgent");

        assert_eq!(
            profile.subagent.as_ref().map(|item| item.id.as_str()),
            Some("qa-reviewer")
        );
        assert_eq!(profile.allowed_tools, ["read"]);
    }

    #[test]
    fn selected_skill_and_subagent_require_explicit_agent_authority() {
        let mut agent = all_access_agent();
        agent["allowed_skills"] = json!([]);
        agent["can_spawn"] = json!(false);
        agent["spawn_policy"] = json!({ "allowed_subagents": [] });
        let skill = json!({
            "id": "code-exploration",
            "name": "Code exploration",
            "status": "active",
            "tools": ["read"]
        });
        let subagent = json!({
            "id": "qa-reviewer",
            "name": "qa-reviewer",
            "enabled": true,
            "status": "active",
            "allowed_tools": ["read"],
            "allowed_skills": [],
            "allowed_mcp_servers": []
        });

        assert!(
            ExecutionProfile::resolve("builtin:all-access", &agent, Some(&skill), None,)
                .unwrap_err()
                .contains("skill is not allowed")
        );
        assert!(
            ExecutionProfile::resolve("builtin:all-access", &agent, None, Some(&subagent),)
                .unwrap_err()
                .contains("cannot spawn")
        );
    }

    #[test]
    fn selected_skill_and_subagent_fail_when_their_tool_authorities_do_not_overlap() {
        let skill = json!({
            "id": "code-exploration",
            "name": "Code exploration",
            "status": "active",
            "tools": ["read", "grep"]
        });
        let subagent = json!({
            "id": "workspace-inspector",
            "name": "workspace-inspector",
            "enabled": true,
            "status": "active",
            "allowed_tools": ["list"],
            "allowed_skills": ["code-exploration"],
            "allowed_mcp_servers": []
        });

        let error = ExecutionProfile::resolve(
            "builtin:all-access",
            &all_access_agent(),
            Some(&skill),
            Some(&subagent),
        )
        .expect_err("disjoint tool authorities must fail closed");

        assert!(error.contains("no shared tools"));
    }

    struct StubToolHost;

    #[async_trait]
    impl ToolHost for StubToolHost {
        fn list_tools(&self) -> Vec<String> {
            vec!["read".to_string(), "write".to_string()]
        }

        async fn call(&self, tool: &str, _input_json: &str) -> CoreResult<String> {
            Ok(tool.to_string())
        }
    }

    struct HiddenAliasToolHost;

    #[async_trait]
    impl ToolHost for HiddenAliasToolHost {
        fn list_tools(&self) -> Vec<String> {
            vec!["mcp__readable".to_string()]
        }

        fn can_dispatch(&self, tool: &str) -> bool {
            matches!(tool, "mcp__readable" | "mcp__legacy")
        }

        async fn call(&self, tool: &str, _input_json: &str) -> CoreResult<String> {
            if self.can_dispatch(tool) {
                Ok(tool.to_string())
            } else {
                Err(CoreError::Tool(format!("unknown tool: {tool}")))
            }
        }
    }

    struct RecordingLlm {
        goal: std::sync::Mutex<Option<String>>,
    }

    #[async_trait]
    impl LlmPort for RecordingLlm {
        async fn extract_memory(&self, _episode: &Episode) -> CoreResult<MemoryDraft> {
            Err(CoreError::Llm("unused".to_string()))
        }

        async fn decide(
            &self,
            goal: &str,
            _round: u64,
            _transcript: &[TranscriptEntry],
            _available_tools: &[String],
        ) -> CoreResult<AgentAction> {
            *self.goal.lock().unwrap() = Some(goal.to_string());
            Ok(AgentAction::Finish {
                answer: "done".to_string(),
            })
        }
    }

    #[tokio::test]
    async fn profiled_tool_host_hides_and_rejects_tools_outside_the_intersection() {
        let mut profile =
            ExecutionProfile::resolve("builtin:all-access", &all_access_agent(), None, None)
                .unwrap();
        profile.allowed_tools = vec!["read".to_string()];
        let host = ProfiledToolHost::new(Arc::new(StubToolHost), &profile);

        assert_eq!(host.list_tools(), ["read"]);
        assert_eq!(host.call("read", "{}").await.unwrap(), "read");
        assert!(host
            .call("write", "{}")
            .await
            .unwrap_err()
            .to_string()
            .contains("not allowed"));
    }

    #[tokio::test]
    async fn profiled_tool_host_keeps_hidden_alias_dispatchable_without_wildcard_duplication() {
        let mut profile =
            ExecutionProfile::resolve("builtin:all-access", &all_access_agent(), None, None)
                .unwrap();
        profile.allowed_tools = vec!["*".to_string()];
        let host = ProfiledToolHost::new(Arc::new(HiddenAliasToolHost), &profile);

        assert_eq!(host.list_tools(), ["mcp__readable"]);
        assert_eq!(host.call("mcp__legacy", "{}").await.unwrap(), "mcp__legacy");
    }

    #[tokio::test]
    async fn profiled_tool_host_advertises_an_explicitly_allowlisted_hidden_alias() {
        let mut profile =
            ExecutionProfile::resolve("builtin:all-access", &all_access_agent(), None, None)
                .unwrap();
        profile.allowed_tools = vec!["mcp__legacy".to_string()];
        let host = ProfiledToolHost::new(Arc::new(HiddenAliasToolHost), &profile);

        assert_eq!(host.list_tools(), ["mcp__legacy"]);
        assert_eq!(host.call("mcp__legacy", "{}").await.unwrap(), "mcp__legacy");
        assert!(host.call("mcp__readable", "{}").await.is_err());
    }

    #[tokio::test]
    async fn profiled_llm_injects_authority_without_replacing_the_user_goal() {
        let inner = Arc::new(RecordingLlm {
            goal: std::sync::Mutex::new(None),
        });
        let mut profile =
            ExecutionProfile::resolve("builtin:all-access", &all_access_agent(), None, None)
                .unwrap();
        profile.instructions = "Use direct evidence.".to_string();
        let llm = ProfiledLlm::new(inner.clone(), &profile);

        llm.decide("Inspect the workspace", 0, &[], &[])
            .await
            .unwrap();

        let captured = inner.goal.lock().unwrap().clone().unwrap();
        assert!(captured.contains("[Authoritative execution profile]"));
        assert!(captured.contains("Use direct evidence."));
        assert!(captured.ends_with("[User goal]\nInspect the workspace"));
    }
}
