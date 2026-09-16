//! Fail-closed, run-scoped tool execution for the local desktop runtime.

use std::{
    collections::{BTreeMap, BTreeSet},
    future::Future,
    sync::{Arc, LazyLock, Mutex},
};

use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use async_trait::async_trait;
use chrono::Utc;
use serde_json::{json, Map, Value};

use super::{
    authority_store::{DesktopPermissionProfile, DesktopRun},
    session_store::DesktopSessionStore,
    tool_authority::{
        canonical_json_digest, InvocationStatus, PermissionGrant, ToolEffect,
        ToolInvocationRequest, ToolMetadata,
    },
};

const PROFILE_GRANT_TTL_MS: i64 = 5 * 60 * 1_000;

pub(super) type RunOnceToolPermissions = Arc<Mutex<BTreeSet<(String, String)>>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct AuthorizedInvocationContext {
    pub(super) invocation_id: String,
    pub(super) run_id: String,
    pub(super) run_revision: u64,
}

tokio::task_local! {
    static AUTHORIZED_INVOCATION_CONTEXT: AuthorizedInvocationContext;
}

pub(super) fn current_authorized_invocation_context() -> Option<AuthorizedInvocationContext> {
    AUTHORIZED_INVOCATION_CONTEXT.try_with(Clone::clone).ok()
}

pub(super) async fn with_authorized_invocation_context<F>(
    context: AuthorizedInvocationContext,
    future: F,
) -> F::Output
where
    F: Future,
{
    AUTHORIZED_INVOCATION_CONTEXT.scope(context, future).await
}

#[derive(Clone)]
pub(super) struct AuthorizedRunToolHost {
    inner: Arc<dyn ToolHost>,
    session_store: DesktopSessionStore,
    run: DesktopRun,
    dynamic_metadata: BTreeMap<String, ToolMetadata>,
    once_permissions: RunOnceToolPermissions,
}

impl AuthorizedRunToolHost {
    pub(super) fn new(
        inner: Arc<dyn ToolHost>,
        session_store: DesktopSessionStore,
        run: DesktopRun,
    ) -> Self {
        Self::with_dynamic_metadata(inner, session_store, run, BTreeMap::new())
    }

    pub(super) fn with_dynamic_metadata(
        inner: Arc<dyn ToolHost>,
        session_store: DesktopSessionStore,
        run: DesktopRun,
        dynamic_metadata: BTreeMap<String, ToolMetadata>,
    ) -> Self {
        Self {
            inner,
            session_store,
            run,
            dynamic_metadata,
            once_permissions: Arc::new(Mutex::new(BTreeSet::new())),
        }
    }

    pub(super) fn with_once_permissions(
        mut self,
        once_permissions: RunOnceToolPermissions,
    ) -> Self {
        self.once_permissions = once_permissions;
        self
    }

    fn once_permission_active(&self, tool: &str) -> bool {
        self.once_permissions
            .lock()
            .expect("run once tool permissions")
            .contains(&(self.run.id.clone(), tool.to_string()))
    }

    fn consume_once_permission(&self, tool: &str) {
        self.once_permissions
            .lock()
            .expect("run once tool permissions")
            .remove(&(self.run.id.clone(), tool.to_string()));
    }

    fn metadata(&self, tool: &str) -> Option<ToolMetadata> {
        self.dynamic_metadata
            .get(tool)
            .cloned()
            .or_else(|| tool_metadata(tool))
    }

    fn allows(&self, tool: &str, effect: ToolEffect) -> bool {
        self.allows_without_once(tool, effect) || self.once_permission_active(tool)
    }

    fn allows_without_once(&self, tool: &str, effect: ToolEffect) -> bool {
        // DesktopRun is an approved plan authority, including Build execution.
        // Historical workspace grants cannot broaden that plan's chosen profile.
        // Fresh, exact run/tool approvals are handled separately by `allows`.
        match self.run.permission_profile {
            DesktopPermissionProfile::ReadOnly => effect == ToolEffect::Read,
            DesktopPermissionProfile::WorkspaceWrite => {
                effect == ToolEffect::Read || is_workspace_write_tool(tool)
            }
            DesktopPermissionProfile::FullAccess => true,
        }
    }

    fn validate_browser_run(&self) -> CoreResult<()> {
        let current = self
            .session_store
            .run(&self.run.id)
            .map_err(CoreError::Tool)?
            .ok_or_else(|| CoreError::Tool("authorized browser run no longer exists".into()))?;
        if current.status != super::authority_store::DesktopRunStatus::Running
            || current.revision != self.run.revision
            || current.plan_version_id != self.run.plan_version_id
            || current.conversation_id != self.run.conversation_id
            || current.project_id != self.run.project_id
            || current.permission_profile != self.run.permission_profile
            || current.environment.as_ref().map(|env| &env.id)
                != self.run.environment.as_ref().map(|env| &env.id)
        {
            return Err(CoreError::Tool(
                "browser authority no longer matches the active run".into(),
            ));
        }
        Ok(())
    }

    async fn call_browser(
        &self,
        tool: &str,
        input_json: &str,
        effect: ToolEffect,
    ) -> CoreResult<String> {
        self.validate_browser_run()?;
        let profile_allowed = self.allows_without_once(tool, effect);
        // Reserve the exact once capability before any await. A second concurrent
        // call cannot observe or reuse it while origin consent is being resolved.
        let used_once = self
            .once_permissions
            .lock()
            .expect("run once tool permissions")
            .remove(&(self.run.id.clone(), tool.to_string()));
        if !profile_allowed && !used_once {
            return Err(CoreError::Tool(
                "browser tool permission is no longer active".into(),
            ));
        }
        let result = self.inner.call(tool, input_json).await;
        // These protocol results mean the origin/capability gate did not execute
        // the action. Restore only this attempt's reserved capability, only while
        // the same run authority remains live, so an approved retry can proceed.
        let consent_pending = result
            .as_ref()
            .ok()
            .and_then(|output| serde_json::from_str::<Value>(output).ok())
            .is_some_and(|output| {
                matches!(
                    output.get("error").and_then(Value::as_str),
                    Some(
                        "origin_consent_required"
                            | "full_cdp_consent_required"
                            | "credential_fill_consent_required"
                    )
                )
            });
        if used_once && consent_pending && self.validate_browser_run().is_ok() {
            self.once_permissions
                .lock()
                .expect("run once tool permissions")
                .insert((self.run.id.clone(), tool.to_string()));
        }
        result
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
    fn tool_definition(&self, name: &str) -> Option<agistack_core::ports::ToolDefinition> {
        if !self.list_tools().iter().any(|allowed| allowed == name) {
            return None;
        }
        self.inner.tool_definition(name)
    }

    fn list_tools(&self) -> Vec<String> {
        self.inner
            .list_tools()
            .into_iter()
            .filter(|tool| {
                self.metadata(tool).is_some_and(|metadata| {
                    self.allows(tool, metadata.effect)
                        || (self.run.permission_profile == DesktopPermissionProfile::ReadOnly
                            && is_workspace_write_tool(tool))
                })
            })
            .collect()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let metadata = self
            .metadata(tool)
            .ok_or_else(|| CoreError::Tool(format!("tool '{tool}' has no authority metadata")))?;
        if !self.allows(tool, metadata.effect) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' is outside the approved permission profile; request human permission with the exact canonical tool name"
            )));
        }
        // Browser tools are remote side effects authorized by the
        // origin-consent layer (persisted origin grants + the run-scoped once
        // cache), not the workspace invocation ledger. They bypass the
        // digest-based replay/dedup path entirely: a consent-gated
        // short-circuit result (origin_consent_required / origin_declined) is
        // deliberately an Ok tool result, and ledgering it as Completed would
        // trap a byte-identical retry after the user grants consent behind
        // the "already completed" replay.
        if tool.starts_with("browser_") {
            return self.call_browser(tool, input_json, metadata.effect).await;
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
        let invocation_context = AuthorizedInvocationContext {
            invocation_id: invocation_id.clone(),
            run_id: request.run_id.clone(),
            run_revision: request.run_revision,
        };
        let now_ms = Utc::now().timestamp_millis();
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
                "plan_permission_profile",
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

        // Consume the run-scoped once-permission only when the invocation will
        // actually execute. Replays and idempotency short-circuits above must
        // not burn the user's one-shot approval.
        if self.once_permission_active(tool) {
            self.consume_once_permission(tool);
        }

        self.session_store
            .transition_tool_invocation(&invocation_id, InvocationStatus::Executing, now_ms)
            .map_err(CoreError::Tool)?;
        let output = with_authorized_invocation_context(
            invocation_context,
            self.inner.call(tool, input_json),
        )
        .await;
        match output {
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
        sensitive_input_fields: sensitive_input_fields(),
    })
}

pub(super) fn sensitive_input_fields() -> BTreeSet<String> {
    SENSITIVE_INPUT_FIELDS
        .iter()
        .map(|field| (*field).to_string())
        .collect()
}

pub(super) fn redact_tool_payload(tool: &str, payload: &str) -> String {
    if tool_effect(tool).is_none()
        && tool != "submit_plan"
        && !tool.starts_with("mcp__")
        && !tool.starts_with("skill__")
        && tool != "subagent"
        && !tool.starts_with("subagent__")
    {
        return "[UNAVAILABLE]".to_string();
    }
    let Ok(value) = serde_json::from_str::<Value>(payload) else {
        return "[UNPARSEABLE]".to_string();
    };
    let redacted = if tool == "subagent" {
        redact_subagent_payload(&value)
    } else {
        super::tool_authority::redact_sensitive_fields(&value, &SENSITIVE_INPUT_FIELDS)
    };
    serde_json::to_string(&redacted).unwrap_or_else(|_| "[UNAVAILABLE]".to_string())
}

fn redact_subagent_payload(value: &Value) -> Value {
    let mut safe = Map::new();
    let payload_kind = if value.get("task").is_some() {
        "input"
    } else if value.get("content").is_some() {
        "output"
    } else if value.get("error").is_some() {
        "error"
    } else {
        "unknown"
    };
    safe.insert("payload_kind".to_string(), json!(payload_kind));
    safe.insert("redacted".to_string(), json!(true));
    insert_payload_size(&mut safe, "payload", value);
    for field in ["subagent_id", "subagent_name", "task", "content", "error"] {
        if let Some(field_value) = value.get(field) {
            safe.insert(field.to_string(), json!("[REDACTED]"));
            insert_payload_size(&mut safe, field, field_value);
        }
    }
    if let Some(success) = value.get("success").and_then(Value::as_bool) {
        safe.insert("success".to_string(), json!(success));
    }
    Value::Object(safe)
}

fn insert_payload_size(target: &mut Map<String, Value>, field: &str, value: &Value) {
    let bytes = value.as_str().map_or_else(
        || serde_json::to_vec(value).ok().map(|value| value.len()),
        |value| Some(value.len()),
    );
    if let Some(bytes) = bytes {
        target.insert(format!("{field}_bytes"), json!(bytes));
    }
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
    "skill_list",
    "skill_loader",
    // Plan submission only persists the proposed plan into the runtime's own
    // session store for human review; it never executes the plan or touches
    // the workspace, so it carries read authority like the rest of the
    // plan-mode roster and never requires a mutation grant.
    "submit_plan",
    "knowledge_search",
    "knowledge_source",
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
    "browser_list_tabs",
    "browser_snapshot",
    "browser_screenshot",
    "browser_console_logs",
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
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_new_tab",
    "browser_claim_tab",
    "browser_mark_tab",
    "browser_cdp_raw",
    "browser_fill_credentials",
];

#[cfg(test)]
mod tests {
    include!("authorized_tool_contract_tests.rs");
    use super::*;
    use crate::local_runtime::{
        authority_store::{
            DesktopExecutionEnvironment, DesktopExecutionEnvironmentKind, DesktopRunStatus,
        },
        session_store::ApprovePlanStartInput,
        ConversationCapabilityMode, ConversationRunMode, LocalConversation,
    };
    use agistack_adapters_local_tools::LocalToolHost;
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
        let host = AuthorizedRunToolHost::new(Arc::new(inner), store.clone(), run.clone());
        Ok((root, store, run, host))
    }

    #[tokio::test]
    async fn read_only_profile_advertises_but_blocks_workspace_writes() -> Result<(), String> {
        let (root, _store, _run, host) = running_host(DesktopPermissionProfile::ReadOnly)?;
        let tools = host.list_tools();
        assert!(tools.contains(&"read".to_string()));
        assert!(tools.contains(&"write".to_string()));
        assert!(!tools.contains(&"bash".to_string()));
        let error = host
            .call(
                "write",
                r#"{"path":"blocked.txt","content":"must not write"}"#,
            )
            .await
            .expect_err("write remains blocked until human permission");
        assert!(error
            .to_string()
            .contains("request human permission with the exact canonical tool name"));
        assert!(!root.join("blocked.txt").exists());
        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }

    #[derive(Default)]
    struct BrowserAuthorityProbe {
        calls: std::sync::atomic::AtomicUsize,
    }

    #[tokio::test]
    async fn approved_read_only_plan_does_not_inherit_historical_workspace_grant(
    ) -> Result<(), String> {
        use crate::local_runtime::authority_store::{
            DesktopHitlRequest, DesktopHitlStatus, WorkspaceToolGrant,
        };
        use crate::local_runtime::session_store::HitlResponseCommit;

        let (root, store, run, host) = running_host(DesktopPermissionProfile::ReadOnly)?;
        let request = DesktopHitlRequest {
            id: Uuid::new_v4().to_string(),
            conversation_id: run.conversation_id.clone(),
            run_id: None,
            round: 1,
            kind: agistack_core::agent::types::HitlKind::Permission,
            prompt: "Allow workspace write".into(),
            decision: None,
            a2ui_action: None,
            status: DesktopHitlStatus::Pending,
            authority_revision: 1,
            created_at: super::super::now_iso(),
            responded_at: None,
            response_data: None,
            response_actor: None,
            response_revision: None,
            idempotency_key: None,
        };
        store.insert_hitl_request(&request)?;
        let grant = WorkspaceToolGrant {
            id: Uuid::new_v4().to_string(),
            workspace_id: "local-workspace".into(),
            canonical_tool_name: "write".into(),
            source_hitl_request_id: request.id.clone(),
            revision: 1,
            created_by: "owner".into(),
            created_at: super::super::now_iso(),
            revoked_by: None,
            revoked_at: None,
        };
        store.mark_hitl_responded(&request.id, HitlResponseCommit {
            expected_authority_revision: 1,
            response_data: &json!({"action":"allow_always", "granted":true, "scope":"workspace_tool"}),
            response_actor: "owner",
            response_revision: None,
            idempotency_key: "historical-workspace-grant",
            workspace_tool_grant: Some(&grant),
            now: &super::super::now_iso(),
        }).map_err(|error| format!("{error:?}"))?;
        assert!(store.workspace_tool_grant_active(&run.conversation_id, "write")?);
        assert!(!run.plan_version_id.is_empty());
        assert_eq!(run.authorization_snapshot["mode"], "build");
        let input = r#"{"path":"historical-grant.txt","content":"explicit approval only"}"#;
        assert!(host.call("write", input).await.is_err());
        assert!(!root.join("historical-grant.txt").exists());

        // A fresh human approval for this exact run/tool remains sufficient.
        let once = Arc::new(Mutex::new(BTreeSet::from([(
            run.id.clone(),
            "write".into(),
        )])));
        let host = host.with_once_permissions(Arc::clone(&once));
        host.call("write", input)
            .await
            .map_err(|error| error.to_string())?;
        assert!(root.join("historical-grant.txt").exists());
        assert!(once.lock().expect("once permissions").is_empty());
        assert!(host
            .call("write", r#"{"path":"second.txt","content":"blocked"}"#)
            .await
            .is_err());
        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }

    #[async_trait]
    impl ToolHost for BrowserAuthorityProbe {
        fn list_tools(&self) -> Vec<String> {
            vec!["browser_navigate".to_string()]
        }

        async fn call(&self, _tool: &str, _input: &str) -> CoreResult<String> {
            self.calls.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            tokio::task::yield_now().await;
            Ok(json!({"ok": true}).to_string())
        }
    }

    #[tokio::test]
    async fn browser_dispatch_rejects_stale_run_revision_environment_and_cancelled_run(
    ) -> Result<(), String> {
        for fault in ["revision", "environment", "cancelled"] {
            let (root, store, run, _) = running_host(DesktopPermissionProfile::FullAccess)?;
            let probe = Arc::new(BrowserAuthorityProbe::default());
            let mut host = AuthorizedRunToolHost::new(probe.clone(), store.clone(), run.clone());
            match fault {
                "revision" => host.run.revision += 1,
                "environment" => {
                    host.run.environment.as_mut().expect("environment").id = "other".into()
                }
                _ => {
                    store.transition_run(
                        &run.id,
                        run.revision,
                        DesktopRunStatus::Cancelled,
                        None,
                        &super::super::now_iso(),
                    )?;
                }
            }
            assert!(
                host.call("browser_navigate", r#"{"url":"https://example.test"}"#)
                    .await
                    .is_err(),
                "stale {fault} must fail closed"
            );
            assert_eq!(probe.calls.load(std::sync::atomic::Ordering::SeqCst), 0);
            std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        }
        Ok(())
    }

    #[tokio::test]
    async fn browser_tool_once_grant_cannot_be_reused_or_raced() -> Result<(), String> {
        let (root, store, run, _) = running_host(DesktopPermissionProfile::ReadOnly)?;
        let probe = Arc::new(BrowserAuthorityProbe::default());
        let permissions: RunOnceToolPermissions = Arc::new(Mutex::new(BTreeSet::from([(
            run.id.clone(),
            "browser_navigate".into(),
        )])));
        let host = AuthorizedRunToolHost::new(probe.clone(), store, run)
            .with_once_permissions(permissions.clone());
        let (first, second) = tokio::join!(
            host.call("browser_navigate", "{}"),
            host.call("browser_navigate", "{}")
        );
        assert_ne!(
            first.is_ok(),
            second.is_ok(),
            "exactly one concurrent invocation is authorized"
        );
        assert_eq!(probe.calls.load(std::sync::atomic::Ordering::SeqCst), 1);
        assert!(permissions.lock().expect("permissions").is_empty());
        assert!(host.call("browser_navigate", "{}").await.is_err());
        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }

    #[tokio::test]
    async fn one_time_hitl_permission_exposes_and_consumes_exactly_one_call() -> Result<(), String>
    {
        let (root, _store, run, host) = running_host(DesktopPermissionProfile::ReadOnly)?;
        let once_permissions: RunOnceToolPermissions = Arc::new(Mutex::new(BTreeSet::new()));
        once_permissions
            .lock()
            .expect("run once permissions")
            .insert((run.id.clone(), "write".to_string()));
        let host = host.with_once_permissions(Arc::clone(&once_permissions));

        assert!(host.list_tools().iter().any(|tool| tool == "write"));
        std::fs::create_dir(root.join("src")).map_err(|error| error.to_string())?;
        host.call(
            "write",
            r#"{"path":"src/one-time.txt","content":"PLUGIN_TOOL_OK"}"#,
        )
        .await
        .map_err(|error| error.to_string())?;
        assert!(root.join("src/one-time.txt").exists());
        let second_error = host
            .call(
                "write",
                r#"{"path":"src/second.txt","content":"must not write"}"#,
            )
            .await
            .expect_err("one-time permission was consumed");
        assert!(second_error
            .to_string()
            .contains("request human permission with the exact canonical tool name"));
        assert!(!root.join("src/second.txt").exists());
        assert!(once_permissions
            .lock()
            .expect("run once permissions")
            .is_empty());

        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }

    #[tokio::test]
    async fn replayed_identical_invocation_does_not_consume_once_permission() -> Result<(), String>
    {
        let (root, _store, run, host) = running_host(DesktopPermissionProfile::ReadOnly)?;
        let once_permissions: RunOnceToolPermissions = Arc::new(Mutex::new(BTreeSet::new()));
        let host = host.with_once_permissions(Arc::clone(&once_permissions));
        let input = r#"{"path":"replayed.txt","content":"replay-safe"}"#;
        let grant_once = || {
            once_permissions
                .lock()
                .expect("run once permissions")
                .insert((run.id.clone(), "write".to_string()));
        };
        let once_active = || {
            once_permissions
                .lock()
                .expect("run once permissions")
                .contains(&(run.id.clone(), "write".to_string()))
        };

        grant_once();
        host.call("write", input)
            .await
            .map_err(|error| error.to_string())?;
        assert!(root.join("replayed.txt").exists());
        assert!(
            !once_active(),
            "executing the call consumes the one-shot grant"
        );

        // A fresh one-shot approval followed by an identical repeat of the
        // completed call replays the recorded outcome and must leave the
        // grant untouched for a genuine retry with different input.
        grant_once();
        let replayed = host
            .call("write", input)
            .await
            .map_err(|error| error.to_string())?;
        assert!(replayed.contains("\"replayed\":true"));
        assert!(
            once_active(),
            "replaying an identical completed invocation must not consume the one-shot grant"
        );

        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }

    #[test]
    fn browser_tools_are_classified_read_only() {
        for tool in [
            "browser_list_tabs",
            "browser_snapshot",
            "browser_screenshot",
            "browser_console_logs",
        ] {
            assert_eq!(tool_effect(tool), Some(ToolEffect::Read));
        }
    }

    #[test]
    fn browser_mutation_tools_are_classified_mutating_and_excluded_from_plan_mode() {
        for tool in [
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_new_tab",
            "browser_claim_tab",
            "browser_mark_tab",
            "browser_cdp_raw",
            "browser_fill_credentials",
        ] {
            assert_eq!(tool_effect(tool), Some(ToolEffect::Mutate), "tool {tool}");
            assert!(
                !super::super::PLAN_MODE_TOOL_NAMES.contains(&tool),
                "mutating browser tool {tool} must stay out of plan mode"
            );
        }
    }

    #[test]
    fn plan_mode_roster_and_submit_plan_carry_read_authority_metadata() {
        // The fail-closed run boundary rejects undeclared tools with
        // "no authority metadata"; every plan-mode tool must stay declared.
        for tool in super::super::PLAN_MODE_TOOL_NAMES {
            assert_eq!(
                tool_effect(tool),
                Some(ToolEffect::Read),
                "plan-mode tool {tool} is missing read authority metadata"
            );
        }
        let metadata = tool_metadata("submit_plan").expect("submit_plan authority metadata");
        assert_eq!(metadata.name, "submit_plan");
        assert_eq!(metadata.effect, ToolEffect::Read);
        assert!(
            !metadata.requires_grant(),
            "submitting a plan for review must not consume a mutation grant"
        );
    }

    #[test]
    fn dynamic_mcp_metadata_remains_fail_closed_by_permission_profile() -> Result<(), String> {
        let (read_root, read_store, read_run, _read_inner) =
            running_host(DesktopPermissionProfile::ReadOnly)?;
        let mut read_metadata = BTreeMap::new();
        read_metadata.insert(
            "mcp__server__tool".to_string(),
            ToolMetadata {
                name: "mcp__server__tool".to_string(),
                effect: ToolEffect::Mutate,
                sensitive_input_fields: BTreeSet::new(),
            },
        );
        let read_host = AuthorizedRunToolHost::with_dynamic_metadata(
            Arc::new(StubDynamicHost),
            read_store,
            read_run,
            read_metadata,
        );
        assert!(!read_host
            .list_tools()
            .iter()
            .any(|tool| tool == "mcp__server__tool"));

        let (full_root, full_store, full_run, _full_inner) =
            running_host(DesktopPermissionProfile::FullAccess)?;
        let mut full_metadata = BTreeMap::new();
        full_metadata.insert(
            "mcp__server__tool".to_string(),
            ToolMetadata {
                name: "mcp__server__tool".to_string(),
                effect: ToolEffect::Mutate,
                sensitive_input_fields: BTreeSet::new(),
            },
        );
        let full_host = AuthorizedRunToolHost::with_dynamic_metadata(
            Arc::new(StubDynamicHost),
            full_store,
            full_run,
            full_metadata,
        );
        assert!(full_host
            .list_tools()
            .iter()
            .any(|tool| tool == "mcp__server__tool"));

        std::fs::remove_dir_all(read_root).map_err(|error| error.to_string())?;
        std::fs::remove_dir_all(full_root).map_err(|error| error.to_string())?;
        Ok(())
    }

    #[tokio::test]
    async fn workspace_write_mcp_once_grant_is_exact_and_consumed() -> Result<(), String> {
        let (root, store, run, _) = running_host(DesktopPermissionProfile::WorkspaceWrite)?;
        let tool = "mcp__server__tool";
        let permissions: RunOnceToolPermissions = Arc::new(Mutex::new(BTreeSet::new()));
        let host = AuthorizedRunToolHost::with_dynamic_metadata(
            Arc::new(StubDynamicHost),
            store,
            run.clone(),
            BTreeMap::from([(
                tool.to_string(),
                ToolMetadata {
                    name: tool.to_string(),
                    effect: ToolEffect::Mutate,
                    sensitive_input_fields: BTreeSet::new(),
                },
            )]),
        )
        .with_once_permissions(Arc::clone(&permissions));
        assert!(!host.list_tools().contains(&tool.to_string()));
        permissions
            .lock()
            .unwrap()
            .insert(("other-run".into(), tool.into()));
        permissions
            .lock()
            .unwrap()
            .insert((run.id.clone(), "another-tool".into()));
        assert!(host.call(tool, "{}").await.is_err());
        permissions
            .lock()
            .unwrap()
            .insert((run.id.clone(), tool.into()));
        assert!(host.list_tools().contains(&tool.to_string()));
        host.call(tool, "{}")
            .await
            .map_err(|error| error.to_string())?;
        assert!(!permissions
            .lock()
            .unwrap()
            .contains(&(run.id.clone(), tool.into())));
        assert!(!host.list_tools().contains(&tool.to_string()));
        assert!(host.call(tool, r#"{"second":true}"#).await.is_err());
        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }

    struct StubDynamicHost;

    #[async_trait]
    impl ToolHost for StubDynamicHost {
        fn list_tools(&self) -> Vec<String> {
            vec!["mcp__server__tool".to_string()]
        }

        async fn call(&self, _tool: &str, _input_json: &str) -> CoreResult<String> {
            Ok("{}".to_string())
        }
    }

    #[derive(Default)]
    struct StubSubagentHost {
        invocations: std::sync::Mutex<Vec<AuthorizedInvocationContext>>,
    }

    #[async_trait]
    impl ToolHost for StubSubagentHost {
        fn list_tools(&self) -> Vec<String> {
            vec!["subagent".to_string()]
        }

        async fn call(&self, _tool: &str, _input_json: &str) -> CoreResult<String> {
            let invocation = current_authorized_invocation_context().ok_or_else(|| {
                CoreError::Tool("authorized invocation context was not propagated".to_string())
            })?;
            self.invocations
                .lock()
                .map_err(|_| CoreError::Tool("invocation recorder lock poisoned".to_string()))?
                .push(invocation);
            Ok(json!({
                "subagent_id": "qa-path-reader",
                "status": "completed",
                "content": "verified",
            })
            .to_string())
        }
    }

    #[tokio::test]
    async fn dynamic_read_only_subagent_metadata_is_ledgered_and_dispatched() -> Result<(), String>
    {
        let (root, store, run, _inner) = running_host(DesktopPermissionProfile::ReadOnly)?;
        let metadata = BTreeMap::from([(
            "subagent".to_string(),
            ToolMetadata {
                name: "subagent".to_string(),
                effect: ToolEffect::Read,
                sensitive_input_fields: BTreeSet::from([
                    "subagent_id".to_string(),
                    "subagent_name".to_string(),
                    "task".to_string(),
                ]),
            },
        )]);
        let inner = Arc::new(StubSubagentHost::default());
        let host = AuthorizedRunToolHost::with_dynamic_metadata(
            inner.clone(),
            store.clone(),
            run.clone(),
            metadata,
        );

        assert!(host.list_tools().iter().any(|tool| tool == "subagent"));
        let input = r#"{"subagent_id":"qa-path-reader","task":"inspect README task-secret-one"}"#;
        let output = host
            .call("subagent", input)
            .await
            .map_err(|error| error.to_string())?;

        assert!(output.contains("qa-path-reader"));
        let invocations = store.list_tool_invocations(&run.conversation_id)?;
        assert_eq!(invocations.len(), 1);
        assert_eq!(invocations[0].tool_name, "subagent");
        assert_eq!(invocations[0].effect, ToolEffect::Read);
        assert_eq!(invocations[0].status, InvocationStatus::Completed);
        assert!(invocations[0].grant_id.is_none());
        assert_eq!(invocations[0].redacted_input["subagent_id"], "[REDACTED]");
        assert_eq!(invocations[0].redacted_input["task"], "[REDACTED]");
        assert!(!invocations[0]
            .redacted_input
            .to_string()
            .contains("task-secret-one"));

        let replay = host
            .call("subagent", input)
            .await
            .map_err(|error| error.to_string())?;
        assert!(replay.contains("already completed"));
        assert_eq!(
            inner
                .invocations
                .lock()
                .map_err(|_| "invocation recorder lock poisoned".to_string())?
                .len(),
            1
        );

        host.call(
            "subagent",
            r#"{"subagent_id":"qa-path-reader","task":" inspect README task-secret-one "}"#,
        )
        .await
        .map_err(|error| error.to_string())?;
        let propagated = inner
            .invocations
            .lock()
            .map_err(|_| "invocation recorder lock poisoned".to_string())?;
        assert_eq!(propagated.len(), 2);
        assert_ne!(propagated[0].invocation_id, propagated[1].invocation_id);
        assert!(propagated
            .iter()
            .all(|context| context.run_id == run.id && context.run_revision == run.revision));
        drop(propagated);

        let redacted = redact_tool_payload(
            "subagent",
            r#"{"subagent_id":"qa-path-reader","task":"inspect README","api_key":"must-not-persist"}"#,
        );
        assert_ne!(redacted, "[UNAVAILABLE]");
        assert!(!redacted.contains("must-not-persist"));
        assert!(redacted.contains("[REDACTED]"));
        assert!(!redacted.contains("digest"));
        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
        Ok(())
    }

    #[test]
    fn subagent_payload_redaction_never_exposes_content_or_unsalted_digests() {
        for (payload, secret) in [
            (
                json!({
                    "subagent_id": "qa-path-reader",
                    "task": "task-secret-low-entropy",
                }),
                "task-secret-low-entropy",
            ),
            (
                json!({
                    "subagent_id": "qa-path-reader",
                    "status": "completed",
                    "content": "answer-secret-low-entropy",
                    "success": true,
                }),
                "answer-secret-low-entropy",
            ),
            (
                json!({
                    "subagent_id": "qa-path-reader",
                    "error": "error-secret-low-entropy",
                    "success": false,
                }),
                "error-secret-low-entropy",
            ),
        ] {
            let redacted = redact_tool_payload("subagent", &payload.to_string());
            assert!(!redacted.contains(secret));
            assert!(!redacted.contains("digest"));
            assert!(redacted.contains("[REDACTED]"));
            assert!(redacted.contains("_bytes"));
        }
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
