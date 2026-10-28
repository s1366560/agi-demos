use super::*;
use crate::local_runtime::{
    authority_store::DesktopPermissionProfile,
    computer_use_v2::call_identity,
    execution_authority::{ExecutionScope, ScopedExecution},
};
use agistack_core::agent::tool_policy::ToolPolicyContext;
use async_trait::async_trait;
use std::sync::atomic::AtomicUsize;

struct Fixture {
    scope: ExecutionScope,
    active: AtomicBool,
    granted: AtomicBool,
    calls: AtomicUsize,
    writes: AtomicUsize,
    signal: tokio::sync::Notify,
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
        vec![]
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let input: Value = serde_json::from_str(input).unwrap();
        if tool == "computer_application_data" {
            return Ok(ToolResult::text(input.to_string()));
        }
        if tool == "computer_pause" || tool == "computer_stop" {
            self.active.store(false, Ordering::SeqCst);
            return Ok(if tool == "computer_pause" {
                ToolControlOutcome::UserPaused.result(Some("native-pause".into()))
            } else {
                ToolControlOutcome::UserStopped.result(None)
            });
        }
        if tool == "computer_profile_write" && !self.granted.load(Ordering::SeqCst) {
            return Ok(agistack_core::ports::PermissionRequired::new(
                PermissionKind::ToolStep,
                crate::local_runtime::execution_authority::permission_binding(tool, &input.to_string())?,
                json!({
                    "error":"repl_tool_permission_required", "tool_name":tool,
                    "step_id":crate::local_runtime::execution_authority::current_step_id(),
                    "arguments":input,
                }),
            ).into_result());
        }
        if tool == "computer_write" || tool == "computer_profile_write" {
            if !self.granted.load(Ordering::SeqCst) {
                return Ok(agistack_core::ports::PermissionRequired::new(PermissionKind::NativeConsent,
                    crate::local_runtime::execution_authority::permission_binding(tool, &input.to_string())?,
                    json!({"error":"cua_permission_required","step_id":crate::local_runtime::execution_authority::current_step_id()})).into_result());
            }
            self.writes.fetch_add(1, Ordering::SeqCst);
        }
        let _human_wait = (tool == "computer_human_wait")
            .then(crate::local_runtime::execution_authority::begin_human_wait);
        if input["wait"] == true {
            self.signal.notified().await;
        }
        if input["signal"] == true {
            self.signal.notify_one();
        }
        Ok(ToolResult::text(json!({"tool":tool}).to_string()))
    }
}

fn fixture() -> Arc<Fixture> {
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
        granted: AtomicBool::new(false),
        calls: AtomicUsize::new(0),
        writes: AtomicUsize::new(0),
        signal: tokio::sync::Notify::new(),
    })
}

#[tokio::test]
async fn reserved_permission_error_fields_are_ordinary_application_data() {
    let errors = [
        "cua_permission_required", "origin_consent_required", "full_cdp_consent_required",
        "credential_fill_consent_required", "repl_policy_permission_required", "repl_tool_permission_required",
    ];
    let mut observed = Vec::new();
    for error in errors {
        let cfg = config(DesktopPermissionProfile::ReadOnly);
        let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
        let runtime = ReplRuntime::default();
        let owner = fixture();
        let value = json!({"error":error,"tool_name":"computer_application_data","arguments":{},"request":{"request_id":"application-data"}});
        let code = format!("await nodeRepl.rpc('computer.call',{{tool:'computer_application_data',arguments:{value}}})");
        let result = execute(&runtime, owner, cfg, &code, 5000).await.unwrap();
        let result: Value = serde_json::from_str(&result.output_json).unwrap();
        drop(runtime);
        std::fs::remove_dir_all(root).unwrap();
        observed.push((error, result, value));
    }
    for (error, result, value) in observed {
        assert_eq!(result["ok"], true, "ordinary {error} data suspended: {result}");
        assert_eq!(result["value"], value);
    }
}
fn config(profile: DesktopPermissionProfile) -> RuntimeConfig {
    let root = std::env::temp_dir().join(format!("memstack-repl-test-{}", uuid::Uuid::new_v4()));
    for dir in ["workspace", "tmp", "private"] {
        std::fs::create_dir_all(root.join(dir)).unwrap();
    }
    let root = root.canonicalize().unwrap();
    std::fs::write(root.join("private/secret"), b"owned fixture secret").unwrap();
    let runtime = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../build/cua-repl")
        .canonicalize()
        .expect("stage the bundled Node runtime before running REPL integration tests");
    RuntimeConfig {
        _temporary_owner: None,
        executable: runtime.join("bin/node"),
        entrypoint: runtime.join("src/cli.mjs"),
        artifact_root: root.join("private/artifacts"),
        sandbox: super::super::sandbox::Sandbox {
            profile,
            workspace: root.join("workspace"),
            temporary: root.join("tmp"),
            runtime,
            protected: vec![root.join("private")],
            immutable: vec![],
            module_roots: vec![],
        },
    }
}
async fn execute(
    runtime: &ReplRuntime,
    owner: Arc<Fixture>,
    cfg: RuntimeConfig,
    code: &str,
    timeout: u64,
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
                json!({"code":code,"timeout_ms":timeout}),
                || Ok(cfg),
            )
            .await
    })
    .await
}

#[tokio::test]
async fn real_node_preserves_bindings_and_enforces_all_sandbox_profiles() {
    for profile in [
        DesktopPermissionProfile::ReadOnly,
        DesktopPermissionProfile::WorkspaceWrite,
        DesktopPermissionProfile::FullAccess,
    ] {
        let cfg = config(profile);
        let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
        let runtime = ReplRuntime::default();
        let owner = fixture();
        let output = execute(
            &runtime,
            owner.clone(),
            cfg.clone(),
            "let retained = 41; retained + 1",
            5000,
        )
        .await
        .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&output.output_json).unwrap()["value"],
            42
        );
        let code = format!("let fs = await import('node:fs/promises'); let denied = false; try {{ await fs.readFile({}); }} catch (e) {{ denied = e.code === 'EPERM'; }}; [++retained, denied]",json!(root.join("private/secret")));
        let output = execute(&runtime, owner, cfg, &code, 5000).await.unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&output.output_json).unwrap()["value"],
            json!([42, true])
        );
        drop(runtime);
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[tokio::test]
async fn permission_resume_continues_only_the_pending_operation() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let code = "let first = await nodeRepl.rpc('computer.call', {tool:'computer_read',arguments:{}}); let second = await nodeRepl.rpc('computer.call', {tool:'computer_write',arguments:{}}); [first.tool,second.tool]";
    let pending = execute(&runtime, owner.clone(), cfg.clone(), code, 5000)
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&pending.output_json).unwrap()["error"],
        "cua_permission_required"
    );
    assert_eq!(owner.calls.load(Ordering::SeqCst), 2);
    owner.granted.store(true, Ordering::SeqCst);
    let result = execute(&runtime, owner.clone(), cfg, code, 5000)
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&result.output_json).unwrap()["value"],
        json!(["computer_read", "computer_write"])
    );
    assert_eq!(owner.calls.load(Ordering::SeqCst), 3);
    assert_eq!(owner.writes.load(Ordering::SeqCst), 1);
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn profile_permission_is_bound_to_current_pending_cell() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let code = "await nodeRepl.rpc('computer.call',{tool:'computer_profile_write',arguments:{text:'approved'}})";
    let pending = execute(&runtime, owner.clone(), cfg.clone(), code, 5000)
        .await
        .unwrap();
    let pending: Value = serde_json::from_str(&pending.output_json).unwrap();
    assert_eq!(pending["error"], "repl_tool_permission_required");
    let step = pending["step_id"].as_str().unwrap();
    assert_eq!(
        runtime.pending_permission_scope("conversation", "run", step, "computer_profile_write"),
        Some((owner.scope.clone(), "engine".into()))
    );
    let expected = crate::local_runtime::authorized_tool_host::step_permission_key(
        step,
        "computer_profile_write",
        &json!({"text":"approved"}),
    )
    .unwrap();
    assert_eq!(
        runtime.pending_permission_key(
            "conversation",
            "run",
            Some("engine"),
            step,
            "computer_profile_write"
        ),
        Some(expected)
    );
    for (conversation, run, engine, requested_step, tool) in [
        ("other", "run", "engine", step, "computer_profile_write"),
        (
            "conversation",
            "other",
            "engine",
            step,
            "computer_profile_write",
        ),
        (
            "conversation",
            "run",
            "other",
            step,
            "computer_profile_write",
        ),
        (
            "conversation",
            "run",
            "engine",
            "other",
            "computer_profile_write",
        ),
        ("conversation", "run", "engine", step, "computer_write"),
    ] {
        assert!(runtime
            .pending_permission_key(conversation, run, Some(engine), requested_step, tool)
            .is_none());
        if engine == "engine" {
            assert!(runtime.pending_permission_scope(conversation, run, requested_step, tool).is_none());
        }
    }
    owner.granted.store(true, Ordering::SeqCst);
    execute(&runtime, owner.clone(), cfg.clone(), code, 5000)
        .await
        .unwrap();
    assert_eq!(owner.writes.load(Ordering::SeqCst), 1);
    assert!(runtime.pending_permission_scope("conversation", "run", step, "computer_profile_write").is_none());
    assert!(runtime
        .pending_permission_key("conversation", "run", None, step, "computer_profile_write")
        .is_none());
    owner.granted.store(false, Ordering::SeqCst);
    let pending = execute(&runtime, owner, cfg, code, 5000).await.unwrap();
    let pending: Value = serde_json::from_str(&pending.output_json).unwrap();
    runtime.cancel_run("run");
    assert!(runtime.pending_permission_scope("conversation", "run", pending["step_id"].as_str().unwrap(), "computer_profile_write").is_none());
    assert!(runtime
        .pending_permission_key(
            "conversation",
            "run",
            None,
            pending["step_id"].as_str().unwrap(),
            "computer_profile_write"
        )
        .is_none());
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn simultaneous_wait_and_action_do_not_deadlock() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let code = "let waiting=nodeRepl.rpc('computer.call',{tool:'computer_read',arguments:{wait:true}}); await nodeRepl.rpc('computer.call',{tool:'computer_read',arguments:{signal:true}}); (await waiting).tool";
    let output = execute(&runtime, owner, cfg, code, 5000).await.unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&output.output_json).unwrap()["value"],
        "computer_read"
    );
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn execution_timeout_destroys_the_interpreter_and_its_bindings() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let error = execute(
        &runtime,
        owner.clone(),
        cfg.clone(),
        "let stale=1; await new Promise(() => {})",
        200,
    )
    .await
    .unwrap_err();
    assert!(error.to_string().contains("timeout"));
    let output = execute(&runtime, owner, cfg, "typeof stale", 5000)
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&output.output_json).unwrap()["value"],
        "undefined"
    );
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn native_pause_preserves_cell_but_never_replays_interrupted_action() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let code = "let beforePause = (globalThis.beforePause || 0) + 1; let interruption; try { await nodeRepl.rpc('computer.call',{tool:'computer_pause',arguments:{}}); } catch(e) { interruption=e.message; } [beforePause,interruption]";
    let paused = execute(&runtime, owner.clone(), cfg.clone(), code, 5000)
        .await
        .unwrap();
    assert_eq!(paused.control_outcome, Some(ToolControlOutcome::UserPaused));
    assert_eq!(paused.control_generation.as_deref(), Some("native-pause"));
    assert!(ToolControlOutcome::UserPaused.matches_result(&paused));
    assert!(runtime.active_context_for("run", "engine").is_none());
    owner.active.store(true, Ordering::SeqCst);
    let resumed = execute(&runtime, owner.clone(), cfg, code, 5000)
        .await
        .unwrap();
    let value: Value = serde_json::from_str(&resumed.output_json).unwrap();
    assert_eq!(value["value"][0], 1);
    assert!(value["value"][1]
        .as_str()
        .unwrap()
        .contains("partial effects"));
    assert_eq!(owner.calls.load(Ordering::SeqCst), 1);
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn native_stop_destroys_kernel_and_propagates_typed_receipt() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let stopped = execute(&runtime,owner.clone(),cfg.clone(),"let destroyed=1; await nodeRepl.rpc('computer.call',{tool:'computer_stop',arguments:{}}); destroyed=2",5000).await.unwrap();
    assert_eq!(
        stopped.control_outcome,
        Some(ToolControlOutcome::UserStopped)
    );
    assert!(ToolControlOutcome::UserStopped.matches_result(&stopped));
    owner.active.store(true, Ordering::SeqCst);
    let result = execute(&runtime, owner.clone(), cfg, "typeof destroyed", 5000)
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&result.output_json).unwrap()["value"],
        "undefined"
    );
    assert_eq!(owner.calls.load(Ordering::SeqCst), 1);
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}

async fn wait_context(runtime: &ReplRuntime) -> ActiveCellContext {
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if let Some(context) = runtime.active_context_for("run", "engine") {
                return context;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap()
}

#[tokio::test]
async fn external_permission_resumes_exact_step_and_keeps_callback_waiting() {
    for allowed_on_resume in [true, false] {
        let cfg = config(DesktopPermissionProfile::ReadOnly);
        let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
        let runtime = Arc::new(ReplRuntime::default());
        let owner = fixture();
        let code =
            "await nodeRepl.rpc('computer.call',{tool:'computer_read',arguments:{wait:true}})";
        let active = tokio::spawn({
            let runtime = runtime.clone();
            let owner = owner.clone();
            let cfg = cfg.clone();
            async move { execute(&runtime, owner, cfg, code, 5000).await }
        });
        let context = wait_context(&runtime).await;
        assert!(runtime.active_context_for("run", "other-engine").is_none());
        let steps = Arc::new(Mutex::new(Vec::new()));
        let attached = Arc::new(AtomicBool::new(true));
        let dispatch: ExternalDispatch = Arc::new({
            let owner = owner.clone();
            let steps = steps.clone();
            let attached = attached.clone();
            move |authority| {
                let owner = owner.clone();
                let steps = steps.clone();
                let attached = attached.clone();
                Box::pin(async move {
                    steps.lock().unwrap().push(
                        crate::local_runtime::execution_authority::current_step_id().unwrap(),
                    );
                    if !attached.load(Ordering::SeqCst) {
                        owner.signal.notify_one();
                        return Err(CoreError::Tool("frame_detached".into()));
                    }
                    let output = authority.call("computer_write", "{}").await?;
        if output.permission_required.is_none() {
                        owner.signal.notify_one();
                    }
                    Ok(output)
                })
            }
        });
        let callback = tokio::spawn(async move { context.submit(dispatch).await });
        let pending = active.await.unwrap().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&pending.output_json).unwrap()["error"],
            "cua_permission_required"
        );
        assert!(!callback.is_finished());
        owner.granted.store(true, Ordering::SeqCst);
        attached.store(allowed_on_resume, Ordering::SeqCst);
        let completed = execute(&runtime, owner.clone(), cfg, code, 5000)
            .await
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&completed.output_json).unwrap()["ok"],
            true
        );
        let response = callback.await.unwrap();
        if allowed_on_resume {
            assert_eq!(response.unwrap()["tool"], "computer_write");
        } else {
            assert!(response.unwrap_err().to_string().contains("frame_detached"));
        }
        assert_eq!(
            owner.writes.load(Ordering::SeqCst),
            usize::from(allowed_on_resume)
        );
        let steps = steps.lock().unwrap();
        assert_eq!(steps.len(), 2);
        assert_eq!(steps[0], steps[1]);
        drop(steps);
        drop(runtime);
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[tokio::test]
async fn cancelling_pending_external_request_releases_callback_without_dispatch() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = Arc::new(ReplRuntime::default());
    let owner = fixture();
    let active = tokio::spawn({
        let runtime = runtime.clone();
        let owner = owner.clone();
        let cfg = cfg.clone();
        async move {
            execute(
                &runtime,
                owner,
                cfg,
                "await nodeRepl.rpc('computer.call',{tool:'computer_read',arguments:{wait:true}})",
                5000,
            )
            .await
        }
    });
    let context = wait_context(&runtime).await;
    let dispatch: ExternalDispatch =
        Arc::new(|authority| Box::pin(async move { authority.call("computer_write", "{}").await }));
    let callback = tokio::spawn(async move { context.submit(dispatch).await });
    active.await.unwrap().unwrap();
    runtime.cancel_run("run");
    assert!(callback
        .await
        .unwrap()
        .unwrap_err()
        .to_string()
        .contains("cancelled"));
    assert_eq!(owner.writes.load(Ordering::SeqCst), 0);
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn abandoned_external_callback_never_dispatches_after_permission_resume() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = Arc::new(ReplRuntime::default());
    let owner = fixture();
    let code = "await nodeRepl.rpc('computer.call',{tool:'computer_read',arguments:{wait:true}})";
    let active = tokio::spawn({
        let runtime = runtime.clone();
        let owner = owner.clone();
        let cfg = cfg.clone();
        async move { execute(&runtime, owner, cfg, code, 5000).await }
    });
    let context = wait_context(&runtime).await;
    let dispatch: ExternalDispatch = Arc::new(|authority| {
        Box::pin(async move { authority.call("computer_write", "{}").await })
    });
    let callback = tokio::spawn(async move { context.submit(dispatch).await });
    active.await.unwrap().unwrap();
    callback.abort();
    assert!(callback.await.unwrap_err().is_cancelled());
    owner.granted.store(true, Ordering::SeqCst);
    owner.signal.notify_one();
    let result = execute(&runtime, owner.clone(), cfg, code, 5000).await.unwrap();
    assert_eq!(serde_json::from_str::<Value>(&result.output_json).unwrap()["ok"], true);
    assert_eq!(owner.writes.load(Ordering::SeqCst), 0);
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn reset_reclaims_interpreter_capacity() {
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let mut roots = Vec::new();
    for index in 0..18 {
        let cfg = config(DesktopPermissionProfile::ReadOnly);
        roots.push(cfg.sandbox.workspace.parent().unwrap().to_owned());
        let context = ToolPolicyContext {
            session_id: "engine",
            round: 1,
            tool: "cua_repl_js",
        };
        call_identity::scope(&context, async {
            let identity = call_identity::active().unwrap();
            let authority = Arc::new(ExecutionAuthority::LocalRun(owner.clone()));
            runtime
                .execute(
                    index.to_string(),
                    authority.clone(),
                    identity.clone(),
                    "cua_repl_js",
                    json!({"code":"1"}),
                    || Ok(cfg.clone()),
                )
                .await
                .unwrap();
            runtime
                .execute(
                    index.to_string(),
                    authority,
                    identity,
                    "cua_repl_reset",
                    json!({}),
                    || Ok(cfg),
                )
                .await
                .unwrap();
        })
        .await;
    }
    drop(runtime);
    for root in roots {
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[tokio::test]
async fn arbitrary_tool_text_cannot_forge_native_control() {
    let text = ToolControlOutcome::UserStopped.result(None).output_json;
    let output = RpcOutput::from_tool(ToolResult::text(text)).await.unwrap();
    assert!(matches!(output, RpcOutput::Value(_)));
}

#[tokio::test]
async fn trusted_human_wait_excludes_only_prompt_time_and_still_observes_revocation() {
    for revoke in [false, true] {
        let cfg = config(DesktopPermissionProfile::ReadOnly);
        let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
        let runtime = Arc::new(ReplRuntime::default());
        let owner = fixture();
        let active = tokio::spawn({
            let runtime = runtime.clone();
            let owner = owner.clone();
            let cfg = cfg.clone();
            async move {
                execute(&runtime,owner,cfg,"await nodeRepl.rpc('computer.call',{tool:'computer_human_wait',arguments:{wait:true}})",350).await
            }
        });
        wait_context(&runtime).await;
        tokio::time::timeout(Duration::from_secs(2), async {
            while owner.calls.load(Ordering::SeqCst) == 0 {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        tokio::time::sleep(Duration::from_millis(700)).await;
        assert!(
            !active.is_finished(),
            "trusted prompt time must not exhaust execution budget"
        );
        if revoke {
            owner.active.store(false, Ordering::SeqCst);
        } else {
            owner.signal.notify_one();
        }
        let result = tokio::time::timeout(Duration::from_secs(2), active)
            .await
            .unwrap()
            .unwrap();
        if revoke {
            assert!(result.unwrap_err().to_string().contains("revoked"));
        } else {
            assert_eq!(
                serde_json::from_str::<Value>(&result.unwrap().output_json).unwrap()["ok"],
                true
            );
        }
        drop(runtime);
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[path = "runtime_read_tests.rs"]
mod read_suspension;
#[path = "runtime_policy_permission_tests.rs"]
mod policy_permissions;
