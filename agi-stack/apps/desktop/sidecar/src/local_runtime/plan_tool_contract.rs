use super::*;

pub(super) fn approved_build_instructions(
    store: &DesktopSessionStore,
    run: &DesktopRun,
) -> Result<String, String> {
    let plan = store
        .plan_version_for_projection(&run.plan_version_id)?
        .filter(|plan| {
            plan.conversation_id == run.conversation_id
                && plan.status == authority_store::DesktopPlanStatus::Approved
        })
        .ok_or_else(|| "approved plan for this run is unavailable".to_owned())?;
    let tasks: Vec<_> = plan.tasks.iter().map(|task| &task["content"]).collect();
    Ok(format!(
        "\n\n[Current Build run]\nExecute these approved tasks in order: {}. \
         Prior conversation messages and tool calls are historical context. \
         Use tools available in this run when needed. In the finish answer, follow the user's \
         requested format for the approved deliverable. When reporting tool results, check each \
         factual claim against the current run's observations. For a requested complete listing, \
         report every returned entry with its exact path and observed type.",
        json!(tasks)
    ))
}

pub(super) fn submit_plan_definition() -> agistack_core::ports::ToolDefinition {
    agistack_core::ports::ToolDefinition::new(SUBMIT_PLAN_TOOL_NAME,
        "Persist the final ordered plan for human review. Supply tasks with content (not description); do not execute the plan.",
        json!({"type":"object", "required":["tasks"], "properties":{
            "tasks":{"type":"array", "minItems":1, "maxItems":50, "items":{
                "type":"object", "required":["content"], "properties":{
                    "content":{"type":"string", "minLength":1, "pattern":"\\S"},
                    "priority":{"type":"string", "enum":["high","medium","low"], "default":"medium"}
                }
            }}
        }})
    )
}

#[async_trait]
impl ToolHost for PlanModeToolHost {
    fn tool_definition(&self, name: &str) -> Option<agistack_core::ports::ToolDefinition> {
        if name == SUBMIT_PLAN_TOOL_NAME {
            return Some(submit_plan_definition());
        }
        if !self.accepts_tool(name) {
            return None;
        }
        self.inner.tool_definition(name)
    }

    fn list_tools(&self) -> Vec<String> {
        let mut tools = self
            .inner
            .list_tools()
            .into_iter()
            .filter(|tool| self.accepts_tool(tool))
            .collect::<Vec<_>>();
        tools.push(SUBMIT_PLAN_TOOL_NAME.to_string());
        tools
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        if agistack_adapters_cua::tool_effects().contains_key(tool) {
            return self
                .call_with_content(tool, input_json)
                .await
                .map(|result| result.output_json);
        }
        if !self.accepts_tool(tool) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' is blocked while the conversation is in plan mode"
            )));
        }
        if tool == SUBMIT_PLAN_TOOL_NAME {
            return self.submit_plan(input_json);
        }
        self.inner.call(tool, input_json).await
    }
    async fn call_with_content(
        &self,
        tool: &str,
        input_json: &str,
    ) -> CoreResult<agistack_core::ports::ToolResult> {
        if !self.accepts_tool(tool) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' is blocked while the conversation is in plan mode"
            )));
        }
        if tool == SUBMIT_PLAN_TOOL_NAME {
            return self
                .submit_plan(input_json)
                .map(|output_json| agistack_core::ports::ToolResult::text(output_json));
        }
        if agistack_adapters_cua::tool_effects().contains_key(tool) {
            let effect = computer_use_v2::input_effect(&*self.inner, tool, input_json)?;
            if effect != agistack_adapters_cua::CuaToolEffect::Read {
                return Err(CoreError::Tool("cua_operation_blocked_in_plan_mode".into()));
            }
            return computer_use_v2::with_effect(
                effect,
                self.inner.call_with_content(tool, input_json),
            )
            .await;
        }
        self.inner.call_with_content(tool, input_json).await
    }
}
