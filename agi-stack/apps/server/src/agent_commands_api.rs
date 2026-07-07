//! P3/F11 builtin slash-command catalog discovery slice.
//!
//! Rust owns only the exact read-only `/api/v1/agent/commands` catalog. Command
//! execution and adjacent agent tools/workflow/conversation routes remain
//! Python-owned.

use axum::{extract::Query, routing::get, Json, Router};
use serde::{Deserialize, Serialize};

use crate::AppState;

pub(crate) fn router() -> Router<AppState> {
    Router::new().route("/api/v1/agent/commands", get(list_commands))
}

async fn list_commands(Query(query): Query<CommandListQuery>) -> Json<CommandsListResponse> {
    let commands: Vec<&'static CommandInfo> = BUILTIN_COMMANDS
        .iter()
        .filter(|command| query.matches(command))
        .collect();
    Json(CommandsListResponse {
        total: commands.len(),
        commands,
    })
}

#[derive(Debug, Clone, Deserialize)]
struct CommandListQuery {
    category: Option<String>,
    scope: Option<String>,
}

impl CommandListQuery {
    fn matches(&self, command: &CommandInfo) -> bool {
        if self
            .category
            .as_deref()
            .is_some_and(|category| command.category != category)
        {
            return false;
        }
        if let Some(scope) = self.scope.as_deref() {
            if command.scope != scope && command.scope != "both" {
                return false;
            }
        }
        true
    }
}

#[derive(Debug, Serialize)]
struct CommandsListResponse {
    commands: Vec<&'static CommandInfo>,
    total: usize,
}

#[derive(Debug, Serialize)]
struct CommandInfo {
    name: &'static str,
    description: &'static str,
    category: &'static str,
    scope: &'static str,
    aliases: &'static [&'static str],
    args: &'static [CommandArgInfo],
}

#[derive(Debug, Serialize)]
struct CommandArgInfo {
    name: &'static str,
    description: &'static str,
    arg_type: &'static str,
    required: bool,
    choices: Option<&'static [&'static str]>,
}

const ARG_DEBUG_TOGGLE: &[CommandArgInfo] = &[CommandArgInfo {
    name: "toggle",
    description: "Debug toggle",
    arg_type: "choice",
    required: false,
    choices: Some(&["on", "off"]),
}];

const ARG_GOAL_OBJECTIVE: &[CommandArgInfo] = &[CommandArgInfo {
    name: "objective",
    description: "Goal objective text",
    arg_type: "string",
    required: false,
    choices: None,
}];

const ARG_HELP_COMMAND: &[CommandArgInfo] = &[CommandArgInfo {
    name: "command",
    description: "Command name to get help for",
    arg_type: "string",
    required: false,
    choices: None,
}];

const ARG_MODEL_NAME: &[CommandArgInfo] = &[CommandArgInfo {
    name: "name",
    description: "Model name to switch to",
    arg_type: "string",
    required: false,
    choices: None,
}];

const ARG_THINK_MODE: &[CommandArgInfo] = &[CommandArgInfo {
    name: "mode",
    description: "Thinking mode",
    arg_type: "choice",
    required: false,
    choices: Some(&["on", "off", "auto"]),
}];

const BUILTIN_COMMANDS: &[CommandInfo] = &[
    CommandInfo {
        name: "agents",
        description: "List available agents in this project",
        category: "agent",
        scope: "both",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "clear",
        description: "Clear conversation display",
        category: "session",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "commands",
        description: "List all available commands",
        category: "help",
        scope: "both",
        aliases: &["cmds"],
        args: &[],
    },
    CommandInfo {
        name: "compact",
        description: "Trigger context compaction",
        category: "session",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "context",
        description: "Show current agent context and session info",
        category: "agent",
        scope: "both",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "debug",
        description: "Toggle debug mode",
        category: "debug",
        scope: "both",
        aliases: &[],
        args: ARG_DEBUG_TOGGLE,
    },
    CommandInfo {
        name: "focus",
        description: "Focus conversation on a specific agent",
        category: "agent",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "goal",
        description: "Create a workspace-backed standing goal",
        category: "agent",
        scope: "chat",
        aliases: &[],
        args: ARG_GOAL_OBJECTIVE,
    },
    CommandInfo {
        name: "help",
        description: "Show help for all commands or a specific command",
        category: "help",
        scope: "both",
        aliases: &[],
        args: ARG_HELP_COMMAND,
    },
    CommandInfo {
        name: "kill",
        description: "Kill a running sub-agent",
        category: "agent",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "model",
        description: "Show or switch current model",
        category: "model",
        scope: "both",
        aliases: &[],
        args: ARG_MODEL_NAME,
    },
    CommandInfo {
        name: "new",
        description: "Start a new conversation",
        category: "session",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "reset",
        description: "Reset current conversation session",
        category: "agent",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "send",
        description: "Send message to a specific agent",
        category: "agent",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "skills",
        description: "List available skills",
        category: "skill",
        scope: "both",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "spawn",
        description: "Delegate a task to a sub-agent",
        category: "agent",
        scope: "chat",
        aliases: &["delegate"],
        args: &[],
    },
    CommandInfo {
        name: "status",
        description: "Show current session status",
        category: "status",
        scope: "both",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "steer",
        description: "Send steering instruction to a running sub-agent",
        category: "agent",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "stop",
        description: "Stop current agent execution",
        category: "session",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "subagents",
        description: "List sub-agents of current agent",
        category: "agent",
        scope: "both",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "think",
        description: "Toggle thinking/reasoning mode",
        category: "config",
        scope: "both",
        aliases: &[],
        args: ARG_THINK_MODE,
    },
    CommandInfo {
        name: "tools",
        description: "List available tools",
        category: "tools",
        scope: "both",
        aliases: &[],
        args: &[],
    },
    CommandInfo {
        name: "unfocus",
        description: "Remove agent focus, return to default routing",
        category: "agent",
        scope: "chat",
        aliases: &[],
        args: &[],
    },
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn router_builds() {
        let _ = router();
    }

    #[tokio::test]
    async fn builtin_command_catalog_matches_python_shape() {
        let Json(response) = list_commands(Query(CommandListQuery {
            category: None,
            scope: None,
        }))
        .await;
        assert_eq!(response.total, 23);
        assert_eq!(response.commands[0].name, "agents");
        assert_eq!(response.commands[22].name, "unfocus");

        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/agent_commands_response.json"))
                .expect("agent command catalog golden parses");
        let actual = serde_json::to_value(&response).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[tokio::test]
    async fn filters_match_python_category_and_scope_semantics() {
        let Json(agent_commands) = list_commands(Query(CommandListQuery {
            category: Some("agent".to_string()),
            scope: None,
        }))
        .await;
        assert_eq!(agent_commands.total, 11);
        assert!(agent_commands
            .commands
            .iter()
            .all(|command| command.category == "agent"));

        let Json(both_scope) = list_commands(Query(CommandListQuery {
            category: None,
            scope: Some("both".to_string()),
        }))
        .await;
        assert_eq!(both_scope.total, 11);
        assert!(both_scope
            .commands
            .iter()
            .all(|command| command.scope == "both"));

        let Json(chat_scope) = list_commands(Query(CommandListQuery {
            category: None,
            scope: Some("chat".to_string()),
        }))
        .await;
        assert_eq!(chat_scope.total, 23);
    }
}
