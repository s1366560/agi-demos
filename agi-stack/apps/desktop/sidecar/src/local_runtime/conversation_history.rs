//! Seed new turns from the same conversation's durable, already-redacted public messages.
//! Historical actions are context only: they must not become this run's replay journal.
use super::*;

impl LocalRuntimeState {
    pub(super) fn conversation_turn_checkpoint(
        &self,
        conversation_id: &str,
        project_id: &str,
        message_id: &str,
        goal: &str,
    ) -> Result<SessionState, String> {
        let conversation = self
            .session_store
            .conversation(conversation_id)?
            .ok_or_else(|| "conversation history is unavailable".to_owned())?;
        if conversation.project_id != project_id {
            return Err("conversation history project scope mismatch".to_owned());
        }
        let count = self.session_store.timeline_count(conversation_id)?;
        let history = self
            .session_store
            .timeline(conversation_id, count)?
            .into_iter()
            .take_while(|item| item["message_id"].as_str() != Some(message_id))
            .filter_map(|item| {
                let kind = item["type"].as_str()?;
                let data = &item["data"];
                match kind {
                    "user_message" | "assistant_message" => Some(json!({
                        "type": kind,
                        "content": item["content"].as_str().or_else(|| data["content"].as_str())?,
                    })),
                    "act" | "observe" => Some(json!({
                        "type": kind,
                        "tool_name": data["tool_name"],
                        "tool_input": data["tool_input"],
                        "tool_output": data["tool_output"],
                        "is_error": data["is_error"],
                    })),
                    _ => None,
                }
            })
            .collect::<Vec<_>>();
        let mut checkpoint = SessionState::new(conversation_id, goal, Some(project_id));
        if !history.is_empty() {
            // One explicitly labelled context entry avoids round-zero action/observation matches
            // and never restores prior permissions, HITL answers, or completed tool calls.
            checkpoint.transcript.push(TranscriptEntry::new(
                0,
                Role::Human,
                json!({
                    "kind": "prior_conversation_history",
                    "messages": history,
                })
                .to_string(),
            ));
        }
        Ok(checkpoint)
    }
}
