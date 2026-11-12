//! Authority for individual operations issued by an interpreter or an MCP App.
//!
//! The host creates this value. Neither a JavaScript handle nor an iframe message
//! supplies an identity or widens the active run's permissions.

use std::sync::atomic::AtomicBool;
use std::{future::Future, sync::Arc};
#[path = "execution_human_wait.rs"]
mod human_wait;
pub(crate) use human_wait::{begin_human_wait, with_human_wait_clock, HumanWaitClock};

use agistack_core::ports::{CoreError, CoreResult, ToolResult};
use async_trait::async_trait;
use serde::Serialize;

/// Trusted owner and execution binding; never deserialized from model input.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ExecutionScope {
    pub tenant_id: String,
    pub project_id: String,
    pub conversation_id: String,
    pub run_id: String,
    pub run_revision: u64,
    pub engine_session_id: String,
    pub device_id: Option<String>,
    pub connection_epoch: Option<u64>,
    pub generation: u64,
}

/// An implementation must check its actual run authority before dispatch.
#[async_trait]
pub(crate) trait ScopedExecution: Send + Sync {
    fn scope(&self) -> &ExecutionScope;
    fn current(&self) -> CoreResult<()>;
    fn allowed_mcp_servers(&self) -> Vec<String>;
    fn mcp_scope(&self) -> super::mcp_supervisor::McpScope {
        super::mcp_supervisor::McpScope {
            tenant_id: self.scope().tenant_id.clone(),
            project_id: self.scope().project_id.clone(),
        }
    }
    fn request_id(&self) -> Option<&str> {
        None
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<ToolResult>;
}

/// Local and remote authority use the same operation boundary, not a synthetic local run.
#[derive(Clone)]
pub(crate) enum ExecutionAuthority {
    LocalRun(Arc<dyn ScopedExecution>),
    CloudClaim(Arc<dyn ScopedExecution>),
}

impl ExecutionAuthority {
    fn inner(&self) -> &dyn ScopedExecution {
        match self {
            Self::LocalRun(inner) | Self::CloudClaim(inner) => inner.as_ref(),
        }
    }

    pub(crate) fn scope(&self) -> &ExecutionScope {
        self.inner().scope()
    }

    pub(crate) fn current(&self) -> CoreResult<()> {
        self.inner().current()
    }

    pub(crate) fn allowed_mcp_servers(&self) -> Vec<String> {
        self.inner().allowed_mcp_servers()
    }
    pub(super) fn mcp_scope(&self) -> super::mcp_supervisor::McpScope {
        self.inner().mcp_scope()
    }
    pub(crate) fn request_id(&self) -> Option<&str> {
        self.inner().request_id()
    }

    /// Dispatch one exact operation. A failure after dispatch never means it is safe to retry.
    pub(crate) async fn call(&self, tool: &str, input_json: &str) -> CoreResult<ToolResult> {
        self.current()?;
        let result = self.inner().call(tool, input_json).await?;
        if let Some(permission) = result.permission_required.as_ref() {
            if result.control_outcome.is_some()
                || result.control_generation.is_some()
                || permission.binding() != &permission_binding(tool, input_json)?
            {
                return Err(CoreError::Tool("permission_binding_mismatch".into()));
            }
        }
        if let Some(outcome) = result.control_outcome {
            // Native control may itself revoke dispatch authority. Preserve only the
            // typed, canonical receipt; arbitrary tool JSON cannot request control.
            let generation_valid = match outcome {
                agistack_core::ports::ToolControlOutcome::UserPaused => result
                    .control_generation
                    .as_ref()
                    .is_some_and(|value| !value.is_empty()),
                agistack_core::ports::ToolControlOutcome::UserStopped => {
                    result.control_generation.is_none()
                }
            };
            if !outcome.matches_result(&result) || !generation_valid {
                return Err(CoreError::Tool("invalid tool control result".into()));
            }
            return Ok(result);
        }
        self.current().map_err(|_| {
            CoreError::Tool(
                "execution_authority_revoked_after_dispatch: outcome may already have occurred"
                    .into(),
            )
        })?;
        Ok(result)
    }
}

// Only trusted dispatch code assigns this identity. It makes separate steps with
// identical arguments independent, while transport retries retain the same identity.
tokio::task_local! { static STEP_ID: String; }
tokio::task_local! { static CELL_LIFETIME: Arc<AtomicBool>; }
tokio::task_local! { static FILE_ROOTS: Vec<std::path::PathBuf>; }
tokio::task_local! { static STEP_ORIGIN: StepOrigin; }

#[derive(Clone)]
pub(crate) struct StepOrigin {
    pub cell_id: String,
    pub parent_request_id: Option<String>,
    /// The host's previous authority, only while resuming this live pending operation.
    pub continuation_scope: Option<ExecutionScope>,
}
pub(crate) fn current_step_origin() -> Option<StepOrigin> {
    STEP_ORIGIN.try_with(Clone::clone).ok()
}

/// Capture the action identity before a host binds or normalizes its arguments.
pub(crate) fn permission_binding(
    tool: &str,
    input_json: &str,
) -> CoreResult<agistack_core::ports::PermissionBinding> {
    Ok(agistack_core::ports::PermissionBinding {
        tool_name: tool.into(),
        input_digest: agistack_core::ports::permission_input_digest(input_json)?,
        engine_session_id: super::computer_use_v2::call_identity::active()
            .ok()
            .map(|identity| identity.engine_session_id().to_string()),
        cell_id: current_step_origin().map(|origin| origin.cell_id),
        step_id: current_step_id(),
    })
}
pub(super) async fn with_step_origin<F: Future>(origin: StepOrigin, future: F) -> F::Output {
    STEP_ORIGIN.scope(origin, future).await
}
pub(crate) fn current_file_roots() -> Option<Vec<std::path::PathBuf>> {
    FILE_ROOTS.try_with(Clone::clone).ok()
}
pub(crate) fn current_download_root() -> Option<std::path::PathBuf> {
    FILE_ROOTS
        .try_with(|roots| roots.last().map(|root| root.join("downloads")))
        .ok()
        .flatten()
}
pub(super) async fn with_file_roots<F: Future>(
    roots: Vec<std::path::PathBuf>,
    future: F,
) -> F::Output {
    FILE_ROOTS.scope(roots, future).await
}

pub(super) fn current_cell_lifetime() -> Option<Arc<AtomicBool>> {
    CELL_LIFETIME.try_with(Clone::clone).ok()
}
pub(super) async fn with_cell_lifetime<F: Future>(
    lifetime: Arc<AtomicBool>,
    future: F,
) -> F::Output {
    CELL_LIFETIME.scope(lifetime, future).await
}

pub(super) fn current_step_id() -> Option<String> {
    STEP_ID.try_with(Clone::clone).ok()
}

pub(super) async fn with_step_id<F: Future>(step_id: String, future: F) -> F::Output {
    STEP_ID.scope(step_id, future).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    struct Fixture {
        scope: ExecutionScope,
        active: AtomicBool,
        calls: AtomicUsize,
        revoke_on_call: bool,
        control: Option<agistack_core::ports::ToolControlOutcome>,
        invalid_control: bool,
    }

    #[async_trait]
    impl ScopedExecution for Fixture {
        fn scope(&self) -> &ExecutionScope {
            &self.scope
        }
        fn current(&self) -> CoreResult<()> {
            if self.active.load(Ordering::SeqCst) {
                Ok(())
            } else {
                Err(CoreError::Tool("revoked".into()))
            }
        }
        fn allowed_mcp_servers(&self) -> Vec<String> {
            vec!["owned-server".into()]
        }
        async fn call(&self, _tool: &str, _input: &str) -> CoreResult<ToolResult> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            if self.revoke_on_call {
                self.active.store(false, Ordering::SeqCst);
            }
            Ok(if let Some(outcome) = self.control {
                if self.invalid_control {
                    return Ok(outcome.result(None));
                }
                outcome.result(
                    (outcome == agistack_core::ports::ToolControlOutcome::UserPaused)
                        .then(|| "pause-generation".into()),
                )
            } else {
                ToolResult::text("{}")
            })
        }
    }

    fn fixture(revoke_on_call: bool) -> Arc<Fixture> {
        Arc::new(Fixture {
            scope: ExecutionScope {
                tenant_id: "tenant".into(),
                project_id: "project".into(),
                conversation_id: "conversation".into(),
                run_id: "run".into(),
                run_revision: 1,
                engine_session_id: "engine".into(),
                device_id: Some("device".into()),
                connection_epoch: None,
                generation: 1,
            },
            active: AtomicBool::new(true),
            calls: AtomicUsize::new(0),
            revoke_on_call,
            control: None,
            invalid_control: false,
        })
    }

    #[tokio::test]
    async fn revoked_authority_never_dispatches_for_either_origin() {
        for cloud in [false, true] {
            let fixture = fixture(false);
            fixture.active.store(false, Ordering::SeqCst);
            let authority = if cloud {
                ExecutionAuthority::CloudClaim(fixture.clone())
            } else {
                ExecutionAuthority::LocalRun(fixture.clone())
            };
            assert!(authority.call("write", "{}").await.is_err());
            assert_eq!(fixture.calls.load(Ordering::SeqCst), 0);
        }
    }

    #[tokio::test]
    async fn permission_witness_requires_exact_entry_identity_for_local_and_cloud_calls() {
        use agistack_core::ports::{PermissionKind, PermissionRequired};
        struct Pending {
            scope: ExecutionScope,
            changed: &'static str,
        }
        #[async_trait]
        impl ScopedExecution for Pending {
            fn scope(&self) -> &ExecutionScope {
                &self.scope
            }
            fn current(&self) -> CoreResult<()> {
                Ok(())
            }
            fn allowed_mcp_servers(&self) -> Vec<String> {
                vec![]
            }
            async fn call(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
                let mut binding = permission_binding(tool, input)?;
                match self.changed {
                    "tool" => binding.tool_name = "other".into(),
                    "input" => {
                        binding.input_digest =
                            agistack_core::ports::permission_input_digest("{\"value\":2}")?
                    }
                    "engine" => binding.engine_session_id = Some("foreign".into()),
                    "cell" => binding.cell_id = Some("foreign".into()),
                    "step" => binding.step_id = Some("foreign".into()),
                    "equivalent" => {
                        binding.input_digest =
                            agistack_core::ports::permission_input_digest("{ \"value\": 1.0 }")?
                    }
                    _ => {}
                }
                let mut result = PermissionRequired::new(
                    PermissionKind::NativeConsent,
                    binding,
                    serde_json::json!({"error":"cua_permission_required"}),
                )
                .into_result();
                if self.changed == "control" {
                    result.control_generation = Some("unexpected".into());
                }
                Ok(result)
            }
        }
        for cloud in [false, true] {
            for changed in [
                "none",
                "equivalent",
                "tool",
                "input",
                "engine",
                "cell",
                "step",
                "control",
            ] {
                let pending = Arc::new(Pending {
                    scope: fixture(false).scope.clone(),
                    changed,
                });
                let authority = if cloud {
                    ExecutionAuthority::CloudClaim(pending)
                } else {
                    ExecutionAuthority::LocalRun(pending)
                };
                let result = authority.call("computer_click", "{\"value\":1}").await;
                if matches!(changed, "none" | "equivalent") {
                    assert!(result.unwrap().permission_required.is_some());
                } else {
                    assert!(
                        result
                            .unwrap_err()
                            .to_string()
                            .contains("permission_binding_mismatch"),
                        "{changed}"
                    );
                }
            }
        }
    }

    #[tokio::test]
    async fn revocation_during_dispatch_reports_unknown_outcome_without_replay() {
        let fixture = fixture(true);
        let authority = ExecutionAuthority::LocalRun(fixture.clone());
        let error = authority.call("write", "{}").await.unwrap_err().to_string();
        assert!(error.contains("after_dispatch"));
        assert!(authority.call("write", "{}").await.is_err());
        assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn native_control_receipt_survives_its_own_authority_revocation() {
        use agistack_core::ports::ToolControlOutcome;
        for outcome in [
            ToolControlOutcome::UserPaused,
            ToolControlOutcome::UserStopped,
        ] {
            let mut fixture = fixture(true);
            Arc::get_mut(&mut fixture).unwrap().control = Some(outcome);
            let authority = ExecutionAuthority::LocalRun(fixture.clone());
            let result = authority.call("computer_click", "{}").await.unwrap();
            assert_eq!(result.control_outcome, Some(outcome));
            assert!(outcome.matches_result(&result));
            assert!(authority.call("computer_click", "{}").await.is_err());
            assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
        }
    }

    #[tokio::test]
    async fn invalid_native_pause_generation_is_never_promoted_to_control() {
        let mut fixture = fixture(true);
        let inner = Arc::get_mut(&mut fixture).unwrap();
        inner.control = Some(agistack_core::ports::ToolControlOutcome::UserPaused);
        inner.invalid_control = true;
        let authority = ExecutionAuthority::LocalRun(fixture);
        assert!(authority
            .call("computer_click", "{}")
            .await
            .unwrap_err()
            .to_string()
            .contains("invalid tool control"));
    }

    #[tokio::test]
    async fn step_identity_is_task_local_and_restores_its_parent() {
        assert!(current_step_id().is_none());
        with_step_id("parent".into(), async {
            with_step_id("child".into(), async {
                assert_eq!(current_step_id().as_deref(), Some("child"));
            })
            .await;
            assert_eq!(current_step_id().as_deref(), Some("parent"));
        })
        .await;
        assert!(current_step_id().is_none());
    }
}
