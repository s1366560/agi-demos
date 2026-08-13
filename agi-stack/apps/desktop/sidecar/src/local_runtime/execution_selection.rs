//! Durable, structured resource selections for local conversation turns.

use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};

use super::DesktopSessionStore;

pub(super) fn initialize_schema(connection: &rusqlite::Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS desktop_conversation_execution_selections (
               conversation_id TEXT PRIMARY KEY,
               agent_id TEXT,
               forced_skill_id TEXT,
               subagent_id TEXT,
               message_id TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               FOREIGN KEY(conversation_id) REFERENCES desktop_conversations(id) ON DELETE CASCADE
             );",
        )
        .map_err(|error| error.to_string())
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub(super) struct ExecutionSelection {
    pub(super) agent_id: Option<String>,
    pub(super) forced_skill_id: Option<String>,
    pub(super) subagent_id: Option<String>,
}

impl ExecutionSelection {
    pub(super) fn normalized(self) -> Result<Self, String> {
        Ok(Self {
            agent_id: normalize_id(self.agent_id, "agent_id")?,
            forced_skill_id: normalize_id(self.forced_skill_id, "forced_skill_name")?,
            subagent_id: normalize_id(self.subagent_id, "subagent_id")?,
        })
    }
}

impl DesktopSessionStore {
    pub(super) fn save_execution_selection(
        &self,
        conversation_id: &str,
        message_id: &str,
        selection: &ExecutionSelection,
        now: &str,
    ) -> Result<(), String> {
        self.connection()?
            .execute(
                "INSERT INTO desktop_conversation_execution_selections(
               conversation_id, agent_id, forced_skill_id, subagent_id, message_id, updated_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)
             ON CONFLICT(conversation_id) DO UPDATE SET
               agent_id = excluded.agent_id,
               forced_skill_id = excluded.forced_skill_id,
               subagent_id = excluded.subagent_id,
               message_id = excluded.message_id,
               updated_at = excluded.updated_at",
                params![
                    conversation_id,
                    selection.agent_id,
                    selection.forced_skill_id,
                    selection.subagent_id,
                    message_id,
                    now,
                ],
            )
            .map(|_| ())
            .map_err(|error| error.to_string())
    }

    pub(super) fn execution_selection(
        &self,
        conversation_id: &str,
    ) -> Result<Option<ExecutionSelection>, String> {
        self.connection()?
            .query_row(
                "SELECT agent_id, forced_skill_id, subagent_id
                 FROM desktop_conversation_execution_selections
                 WHERE conversation_id = ?1",
                [conversation_id],
                |row| {
                    Ok(ExecutionSelection {
                        agent_id: row.get(0)?,
                        forced_skill_id: row.get(1)?,
                        subagent_id: row.get(2)?,
                    })
                },
            )
            .optional()
            .map_err(|error| error.to_string())
    }
}

fn normalize_id(value: Option<String>, field: &str) -> Result<Option<String>, String> {
    let Some(value) = value else {
        return Ok(None);
    };
    let value = value.trim();
    if value.is_empty() {
        return Ok(None);
    }
    if value.len() > 200 || value.chars().any(char::is_control) {
        return Err(format!("{field} is invalid"));
    }
    Ok(Some(value.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::local_runtime::{
        now_iso, ConversationCapabilityMode, ConversationRunMode, LocalConversation,
    };

    #[test]
    fn selection_round_trips_without_changing_conversation_storage() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation = LocalConversation {
            id: "selection-conversation".to_string(),
            project_id: "project".to_string(),
            tenant_id: "tenant".to_string(),
            title: "Selection".to_string(),
            workspace_id: None,
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now_iso(),
            updated_at: now_iso(),
        };
        store
            .insert_conversation(&conversation)
            .expect("insert conversation");
        let selection = ExecutionSelection {
            agent_id: Some("agent".to_string()),
            forced_skill_id: Some("skill".to_string()),
            subagent_id: Some("subagent".to_string()),
        };
        store
            .save_execution_selection(&conversation.id, "message", &selection, &now_iso())
            .expect("save selection");
        assert_eq!(
            store
                .execution_selection(&conversation.id)
                .expect("read selection"),
            Some(selection)
        );
    }
}
