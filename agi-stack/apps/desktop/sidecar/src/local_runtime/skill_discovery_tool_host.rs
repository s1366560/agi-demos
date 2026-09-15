//! Structured, read-only access to the current operation's authorized skill library.
use super::*;
use knowledge_authority_v2::agent_access::PluginNativeIdentityV2;

pub(super) struct SkillDiscoveryToolHost {
    state: Arc<LocalRuntimeState>,
    conversation: LocalConversation,
    run: Option<DesktopRun>,
    profile: execution_profile::ExecutionProfile,
    agent: Value,
    subagent: Option<Value>,
    native: PluginNativeIdentityV2,
    control: Arc<LocalRunControl>,
    available: Arc<dyn ToolHost>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LoadInput {
    #[serde(default)]
    skill_id: Option<String>,
    #[serde(default)]
    name: Option<String>,
}

impl SkillDiscoveryToolHost {
    pub(super) fn new(
        state: &Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
        run: Option<&DesktopRun>,
        profile: &execution_profile::ExecutionProfile,
        available: Arc<dyn ToolHost>,
    ) -> Result<Option<Self>, String> {
        let Some(native) = PluginNativeIdentityV2::capture(state, conversation, run) else {
            return Ok(None);
        };
        let control = state
            .agent_runs
            .lock()
            .map_err(|_| "local controls unavailable")?
            .get(&conversation.id)
            .map(|active| active.control.clone());
        let Some(control) = control else {
            return Ok(None);
        };
        let agent = state
            .session_store
            .managed_resource(
                ManagedResourceKind::Agent,
                "project",
                &conversation.project_id,
                &profile.agent.id,
            )?
            .ok_or("selected Agent unavailable")?;
        let subagent = profile
            .subagent
            .as_ref()
            .map(|selected| {
                state
                    .session_store
                    .managed_resource(
                        ManagedResourceKind::SubAgent,
                        "tenant",
                        &conversation.tenant_id,
                        &selected.id,
                    )
                    .and_then(|value| value.ok_or_else(|| "selected SubAgent unavailable".into()))
            })
            .transpose()?;
        Ok(Some(Self {
            state: state.clone(),
            conversation: conversation.clone(),
            run: run.cloned(),
            profile: profile.clone(),
            agent,
            subagent,
            native,
            control,
            available,
        }))
    }

    fn current(&self) -> bool {
        if !self
            .state
            .session_store
            .session_context_is_current(self.native.auth(), chrono::Utc::now().timestamp_millis())
            .unwrap_or(false)
            || !self
                .state
                .session_store
                .list_user_projects(
                    &self.native.auth().user.user_id,
                    &self.conversation.tenant_id,
                )
                .is_ok_and(|projects| {
                    projects
                        .iter()
                        .any(|project| project.id == self.conversation.project_id)
                })
        {
            return false;
        }
        let Ok(selected) = self.state.execution_profile(&self.conversation) else {
            return false;
        };
        if selected.agent != self.profile.agent || selected.skill != self.profile.skill {
            return false;
        }
        if !self.native.current(&self.state)
            || self.control.directive.load(Ordering::Acquire) != LocalRunControl::CONTINUE
        {
            return false;
        }
        if !self.state.agent_runs.lock().is_ok_and(|runs| {
            runs.get(&self.conversation.id)
                .is_some_and(|active| Arc::ptr_eq(&active.control, &self.control))
        }) {
            return false;
        }
        match (
            &self.run,
            &self.profile.subagent,
            local_plugin_tool_host_v2::identity::current_child(),
        ) {
            (Some(expected), Some(child), Some(identity)) => {
                let Ok(Some(run)) = self.state.session_store.run(&expected.id) else {
                    return false;
                };
                identity.run_id == run.id
                    && identity.revision == expected.revision
                    && identity.subagent_id == child.id
                    && run.revision == expected.revision
                    && self.state.subagent_controls.plugin_execution_current(
                        &identity.execution_id,
                        &self.conversation.id,
                        &run,
                        &child.id,
                        Some(&self.control),
                    )
            }
            (Some(expected), None, None) => {
                self.state.session_store.run(&expected.id).is_ok_and(|run| {
                    run.is_some_and(|run| {
                        run.revision == expected.revision && run.status == DesktopRunStatus::Running
                    })
                })
            }
            (None, None, None) => self
                .state
                .session_store
                .conversation(&self.conversation.id)
                .is_ok_and(|conversation| {
                    conversation.is_some_and(|conversation| {
                        conversation.current_mode == ConversationRunMode::Plan
                    })
                }),
            _ => false,
        }
    }

    fn skills(&self) -> Result<Vec<Value>, String> {
        if !self.current() {
            return Err("Skill discovery operation is no longer authorized".into());
        }
        let agent = self
            .state
            .session_store
            .managed_resource(
                ManagedResourceKind::Agent,
                "project",
                &self.conversation.project_id,
                &self.profile.agent.id,
            )?
            .ok_or("selected Agent unavailable")?;
        let child = self
            .profile
            .subagent
            .as_ref()
            .map(|selected| {
                self.state
                    .session_store
                    .managed_resource(
                        ManagedResourceKind::SubAgent,
                        "tenant",
                        &self.conversation.tenant_id,
                        &selected.id,
                    )
                    .and_then(|value| value.ok_or_else(|| "selected SubAgent unavailable".into()))
            })
            .transpose()?;
        if child.as_ref().is_some_and(|child| {
            !subagent_scope::is_visible_in_project(child, &self.conversation.project_id)
        }) {
            return Err("selected SubAgent unavailable".into());
        }
        let mut skills = Vec::new();
        for (kind, owner) in [
            ("tenant", &self.conversation.tenant_id),
            ("project", &self.conversation.project_id),
        ] {
            for mut skill in self.state.session_store.list_managed_resources(
                ManagedResourceKind::Skill,
                kind,
                owner,
            )? {
                if skill
                    .get("tenant_id")
                    .and_then(Value::as_str)
                    .is_some_and(|id| id != self.conversation.tenant_id)
                    || skill
                        .get("project_id")
                        .and_then(Value::as_str)
                        .is_some_and(|id| id != self.conversation.project_id)
                {
                    continue;
                }
                if skill.get("enabled").and_then(Value::as_bool) == Some(false) {
                    continue;
                }
                let initial = execution_profile::ExecutionProfile::resolve(
                    &self.profile.agent.id,
                    &self.agent,
                    Some(&skill),
                    self.subagent.as_ref(),
                );
                let fresh = execution_profile::ExecutionProfile::resolve(
                    &self.profile.agent.id,
                    &agent,
                    Some(&skill),
                    child.as_ref(),
                );
                let (Ok(_), Ok(fresh)) = (initial, fresh) else {
                    continue;
                };
                skill["runtime_allowed_tools"] = json!(fresh.allowed_tools);
                skill["scope"] = json!(kind);
                skills.push(skill);
            }
        }
        skills.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
        Ok(skills)
    }

    fn describe(&self, skill: &Value, include_content: bool) -> Value {
        let actual = self.available.list_tools();
        let declared = skill["tools"].as_array().cloned().unwrap_or_default();
        let available = actual
            .into_iter()
            .filter(|name| {
                skill["runtime_allowed_tools"]
                    .as_array()
                    .is_some_and(|allowed| {
                        allowed
                            .iter()
                            .any(|tool| tool.as_str() == Some("*") || tool.as_str() == Some(name))
                    })
            })
            .collect::<Vec<_>>();
        let mut result = json!({"id":skill["id"],"name":skill["name"],"description":skill["description"],
            "scope":skill["scope"],"declared_tools":declared,"available_tools":available,
            "status":if include_content {"loaded"} else {"available"},"execution_started":false,"authority_changed":false});
        if include_content {
            result["content"] = skill
                .get("full_content")
                .or_else(|| skill.get("skill_md_content"))
                .or_else(|| skill.get("description"))
                .cloned()
                .unwrap_or(Value::Null);
        }
        result
    }
}

#[async_trait]
impl ToolHost for SkillDiscoveryToolHost {
    fn list_tools(&self) -> Vec<String> {
        if !self.current() {
            return vec![];
        }
        let Ok(fresh) = self.state.execution_profile(&self.conversation) else {
            return vec![];
        };
        let child_tools = self.profile.subagent.as_ref().map(|child| {
            self.state
                .session_store
                .managed_resource(
                    ManagedResourceKind::SubAgent,
                    "tenant",
                    &self.conversation.tenant_id,
                    &child.id,
                )
                .ok()
                .flatten()
                .and_then(|child| {
                    serde_json::from_value::<Vec<String>>(child["allowed_tools"].clone()).ok()
                })
                .unwrap_or_default()
        });
        ["skill_list", "skill_loader"]
            .into_iter()
            .filter(|name| {
                child_tools.as_ref().map_or(true, |tools| {
                    tools
                        .iter()
                        .any(|allowed| allowed == "*" || allowed == name)
                }) && fresh
                    .allowed_tools
                    .iter()
                    .any(|allowed| allowed == "*" || allowed == name)
                    && self
                        .profile
                        .allowed_tools
                        .iter()
                        .any(|allowed| allowed == "*" || allowed == name)
            })
            .map(str::to_owned)
            .collect()
    }
    fn tool_definition(&self, name: &str) -> Option<agistack_core::ports::ToolDefinition> {
        if !self.list_tools().iter().any(|tool| tool == name) {
            return None;
        }
        let (description, schema) = if name == "skill_list" {
            ("List authorized skills available in this project's skill library. Discover skills here before reading workspace directories. This does not execute or activate a skill.", json!({"type":"object","properties":{},"additionalProperties":false}))
        } else {
            ("Load an authorized skill's instructions by exact skill_id or name. Follow these instructions using currently authorized tools; loading never grants additional permissions or starts execution.",json!({"type":"object","properties":{"skill_id":{"type":"string"},"name":{"type":"string"}},"oneOf":[{"required":["skill_id"]},{"required":["name"]}],"additionalProperties":false}))
        };
        Some(agistack_core::ports::ToolDefinition::new(
            name,
            description,
            schema,
        ))
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
        if !self.list_tools().iter().any(|name| name == tool) {
            return Err(CoreError::Tool(
                "Skill discovery tool is unavailable".into(),
            ));
        }
        let skills = self.skills().map_err(CoreError::Tool)?;
        if tool == "skill_list" {
            let input: Value =
                serde_json::from_str(input).map_err(|e| CoreError::Tool(e.to_string()))?;
            if input.as_object().map_or(true, |value| !value.is_empty()) {
                return Err(CoreError::Tool(
                    "skill_list requires an empty object".into(),
                ));
            }
            return Ok(json!({"skills":skills.iter().map(|skill| self.describe(skill,false)).collect::<Vec<_>>(),"execution_started":false}).to_string());
        }
        let input: LoadInput =
            serde_json::from_str(input).map_err(|e| CoreError::Tool(e.to_string()))?;
        let (field, selected) = match (input.skill_id, input.name) {
            (Some(id), None) if !id.trim().is_empty() => ("id", id),
            (None, Some(name)) if !name.trim().is_empty() => ("name", name),
            _ => {
                return Err(CoreError::Tool(
                    "skill_loader requires exactly one skill_id or name".into(),
                ))
            }
        };
        let matches = skills
            .iter()
            .filter(|skill| skill[field].as_str() == Some(&selected))
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(CoreError::Tool(
                "Skill is unavailable or selector is ambiguous".into(),
            ));
        }
        Ok(self.describe(matches[0], true).to_string())
    }
}
