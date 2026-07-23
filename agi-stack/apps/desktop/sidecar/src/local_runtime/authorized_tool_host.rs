//! Fail-closed, run-scoped tool execution for the local desktop runtime.

use std::{collections::BTreeSet, sync::LazyLock};

use agistack_adapters_local_tools::LocalToolHost;
use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use async_trait::async_trait;
use chrono::Utc;
use serde_json::{json, Value};

use super::{
    authority_store::{DesktopPermissionProfile, DesktopRun},
    session_store::DesktopSessionStore,
    tool_authority::{
        canonical_json_digest, InvocationStatus, PermissionGrant, ToolEffect,
        ToolInvocationRequest, ToolMetadata,
    },
};

const PROFILE_GRANT_TTL_MS: i64 = 5 * 60 * 1_000;

#[derive(Clone)]
pub(super) struct AuthorizedRunToolHost {
    inner: LocalToolHost,
    session_store: DesktopSessionStore,
    run: DesktopRun,
}

impl AuthorizedRunToolHost {
    pub(super) fn new(
        inner: LocalToolHost,
        session_store: DesktopSessionStore,
        run: DesktopRun,
    ) -> Self {
        Self {
            inner,
            session_store,
            run,
        }
    }

    fn allows(&self, tool: &str, effect: ToolEffect) -> bool {
        let workspace_granted = self.run.authorization_snapshot["mode"].as_str() == Some("build")
            && self
                .session_store
                .workspace_tool_grant_active(&self.run.conversation_id, tool)
                .unwrap_or(false);
        match self.run.permission_profile {
            DesktopPermissionProfile::ReadOnly => effect == ToolEffect::Read || workspace_granted,
            DesktopPermissionProfile::WorkspaceWrite => {
                effect == ToolEffect::Read || is_workspace_write_tool(tool) || workspace_granted
            }
            DesktopPermissionProfile::FullAccess => true,
        }
    }

    fn request(&self, tool: &str, input: Value) -> CoreResult<ToolInvocationRequest> {
        let environment_id = self
            .run
            .environment
            .as_ref()
            .map(|environment| environment.id.clone())
            .ok_or_else(|| CoreError::Tool("authorized run has no execution environment".into()))?;
        let input_digest = canonical_json_digest(&input).map_err(authority_error)?;
        Ok(ToolInvocationRequest {
            run_id: self.run.id.clone(),
            plan_version_id: self.run.plan_version_id.clone(),
            run_revision: self.run.revision,
            environment_id,
            tool_name: tool.to_string(),
            target: json!({ "input_digest": input_digest }),
            input,
        })
    }
}

#[async_trait]
impl ToolHost for AuthorizedRunToolHost {
    fn list_tools(&self) -> Vec<String> {
        self.inner
            .list_tools()
            .into_iter()
            .filter(|tool| tool_effect(tool).is_some_and(|effect| self.allows(tool, effect)))
            .collect()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let metadata = tool_metadata(tool)
            .ok_or_else(|| CoreError::Tool(format!("tool '{tool}' has no authority metadata")))?;
        if !self.allows(tool, metadata.effect) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' is outside the approved permission profile"
            )));
        }
        let input: Value = serde_json::from_str(input_json)
            .map_err(|error| CoreError::Tool(format!("invalid tool input: {error}")))?;
        let request = self.request(tool, input)?;
        let identity = json!({
            "run_id": request.run_id,
            "plan_version_id": request.plan_version_id,
            "run_revision": request.run_revision,
            "environment_id": request.environment_id,
            "tool_name": request.tool_name,
            "input_digest": request.input_digest().map_err(authority_error)?,
        });
        let identity_digest = canonical_json_digest(&identity).map_err(authority_error)?;
        let invocation_id = format!("local-invocation-{identity_digest}");
        let now_ms = Utc::now().timestamp_millis();
        let workspace_granted = self.run.authorization_snapshot["mode"].as_str() == Some("build")
            && self
                .session_store
                .workspace_tool_grant_active(&self.run.conversation_id, tool)
                .map_err(CoreError::Tool)?;
        let grant = if metadata.requires_grant() {
            Some(PermissionGrant {
                grant_id: format!("local-profile-grant-{identity_digest}"),
                run_id: request.run_id.clone(),
                plan_version_id: request.plan_version_id.clone(),
                run_revision: request.run_revision,
                environment_id: request.environment_id.clone(),
                tool_name: request.tool_name.clone(),
                target: request.target.clone(),
                input_digest: request.input_digest().map_err(authority_error)?,
                use_limit: 1,
                uses: 0,
                expires_at_ms: now_ms.saturating_add(PROFILE_GRANT_TTL_MS),
            })
        } else {
            None
        };
        let prepared = self
            .session_store
            .authorize_and_prepare_tool_invocation(
                &invocation_id,
                &request,
                &metadata,
                grant,
                if workspace_granted {
                    "workspace_tool_grant"
                } else {
                    "plan_permission_profile"
                },
                now_ms,
            )
            .map_err(CoreError::Tool)?;

        if prepared.existing {
            match prepared.invocation.status {
                InvocationStatus::Completed => {
                    return serde_json::to_string(&json!({
                        "isError": false,
                        "content": [{
                            "type": "text",
                            "text": "The identical authorized invocation already completed; inspect current state instead of repeating it."
                        }],
                        "invocation_id": invocation_id,
                        "replayed": true,
                    }))
                    .map_err(|error| CoreError::Tool(error.to_string()));
                }
                InvocationStatus::Failed => {
                    return Err(CoreError::Tool(format!(
                        "tool invocation {invocation_id} already failed"
                    )));
                }
                InvocationStatus::Executing | InvocationStatus::UnknownOutcome => {
                    return Err(CoreError::Tool(format!(
                        "tool invocation {invocation_id} has an unknown outcome and requires human inspection"
                    )));
                }
                InvocationStatus::Prepared => {}
            }
        }

        self.session_store
            .transition_tool_invocation(&invocation_id, InvocationStatus::Executing, now_ms)
            .map_err(CoreError::Tool)?;
        match self.inner.call(tool, input_json).await {
            Ok(output) => {
                self.session_store
                    .transition_tool_invocation(
                        &invocation_id,
                        InvocationStatus::Completed,
                        Utc::now().timestamp_millis(),
                    )
                    .map_err(CoreError::Tool)?;
                Ok(output)
            }
            Err(error) => {
                self.session_store
                    .transition_tool_invocation(
                        &invocation_id,
                        InvocationStatus::Failed,
                        Utc::now().timestamp_millis(),
                    )
                    .map_err(CoreError::Tool)?;
                Err(error)
            }
        }
    }
}

fn authority_error(error: impl std::fmt::Display) -> CoreError {
    CoreError::Tool(error.to_string())
}

fn tool_effect(tool: &str) -> Option<ToolEffect> {
    if READ_ONLY_TOOLS.contains(&tool) {
        Some(ToolEffect::Read)
    } else if MUTATING_TOOLS.contains(&tool) {
        Some(ToolEffect::Mutate)
    } else {
        None
    }
}

pub(super) fn tool_metadata(tool: &str) -> Option<ToolMetadata> {
    Some(ToolMetadata {
        name: tool.to_string(),
        effect: tool_effect(tool)?,
        sensitive_input_fields: SENSITIVE_INPUT_FIELDS
            .iter()
            .map(|field| (*field).to_string())
            .collect(),
    })
}

pub(super) fn redact_tool_payload(tool: &str, payload: &str) -> String {
    if tool_effect(tool).is_none() {
        return "[UNAVAILABLE]".to_string();
    }
    let Ok(value) = serde_json::from_str::<Value>(payload) else {
        return "[UNPARSEABLE]".to_string();
    };
    serde_json::to_string(&super::tool_authority::redact_sensitive_fields(
        &value,
        &SENSITIVE_INPUT_FIELDS,
    ))
    .unwrap_or_else(|_| "[UNAVAILABLE]".to_string())
}

fn is_workspace_write_tool(tool: &str) -> bool {
    WORKSPACE_WRITE_TOOLS.contains(&tool)
}

static SENSITIVE_INPUT_FIELDS: LazyLock<BTreeSet<&'static str>> = LazyLock::new(|| {
    BTreeSet::from([
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "password",
        "refresh_token",
        "secret",
        "token",
    ])
});

const READ_ONLY_TOOLS: &[&str] = &[
    "read",
    "batch_read",
    "glob",
    "grep",
    "list",
    "list_artifacts",
    "ast_parse",
    "ast_find_symbols",
    "ast_extract_function",
    "ast_get_imports",
    "code_index_build",
    "find_definition",
    "find_references",
    "call_graph",
    "dependency_graph",
    "preview_edit",
    "analyze_coverage",
    "git_diff",
    "git_log",
    "get_terminal_status",
    "get_desktop_status",
    "deps_check",
];

const WORKSPACE_WRITE_TOOLS: &[&str] = &[
    "write",
    "edit",
    "patch",
    "export_artifact",
    "batch_export_artifacts",
    "edit_by_ast",
    "batch_edit",
    "generate_tests",
    "run_tests",
    "generate_commit",
    "import_file",
    "import_files_batch",
];

const MUTATING_TOOLS: &[&str] = &[
    "write",
    "edit",
    "patch",
    "export_artifact",
    "batch_export_artifacts",
    "bash",
    "edit_by_ast",
    "batch_edit",
    "generate_tests",
    "run_tests",
    "generate_commit",
    "start_terminal",
    "stop_terminal",
    "restart_terminal",
    "start_desktop",
    "stop_desktop",
    "change_resolution",
    "restart_desktop",
    "import_file",
    "import_files_batch",
    "deps_install",
];

#[cfg(test)]
mod tests {
    use super::*;
    use crate::local_runtime::{
        authority_store::{
            DesktopExecutionEnvironment, DesktopExecutionEnvironmentKind, DesktopRunStatus,
        },
        session_store::ApprovePlanStartInput,
        ConversationCapabilityMode, ConversationRunMode, LocalConversation,
    };
    use uuid::Uuid;

    fn running_host(
        profile: DesktopPermissionProfile,
    ) -> Result<
        (
            std::path::PathBuf,
            DesktopSessionStore,
            DesktopRun,
            AuthorizedRunToolHost,
        ),
        String,
    > {
        let root =
            std::env::temp_dir().join(format!("agistack-authorized-host-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&root).map_err(|error| error.to_string())?;
        let store = DesktopSessionStore::in_memory()?;
        let conversation = LocalConversation {
            id: format!("conversation-{}", Uuid::new_v4()),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Authorized tool host".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: super::super::now_iso(),
            updated_at: super::super::now_iso(),
        };
        store.insert_conversation(&conversation)?;
        store.replace_agent_plan_tasks(
            &conversation.id,
            &[json!({
                "id": format!("task-{}", Uuid::new_v4()),
                "conversation_id": conversation.id,
                "content": "Exercise the authorized tool host",
                "status": "pending",
                "priority": "high",
                "order_index": 0,
                "created_at": super::super::now_iso(),
                "updated_at": super::super::now_iso(),
            })],
        )?;
        let plan = store
            .latest_draft_plan(&conversation.id)?
            .ok_or_else(|| "plan not found".to_string())?;
        let now = super::super::now_iso();
        let outcome = store
            .approve_plan_and_start_in_environment(ApprovePlanStartInput {
                conversation_id: &conversation.id,
                project_id: "local-project",
                plan_version_id: &plan.id,
                expected_plan_version: plan.version,
                idempotency_key: "authorized-tool-host",
                message_id: "authorized-tool-message",
                request_message: "Run approved tools",
                environment: Some(DesktopExecutionEnvironment {
                    id: "environment-authorized".to_string(),
                    kind: DesktopExecutionEnvironmentKind::Local,
                    label: "Authorized local environment".to_string(),
                    workspace_path: root.to_string_lossy().into_owned(),
                    repository_root: None,
                    branch: None,
                    base_commit: None,
                    source_run_id: None,
                    created_at: now.clone(),
                }),
                requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
                permission_profile: profile,
                now: &now,
            })
            .map_err(|error| error.to_string())?;
        let run = store
            .prepare_run_for_execution(&outcome.run.id, &super::super::now_iso())?
            .ok_or_else(|| "run did not start".to_string())?;
        if run.status != DesktopRunStatus::Running {
            return Err("run is not active".to_string());
        }
        let inner = LocalToolHost::new(&root).map_err(|error| error.to_string())?;
        let host = AuthorizedRunToolHost::new(inner, store.clone(), run.clone());
        Ok((root, store, run, host))
    }

    #[test]
    fn read_only_profile_hides_mutating_tools() -> Result<(), String> {
        let (root, _store, _run, host) = running_host(DesktopPermissionProfile::ReadOnly)?;
        let tools = host.list_tools();
        assert!(tools.contains(&"read".to_string()));
        assert!(!tools.contains(&"write".to_string()));
        assert!(!tools.contains(&"bash".to_string()));
        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }

    #[tokio::test]
    async fn workspace_write_is_exactly_ledgered_redacted_and_not_repeated() -> Result<(), String> {
        let (root, store, run, host) = running_host(DesktopPermissionProfile::WorkspaceWrite)?;
        let input = json!({
            "path": "authorized.txt",
            "content": "approved content",
            "api_key": "must-not-persist",
        })
        .to_string();

        host.call("write", &input)
            .await
            .map_err(|error| error.to_string())?;
        let invocations = store.list_tool_invocations(&run.conversation_id)?;
        assert_eq!(invocations.len(), 1);
        assert_eq!(invocations[0].status, InvocationStatus::Completed);
        assert!(invocations[0].grant_id.is_some());
        assert_eq!(invocations[0].redacted_input["api_key"], "[REDACTED]");
        assert_eq!(
            std::fs::read_to_string(root.join("authorized.txt"))
                .map_err(|error| error.to_string())?,
            "approved content"
        );

        let replay = host
            .call("write", &input)
            .await
            .map_err(|error| error.to_string())?;
        assert!(replay.contains("already completed"));
        assert_eq!(store.list_tool_invocations(&run.conversation_id)?.len(), 1);
        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }
}
