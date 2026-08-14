//! Durable reconstruction of Workspace Task terminal callback outbox rows.

use rusqlite::OptionalExtension;
use serde_json::Value;

use super::{authority_store::DesktopRun, session_store::DesktopSessionStore};

const AUTHORITY_SOURCE: &str = "workspace_task_dispatch";
const WORKSPACE_PROVIDER_ID: &str = "memstack-workspace-agent-runtime";

#[derive(Debug)]
pub(super) struct RecoveredWorkspaceTaskTerminal {
    pub(super) request_payload: Value,
    pub(super) run_id: String,
    pub(super) conversation_id: String,
    pub(super) terminal_item: Value,
}

impl DesktopSessionStore {
    /// Find only task-owned terminal timeline events whose durable callback row is absent.
    pub(super) fn workspace_task_terminals_missing_callbacks(
        &self,
    ) -> Result<Vec<RecoveredWorkspaceTaskTerminal>, String> {
        let connection = self.connection()?;
        let mut runs = connection
            .prepare(
                "SELECT value_json FROM desktop_runs run
                 WHERE status IN (
                   'running', 'ready_review', 'completed', 'failed', 'cancelled', 'interrupted',
                   'disconnected'
                 )
                   AND NOT EXISTS (
                     SELECT 1 FROM desktop_workspace_core_terminal_callbacks callback
                     WHERE callback.run_id = run.id
                   )
                 ORDER BY created_at ASC, id ASC",
            )
            .map_err(|error| error.to_string())?;
        let rows = runs
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        let mut recovered = Vec::new();
        for encoded in rows {
            let run: DesktopRun =
                serde_json::from_str(encoded.map_err(|error| error.to_string())?.as_str())
                    .map_err(|error| error.to_string())?;
            if run.authorization_snapshot["source"].as_str() != Some(AUTHORITY_SOURCE) {
                continue;
            }
            validate_run_authority(&run)?;
            let Some(terminal_item) = terminal_item_after_run_message(&connection, &run)? else {
                continue;
            };
            recovered.push(RecoveredWorkspaceTaskTerminal {
                request_payload: run.authorization_snapshot["provider_request"].clone(),
                run_id: run.id,
                conversation_id: run.conversation_id,
                terminal_item,
            });
        }
        Ok(recovered)
    }
}

fn validate_run_authority(run: &DesktopRun) -> Result<(), String> {
    let snapshot = run
        .authorization_snapshot
        .as_object()
        .ok_or_else(|| "Workspace Task terminal run authority is invalid".to_string())?;
    let required = |field: &str| {
        snapshot
            .get(field)
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .ok_or_else(|| format!("Workspace Task terminal run authority is missing {field}"))
    };
    if required("delivery_request_id")? != run.id
        || required("provider_run_id")? != run.id
        || required("conversation_id")? != run.conversation_id
        || required("project_id")? != run.project_id
        || required("provider_id")? != WORKSPACE_PROVIDER_ID
        || !snapshot
            .get("provider_request")
            .is_some_and(Value::is_object)
    {
        return Err(
            "Workspace Task terminal run authority conflicts with its projection".to_string(),
        );
    }
    Ok(())
}

fn terminal_item_after_run_message(
    connection: &rusqlite::Connection,
    run: &DesktopRun,
) -> Result<Option<Value>, String> {
    let boundary = connection
        .query_row(
            "SELECT position FROM desktop_timeline
             WHERE conversation_id = ?1
               AND json_extract(value_json, '$.type') = 'user_message'
               AND json_extract(value_json, '$.message_id') = ?2
             ORDER BY position DESC LIMIT 1",
            [&run.conversation_id, &run.message_id],
            |row| row.get::<_, i64>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    let Some(boundary) = boundary else {
        return Ok(None);
    };
    let encoded = connection
        .query_row(
            "SELECT value_json FROM desktop_timeline
             WHERE conversation_id = ?1 AND position > ?2
               AND json_extract(value_json, '$.type') IN (
                 'assistant_message', 'error', 'provider_aborted'
               )
             ORDER BY position ASC LIMIT 1",
            rusqlite::params![run.conversation_id, boundary],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    encoded
        .map(|encoded| serde_json::from_str(&encoded).map_err(|error| error.to_string()))
        .transpose()
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::local_runtime::authority_store::{
        insert_run, DesktopPermissionProfile, DesktopRunStatus,
    };

    fn workspace_run(status: DesktopRunStatus) -> DesktopRun {
        let request = json!({
            "type": "req",
            "id": "run-1",
            "method": "chat.send",
            "session_id": "conversation-1",
            "bcn_group_id": "group-1",
            "to_bot": {
                "provider_id": WORKSPACE_PROVIDER_ID,
                "provider_bot_ref": "builtin:all-access",
                "tags": [],
            },
            "from": null,
            "message": {"content": "task"},
            "attachments": [],
            "before": null,
            "after": null,
            "limit": null,
            "timeout_ms": 1_000,
            "extensions": {
                "tenant_id": "local",
                "project_id": "project-1",
                "workspace_id": "workspace-1",
                "user_id": "user-1",
                "conversation_id": "conversation-1",
                "task_id": "task-1",
                "attempt_id": "attempt-1",
                "workspace_agent_binding_id": "binding-1",
                "delivery_request_id": "run-1",
            },
        });
        DesktopRun {
            id: "run-1".to_string(),
            conversation_id: "conversation-1".to_string(),
            project_id: "project-1".to_string(),
            plan_version_id: "plan-version-1".to_string(),
            idempotency_key: "workspace-task-run:run-1".to_string(),
            message_id: "run-1".to_string(),
            request_message: "task".to_string(),
            status,
            revision: 2,
            created_at: "2026-08-14T00:00:00Z".to_string(),
            updated_at: "2026-08-14T00:00:01Z".to_string(),
            started_at: Some("2026-08-14T00:00:00Z".to_string()),
            completed_at: None,
            last_heartbeat_at: None,
            error: None,
            environment: None,
            permission_profile: DesktopPermissionProfile::WorkspaceWrite,
            authorization_snapshot: json!({
                "source": AUTHORITY_SOURCE,
                "delivery_request_id": "run-1",
                "provider_run_id": "run-1",
                "conversation_id": "conversation-1",
                "project_id": "project-1",
                "provider_id": WORKSPACE_PROVIDER_ID,
                "provider_request": request,
            }),
        }
    }

    #[test]
    fn terminal_timeline_without_callback_is_recovered_once() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction()
                    .map_err(|error| error.to_string())?;
                insert_run(&transaction, &workspace_run(DesktopRunStatus::ReadyReview))
                    .map_err(|error| error.to_string())?;
                transaction.commit().map_err(|error| error.to_string())
            })
            .expect("seed Workspace run");
        for item in [
            json!({
                "id": "user-1",
                "type": "user_message",
                "conversation_id": "conversation-1",
                "message_id": "run-1",
                "event_time_us": 1,
                "event_counter": 1,
            }),
            json!({
                "id": "terminal-1",
                "type": "assistant_message",
                "conversation_id": "conversation-1",
                "message_id": "assistant-1",
                "content": "done",
                "event_time_us": 2,
                "event_counter": 2,
            }),
        ] {
            store
                .append_timeline("conversation-1", &item)
                .expect("timeline item");
        }

        let recovered = store
            .workspace_task_terminals_missing_callbacks()
            .expect("recover terminal");

        assert_eq!(recovered.len(), 1);
        assert_eq!(recovered[0].run_id, "run-1");
        assert_eq!(recovered[0].terminal_item["id"], "terminal-1");
    }
}
