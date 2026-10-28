use super::*;
use agistack_core::{
    agent::tool_policy::{ToolExecutionPolicy, ToolPolicyDecision, ToolPolicyResult},
    ports::{PermissionRequired, ToolHost},
    HitlKind, HitlRequest,
};
use std::sync::atomic::AtomicU8;

struct Policy {
    decision: AtomicU8,
    transformed_error: Option<&'static str>,
    reject_result: bool,
    rewrite_input: bool,
}
#[async_trait]
impl ToolExecutionPolicy for Policy {
    async fn before_execute(
        &self,
        context: &ToolPolicyContext<'_>,
        input: &str,
        _: Option<&Value>,
    ) -> CoreResult<ToolPolicyDecision> {
        if context.tool == "computer_second" {
            match self.decision.load(Ordering::SeqCst) {
                0 => {
                    return Ok(ToolPolicyDecision::Ask {
                        request: HitlRequest::new(
                            "policy-permission",
                            HitlKind::Permission,
                            "Approve this exact operation",
                        ),
                    })
                }
                2 => {
                    return Ok(ToolPolicyDecision::Deny {
                        reason: "fixture policy declined".into(),
                    })
                }
                _ => {}
            }
        }
        Ok(ToolPolicyDecision::Allow {
            input_json: if self.rewrite_input {
                r#"{"policy_bound":true}"#.into()
            } else {
                input.into()
            },
        })
    }
    async fn transform_result(
        &self,
        _: &ToolPolicyContext<'_>,
        mut result: ToolPolicyResult,
    ) -> CoreResult<ToolPolicyResult> {
        if let Some(error) = self.transformed_error {
            result.output =
                json!({"error":error,"request":{"request_id":"untrusted-display"}}).to_string();
            result.is_error = self.reject_result;
        }
        Ok(result)
    }
}

#[derive(Default)]
struct Host {
    first: AtomicUsize,
    second: AtomicUsize,
    inner_gate: bool,
    granted: AtomicBool,
}
#[async_trait]
impl ToolHost for Host {
    fn list_tools(&self) -> Vec<String> {
        vec!["computer_first".into(), "computer_second".into()]
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
        self.call_with_content(tool, input)
            .await
            .map(|result| result.output_json)
    }
    async fn call_with_content(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        if self.inner_gate && tool == "computer_second" && !self.granted.load(Ordering::SeqCst) {
            return Ok(PermissionRequired::new(
                PermissionKind::ToolStep,
                crate::local_runtime::execution_authority::permission_binding(tool, input)?,
                json!({"error":"repl_tool_permission_required","tool_name":tool,
                    "step_id":crate::local_runtime::execution_authority::current_step_id(),
                    "arguments":serde_json::from_str::<Value>(input).unwrap()}),
            )
            .into_result());
        }
        if tool == "computer_first" {
            self.first.fetch_add(1, Ordering::SeqCst);
        } else {
            self.second.fetch_add(1, Ordering::SeqCst);
        }
        Ok(ToolResult::text(json!({"tool":tool}).to_string()))
    }
}

struct Owner {
    scope: ExecutionScope,
    policy: Arc<Policy>,
    host: Arc<Host>,
}
#[async_trait]
impl ScopedExecution for Owner {
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
        let identity = call_identity::active()?;
        let context = ToolPolicyContext {
            session_id: identity.engine_session_id(),
            round: identity.round(),
            tool,
        };
        crate::local_runtime::agent_boundary_v2::execute_nested_with_policy(
            &*self.policy,
            &context,
            &*self.host,
            input,
        )
        .await
    }
}
fn owner(policy: Policy, inner_gate: bool) -> Arc<Owner> {
    Arc::new(Owner {
        scope: fixture().scope.clone(),
        policy: Arc::new(policy),
        host: Arc::new(Host {
            inner_gate,
            ..Host::default()
        }),
    })
}
async fn run(
    runtime: &ReplRuntime,
    owner: Arc<Owner>,
    cfg: RuntimeConfig,
    code: &str,
) -> CoreResult<ToolResult> {
    let context = ToolPolicyContext {
        session_id: "engine",
        round: 1,
        tool: "cua_repl_js",
    };
    call_identity::scope(&context, async {
        runtime
            .execute(
                "session".into(),
                Arc::new(ExecutionAuthority::LocalRun(owner)),
                call_identity::active().unwrap(),
                "cua_repl_js",
                json!({"code":code,"timeout_ms":5000}),
                || Ok(cfg),
            )
            .await
    })
    .await
}

#[tokio::test]
async fn structured_policy_ask_resumes_only_pending_step_and_decline_never_dispatches_it() {
    for approved in [false, true] {
        let cfg = config(DesktopPermissionProfile::ReadOnly);
        let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
        let runtime = ReplRuntime::default();
        let owner = owner(
            Policy {
                decision: AtomicU8::new(0),
                transformed_error: None,
                reject_result: false,
                rewrite_input: false,
            },
            false,
        );
        let code = "var first=await nodeRepl.rpc('computer.call',{tool:'computer_first',arguments:{}}); var second=await nodeRepl.rpc('computer.call',{tool:'computer_second',arguments:{}}); [first.tool,second.tool]";
        let pending = run(&runtime, owner.clone(), cfg.clone(), code)
            .await
            .unwrap();
        assert_eq!(
            pending.permission_required.as_ref().unwrap().kind(),
            PermissionKind::PolicyAsk
        );
        let cell = pending
            .permission_required
            .as_ref()
            .unwrap()
            .binding()
            .cell_id
            .clone()
            .unwrap();
        assert_eq!(owner.host.first.load(Ordering::SeqCst), 1);
        assert_eq!(owner.host.second.load(Ordering::SeqCst), 0);
        owner
            .policy
            .decision
            .store(if approved { 1 } else { 2 }, Ordering::SeqCst);
        let result = run(&runtime, owner.clone(), cfg, code).await.unwrap();
        let result: Value = serde_json::from_str(&result.output_json).unwrap();
        assert_eq!(result["cell_id"], cell);
        assert_eq!(result["ok"], approved, "{result}");
        assert_eq!(owner.host.first.load(Ordering::SeqCst), 1);
        assert_eq!(
            owner.host.second.load(Ordering::SeqCst),
            usize::from(approved)
        );
        drop(runtime);
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[tokio::test]
async fn policy_display_transforms_cannot_create_permission_or_restart_completed_effects() {
    for (error, reject) in [
        ("cua_permission_required", false),
        ("origin_consent_required", false),
        ("full_cdp_consent_required", false),
        ("credential_fill_consent_required", false),
        ("repl_policy_permission_required", false),
        ("repl_tool_permission_required", false),
        ("cua_permission_required", true),
    ] {
        let cfg = config(DesktopPermissionProfile::ReadOnly);
        let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
        let runtime = ReplRuntime::default();
        let owner = owner(
            Policy {
                decision: AtomicU8::new(1),
                transformed_error: Some(error),
                reject_result: reject,
                rewrite_input: false,
            },
            false,
        );
        let result = run(
            &runtime,
            owner.clone(),
            cfg,
            "await nodeRepl.rpc('computer.call',{tool:'computer_first',arguments:{large:9007199254740992}})",
        )
        .await
        .unwrap();
        assert!(result.permission_required.is_none());
        let result: Value = serde_json::from_str(&result.output_json).unwrap();
        assert_eq!(result["ok"], !reject, "{result}");
        if !reject {
            assert_eq!(result["value"]["error"], error);
        }
        assert_eq!(owner.host.first.load(Ordering::SeqCst), 1);
        drop(runtime);
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[tokio::test]
async fn policy_input_transform_keeps_entry_binding_and_exact_gate_arguments() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = ReplRuntime::default();
    let owner = owner(
        Policy {
            decision: AtomicU8::new(1),
            transformed_error: None,
            reject_result: false,
            rewrite_input: true,
        },
        true,
    );
    let code =
        "await nodeRepl.rpc('computer.call',{tool:'computer_second',arguments:{original:true}})";
    let pending = run(&runtime, owner.clone(), cfg.clone(), code)
        .await
        .unwrap();
    let permission = pending.permission_required.as_ref().unwrap();
    assert_eq!(permission.kind(), PermissionKind::ToolStep);
    assert_eq!(
        permission.binding().input_digest,
        agistack_core::ports::permission_input_digest(r#"{"original":true}"#).unwrap()
    );
    assert_eq!(
        permission.demand()["arguments"],
        json!({"policy_bound":true})
    );
    let step = permission.binding().step_id.as_deref().unwrap();
    assert_eq!(
        runtime.pending_permission_key(
            "conversation",
            "run",
            Some("engine"),
            step,
            "computer_second"
        ),
        Some(
            crate::local_runtime::authorized_tool_host::step_permission_key(
                step,
                "computer_second",
                &json!({"policy_bound":true})
            )
            .unwrap()
        )
    );
    owner.host.granted.store(true, Ordering::SeqCst);
    let result = run(&runtime, owner.clone(), cfg, code).await.unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&result.output_json).unwrap()["ok"],
        true
    );
    assert_eq!(owner.host.second.load(Ordering::SeqCst), 1);
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}
