//! Native user controls publish typed, non-successful tool outcomes.
use super::*;
use agistack_core::{agent::ToolControlResolution, ports::ToolResult};

impl LocalTimelineObserver {
    pub(super) async fn observe_control(
        &self,
        session: &str,
        round: u64,
        tool: &str,
        input: &str,
        result: &ToolResult,
    ) -> CoreResult<ToolControlResolution> {
        let outcome = result
            .control_outcome
            .filter(|outcome| outcome.matches_result(result))
            .ok_or_else(|| CoreError::Tool("invalid native control result".into()))?;
        let input = self.redact_tool_payload(tool, input);
        let mut item = self.state.timeline_item(
            "observe",
            self.conversation_id.clone(),
            None,
            None,
            None,
            json!({
                "tool_name": tool, "tool_input": input,
                "tool_output": result.output_json, "observation": result.output_json,
                "is_error": false, "status": "cancelled", "control_outcome": outcome.as_str(),
                "round": round, "tool_call_id": format!("{}:tool:{round}", self.message_id),
                "conversation_id": self.conversation_id, "message_id": self.message_id,
                "display": timeline_presentation::display(tool),
            }),
        );
        item["toolName"] = json!(tool);
        item["toolInput"] = json!(input);
        item["toolOutput"] = json!(result.output_json);
        item["isError"] = json!(false);
        item["status"] = json!("cancelled");
        item["controlOutcome"] = json!(outcome.as_str());
        item["round"] = json!(round);
        item["display"] = timeline_presentation::display(tool);
        self.state.append_timeline(&self.conversation_id, item);
        if let Some(skill) = self.profile.skill.as_ref() {
            let item = self.state.timeline_item(
                "skill_tool_result", self.conversation_id.clone(), None, None, None,
                json!({
                    "skill_id": skill.id, "skill_name": skill.name, "tool_name": tool,
                    "result": result.output_json, "step_index": self.tool_calls.load(Ordering::Acquire),
                    "status": "cancelled", "control_outcome": outcome.as_str(),
                }),
            );
            self.state.append_timeline(&self.conversation_id, item);
        }
        computer_use_v2::local_control::wait(&self.state, &self.conversation_id, session, result)
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_core::ports::ToolControlOutcome;

    #[tokio::test]
    async fn local_control_observer_publishes_typed_cancelled_result_without_parent_completion() {
        let state = super::super::tests::test_state("local-control-observer");
        let conversation = "local-control-conversation";
        let profile = execution_profile::ExecutionProfile {
            agent: execution_profile::SelectedResource {
                id: "builtin:all-access".into(),
                name: "Agent".into(),
            },
            skill: Some(execution_profile::SelectedResource {
                id: "fixture".into(),
                name: "Fixture".into(),
            }),
            subagent: None,
            allowed_tools: vec!["computer_get_app_state".into()],
            allowed_mcp_servers: vec![],
            instructions: String::new(),
        };
        let observer = LocalTimelineObserver::new(
            state.clone(),
            conversation.into(),
            "message".into(),
            profile,
            "Observe".into(),
        );
        for (round, outcome) in [
            ToolControlOutcome::UserPaused,
            ToolControlOutcome::UserStopped,
        ]
        .into_iter()
        .enumerate()
        {
            let result = outcome
                .result((outcome == ToolControlOutcome::UserPaused).then(|| "generation".into()));
            let resolved = observer
                .on_tool_control(
                    "engine",
                    round as u64,
                    "computer_get_app_state",
                    "{}",
                    &result,
                )
                .await
                .unwrap();
            assert_eq!(
                resolved,
                if outcome == ToolControlOutcome::UserStopped {
                    ToolControlResolution::Stopped
                } else {
                    ToolControlResolution::Pending
                }
            );
        }
        let items = state.session_store.timeline(conversation, 20).unwrap();
        let observations: Vec<_> = items
            .iter()
            .filter(|item| item["type"] == "observe")
            .collect();
        assert_eq!(observations.len(), 2);
        for (round, item) in observations.iter().enumerate() {
            let expected = if round == 0 {
                "user_paused"
            } else {
                "user_stopped"
            };
            assert_eq!(item["controlOutcome"], expected);
            assert_eq!(item["payload"]["control_outcome"], expected);
            assert_eq!(item["data"]["status"], "cancelled");
            assert_eq!(item["isError"], false);
            assert_eq!(
                item["payload"]["tool_call_id"],
                format!("message:tool:{round}")
            );
        }
        assert!(!items
            .iter()
            .any(|item| item["type"] == "complete" || item["type"] == "error"));
        assert!(items
            .iter()
            .filter(|item| item["type"] == "skill_tool_result")
            .all(|item| item["payload"]["status"] == "cancelled"));
        let mut malformed = ToolControlOutcome::UserStopped.result(None);
        malformed.output_json = r#"{"error":"platform error"}"#.into();
        assert!(observer
            .on_tool_control("engine", 2, "computer_get_app_state", "{}", &malformed)
            .await
            .is_err());
    }
}
