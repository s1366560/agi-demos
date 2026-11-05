//! Recoverable source corrections must preserve the original suspended Promise.
use super::*;

struct Cleanup(std::path::PathBuf);
impl Drop for Cleanup {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[tokio::test]
async fn changed_code_retry_keeps_exact_approval_cell_and_resumes_without_replay() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let _cleanup = Cleanup(cfg.sandbox.workspace.parent().unwrap().to_owned());
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let code = "var beforeApproval = await nodeRepl.rpc('computer.call',{tool:'computer_read',arguments:{}}); var approvedWrite = await nodeRepl.rpc('computer.call',{tool:'computer_profile_write',arguments:{text:'approved'}}); [beforeApproval.tool,approvedWrite.tool]";
    let pending = execute(&runtime, owner.clone(), cfg.clone(), code, 5000)
        .await
        .unwrap();
    let pending: Value = serde_json::from_str(&pending.output_json).unwrap();
    let cell = pending["repl_continuation"]["cell_id"].as_str().unwrap();
    let step = pending["step_id"].as_str().unwrap();
    let permission = runtime
        .pending_permission_key(
            "conversation",
            "run",
            Some("engine"),
            step,
            "computer_profile_write",
        )
        .expect("original exact approval binding");
    owner.granted.store(true, Ordering::SeqCst);
    for changed in [
        format!("// resuming approved pending step\n{code}"),
        format!("{code}\n"),
    ] {
        let error = execute(&runtime, owner.clone(), cfg.clone(), &changed, 5000)
            .await
            .unwrap_err();
        assert!(error
            .to_string()
            .contains("repl_pending_cell_requires_exact_code_and_run"));
        assert_eq!(
            runtime.pending_permission_key(
                "conversation",
                "run",
                Some("engine"),
                step,
                "computer_profile_write"
            ),
            Some(permission.clone()),
            "a source mismatch must retain the original step and approval",
        );
        assert_eq!(owner.calls.load(Ordering::SeqCst), 2);
        assert_eq!(owner.writes.load(Ordering::SeqCst), 0);
    }
    let result = execute(&runtime, owner.clone(), cfg, code, 5000)
        .await
        .unwrap();
    let output: Value = serde_json::from_str(&result.output_json).unwrap();
    assert_eq!(output["cell_id"], cell);
    assert_eq!(
        output["value"],
        json!(["computer_read", "computer_profile_write"])
    );
    assert_eq!(owner.calls.load(Ordering::SeqCst), 3);
    assert_eq!(owner.writes.load(Ordering::SeqCst), 1);
    runtime.shutdown();
}

#[tokio::test]
async fn approved_revision_advance_keeps_mistyped_continuation_and_original_promise() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let _cleanup = Cleanup(cfg.sandbox.workspace.parent().unwrap().to_owned());
    let runtime = ReplRuntime::default();
    let owner = fixture();
    let code = "var first = await nodeRepl.rpc('computer.call',{tool:'computer_read',arguments:{}}); var second = await nodeRepl.rpc('computer.call',{tool:'computer_profile_write',arguments:{text:'approved'}}); [first.tool,second.tool]";
    let pending = execute(&runtime, owner.clone(), cfg.clone(), code, 5000)
        .await
        .unwrap();
    let pending: Value = serde_json::from_str(&pending.output_json).unwrap();
    let cell = pending["repl_continuation"]["cell_id"].as_str().unwrap();
    let step = pending["step_id"].as_str().unwrap();
    let permission = runtime
        .pending_permission_key(
            "conversation",
            "run",
            Some("engine"),
            step,
            "computer_profile_write",
        )
        .unwrap();
    let mut resumed = fixture();
    Arc::get_mut(&mut resumed).unwrap().scope.run_revision = 4;
    resumed.granted.store(true, Ordering::SeqCst);
    let error = execute(
        &runtime,
        resumed.clone(),
        cfg.clone(),
        &format!("// resuming after approval\n{code}"),
        5000,
    )
    .await
    .unwrap_err();
    assert!(error
        .to_string()
        .contains("repl_pending_cell_requires_exact_code_and_run"));
    assert_eq!(
        runtime.pending_permission_key(
            "conversation",
            "run",
            Some("engine"),
            step,
            "computer_profile_write"
        ),
        Some(permission)
    );
    assert_eq!(owner.calls.load(Ordering::SeqCst), 2);
    assert_eq!(resumed.calls.load(Ordering::SeqCst), 0);
    let result = execute(&runtime, resumed.clone(), cfg, code, 5000)
        .await
        .unwrap();
    let output: Value = serde_json::from_str(&result.output_json).unwrap();
    assert_eq!(output["cell_id"], cell);
    assert_eq!(
        output["value"],
        json!(["computer_read", "computer_profile_write"])
    );
    assert_eq!(
        owner.calls.load(Ordering::SeqCst),
        2,
        "completed read is not replayed under the new revision"
    );
    assert_eq!(resumed.calls.load(Ordering::SeqCst), 1);
    assert_eq!(resumed.writes.load(Ordering::SeqCst), 1);
    runtime.shutdown();
}

#[tokio::test]
async fn changed_code_under_a_different_authority_still_destroys_the_pending_cell() {
    for change in [
        "run",
        "tenant",
        "project",
        "conversation",
        "generation",
        "revision",
        "engine",
    ] {
        let cfg = config(DesktopPermissionProfile::ReadOnly);
        let _cleanup = Cleanup(cfg.sandbox.workspace.parent().unwrap().to_owned());
        let runtime = ReplRuntime::default();
        let owner = fixture();
        let code = "await nodeRepl.rpc('computer.call',{tool:'computer_profile_write',arguments:{text:'approved'}})";
        let pending = execute(&runtime, owner.clone(), cfg.clone(), code, 5000)
            .await
            .unwrap();
        let pending: Value = serde_json::from_str(&pending.output_json).unwrap();
        let step = pending["step_id"].as_str().unwrap();
        let mut other = fixture();
        let scope = &mut Arc::get_mut(&mut other).unwrap().scope;
        match change {
            "run" => scope.run_id = "other-run".into(),
            "tenant" => scope.tenant_id = "other-tenant".into(),
            "project" => scope.project_id = "other-project".into(),
            "conversation" => scope.conversation_id = "other-conversation".into(),
            "generation" => scope.generation += 1,
            "revision" => scope.run_revision = 0,
            _ => {}
        }
        let context = ToolPolicyContext {
            session_id: if change == "engine" {
                "other-engine"
            } else {
                "engine"
            },
            round: 2,
            tool: "cua_repl_js",
        };
        let error = call_identity::scope(&context, async {
            runtime
                .execute(
                    "session".into(),
                    Arc::new(ExecutionAuthority::LocalRun(other)),
                    call_identity::active().unwrap(),
                    "cua_repl_js",
                    json!({"code":if change == "engine" { code.to_owned() } else { format!("// changed\n{code}") }}),
                    || Ok(cfg),
                )
                .await
        })
        .await
        .unwrap_err();
        assert!(error
            .to_string()
            .contains("repl_pending_cell_requires_exact_code_and_run"));
        assert!(runtime
            .pending_permission_scope("conversation", "run", step, "computer_profile_write")
            .is_none());
        assert_eq!(owner.writes.load(Ordering::SeqCst), 0);
        runtime.shutdown();
    }
}
