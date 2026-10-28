//! Snapshot projection tests only; no helper process or operating-system input.
use super::*;

fn lease(leases: &Leases, session: &str, generation: &str) -> Arc<AtomicBool> {
    let live = Arc::new(AtomicBool::new(true));
    leases
        .active
        .lock()
        .unwrap()
        .insert(session.into(), (generation.into(), live.clone()));
    live
}

fn native_status(session: &str, run: &str, generation: &str) -> Value {
    json!({"session_id":session,"run_id":run,"generation":generation,
        "enabled":true,"state":"active","phase":"armed"})
}

fn issue(leases: &Leases, session: &str, run: &str, generation: &str) {
    leases.record_issued(session, run, generation, &AtomicBool::new(false));
}

fn revoked_status(session: &str, run: &str, generation: &str) -> Value {
    json!({"revoked_binding":{"session_id":session,"run_id":run,"generation":generation},
        "enabled":false,"state":"available","phase":"relocking","requires_manual_unlock":false})
}

#[test]
fn session_status_requires_complete_binding_and_current_live_generation() {
    let leases = Leases::default();
    let live = lease(&leases, "session-a", "generation-a");
    let native = native_status("session-a", "run-a", "generation-a");
    leases.record_status(&native);
    assert_eq!(
        leases.session_status("session-a", "run-a"),
        Some(native.clone())
    );
    assert!(leases.session_status("session-b", "run-a").is_none());
    assert!(leases.session_status("session-a", "run-b").is_none());

    for key in ["session_id", "run_id", "generation"] {
        for invalid in [Value::Null, json!(""), json!(7)] {
            let mut incomplete = native.clone();
            incomplete[key] = invalid;
            leases.record_status(&incomplete);
            assert!(leases.session_status("session-a", "run-a").is_none());
        }
        let mut incomplete = native.clone();
        incomplete.as_object_mut().unwrap().remove(key);
        leases.record_status(&native);
        leases.record_status(&incomplete);
        assert!(leases.session_status("session-a", "run-a").is_none());
    }

    leases.record_status(&native_status("session-a", "run-a", "retired-generation"));
    assert!(leases.session_status("session-a", "run-a").is_none());
    leases.record_status(&native);
    live.store(false, Ordering::SeqCst);
    assert!(leases.session_status("session-a", "run-a").is_none());
    live.store(true, Ordering::SeqCst);
    leases.remove("session-a");
    assert!(leases.session_status("session-a", "run-a").is_none());
}

#[test]
fn replacing_a_generation_rejects_a_late_status_from_the_previous_lease() {
    let leases = Leases::default();
    lease(&leases, "session-a", "generation-a");
    leases.record_status(&native_status("session-a", "run-a", "generation-a"));
    leases.remove("session-a");
    lease(&leases, "session-a", "generation-b");
    leases.record_status(&native_status("session-a", "run-a", "generation-a"));
    assert!(leases.session_status("session-a", "run-a").is_none());
    leases.record_status(&native_status("session-a", "run-a", "generation-b"));
    assert_eq!(
        leases.session_status("session-a", "run-a").unwrap()["generation"],
        "generation-b"
    );
}

#[test]
fn active_phases_require_explicitly_enabled_and_active_native_status() {
    let leases = Leases::default();
    lease(&leases, "session-a", "generation-a");
    for phase in ["armed", "covering", "unlocking", "guarded"] {
        let mut native = native_status("session-a", "run-a", "generation-a");
        native["phase"] = json!(phase);
        leases.record_status(&native);
        assert!(leases.session_status("session-a", "run-a").is_some());

        for (key, invalid) in [
            ("enabled", json!(false)),
            ("enabled", Value::Null),
            ("enabled", json!("true")),
            ("enabled", json!(1)),
            ("state", json!("available")),
            ("state", json!("suppressed")),
            ("state", json!("failed")),
            ("state", Value::Null),
            ("state", json!(true)),
        ] {
            let mut contradictory = native.clone();
            contradictory[key] = invalid;
            leases.record_status(&contradictory);
            assert!(
                leases.session_status("session-a", "run-a").is_none(),
                "contradictory {key} must not project phase {phase}"
            );
        }
        for key in ["enabled", "state"] {
            let mut incomplete = native.clone();
            incomplete.as_object_mut().unwrap().remove(key);
            leases.record_status(&incomplete);
            assert!(
                leases.session_status("session-a", "run-a").is_none(),
                "missing {key} must not project phase {phase}"
            );
        }
    }
}

#[test]
fn fresh_runtime_status_clears_stale_phase_binding_and_failure_but_retains_setup() {
    let leases = Leases::default();
    lease(&leases, "session-a", "generation-a");
    leases.record_status(&json!({"installed":true,"supported_os":true,
        "accessibility":true,"input_monitoring":true}));
    let mut failed = native_status("session-a", "run-a", "generation-a");
    failed["enabled"] = json!(false);
    failed["state"] = json!("suppressed");
    failed["phase"] = json!("relocking");
    failed["reason"] = json!("unlock_failed");
    failed["requires_manual_unlock"] = json!(true);
    failed["failure"] = json!({"stage":"guardian_begin","reason":"coverage_failed"});
    leases.record_status(&failed);
    assert!(leases.session_status("session-a", "run-a").is_none());

    // Native revocation removes its binding. Device status remains readable,
    // but the failure must not be attributed to any visible conversation.
    let mut unbound = failed;
    for key in ["session_id", "run_id", "generation"] {
        unbound.as_object_mut().unwrap().remove(key);
    }
    leases.record_status(&unbound);
    assert!(leases.session_status("session-a", "run-a").is_none());
    assert_eq!(
        leases.status().unwrap()["failure"]["reason"],
        "coverage_failed"
    );

    leases.record_status(&native_status("session-a", "run-a", "generation-a"));
    let current = leases.status().unwrap();
    assert_eq!(current["installed"], true);
    assert_eq!(current["phase"], "armed");
    for key in [
        "reason",
        "requires_manual_unlock",
        "failure",
        "session_id",
        "run_id",
        "generation",
    ] {
        assert!(current.get(key).is_none(), "stale or private field: {key}");
    }
    leases.record_status(&json!({"state":"permission_required","enabled":false}));
    assert!(leases.status().unwrap().get("phase").is_none());
    assert!(leases.session_status("session-a", "run-a").is_none());
}

#[test]
fn latest_issued_terminal_is_displayed_after_execution_lease_is_revoked() {
    let leases = Leases::default();
    let live = lease(&leases, "session-a", "generation-a");
    issue(&leases, "session-a", "run-a", "generation-a");
    let mut terminal = revoked_status("session-a", "run-a", "generation-a");
    leases.record_status(&terminal);
    assert_eq!(
        leases.session_status("session-a", "run-a"),
        Some(terminal.clone())
    );
    live.store(false, Ordering::SeqCst);
    assert_eq!(
        leases.session_status("session-a", "run-a"),
        Some(terminal.clone())
    );
    leases.remove("session-a");
    assert_eq!(
        leases.session_status("session-a", "run-a"),
        Some(terminal.clone())
    );
    assert!(leases.session_status("session-b", "run-a").is_none());
    assert!(leases.session_status("session-a", "run-b").is_none());
    assert!(leases.status().unwrap().get("revoked_binding").is_none());
    assert!(
        !leases
            .status()
            .unwrap()
            .to_string()
            .contains("generation-a")
    );

    terminal["phase"] = json!("idle");
    terminal["state"] = json!("suppressed");
    terminal["requires_manual_unlock"] = json!(true);
    terminal["failure"] = json!({"stage":"guardian_begin","reason":"coverage_failed"});
    leases.record_status(&terminal);
    assert_eq!(leases.session_status("session-a", "run-a"), Some(terminal));
    assert!(leases.active.lock().unwrap().is_empty());
}

#[test]
fn terminal_projection_requires_complete_consistent_native_revocation() {
    let leases = Leases::default();
    let native = revoked_status("session-a", "run-a", "generation-a");
    leases.record_status(&native);
    assert!(leases.session_status("session-a", "run-a").is_none());
    issue(&leases, "session-a", "run-a", "generation-a");
    for (phase, state, manual) in [
        ("relocking", "available", false),
        ("relocking", "suppressed", true),
        ("relocking", "failed", true),
        ("idle", "suppressed", true),
        ("idle", "failed", true),
    ] {
        let mut valid = native.clone();
        valid["phase"] = json!(phase);
        valid["state"] = json!(state);
        valid["requires_manual_unlock"] = json!(manual);
        leases.record_status(&valid);
        assert!(leases.session_status("session-a", "run-a").is_some());
    }
    for (key, invalid) in [
        ("enabled", json!(true)),
        ("enabled", Value::Null),
        ("enabled", json!("false")),
        ("enabled", json!(0)),
        ("state", json!("active")),
        ("state", json!("unknown")),
        ("state", Value::Null),
        ("phase", json!("idle")),
        ("phase", json!("armed")),
        ("phase", json!("guarded")),
        ("phase", json!("unknown")),
        ("phase", Value::Null),
        ("requires_manual_unlock", json!(true)),
        ("requires_manual_unlock", json!("false")),
        ("requires_manual_unlock", Value::Null),
        ("revoked_binding", Value::Null),
        ("revoked_binding", json!([])),
    ] {
        let mut invalid_status = native.clone();
        invalid_status[key] = invalid;
        leases.record_status(&invalid_status);
        assert!(
            leases.session_status("session-a", "run-a").is_none(),
            "invalid {key}"
        );
    }
    for key in [
        "enabled",
        "state",
        "phase",
        "requires_manual_unlock",
        "revoked_binding",
    ] {
        let mut incomplete = native.clone();
        incomplete.as_object_mut().unwrap().remove(key);
        leases.record_status(&incomplete);
        assert!(
            leases.session_status("session-a", "run-a").is_none(),
            "missing {key}"
        );
    }
    for key in ["session_id", "run_id", "generation"] {
        for invalid in [Value::Null, json!(""), json!(7), json!("other")] {
            let mut incomplete = native.clone();
            incomplete["revoked_binding"][key] = invalid;
            leases.record_status(&incomplete);
            assert!(leases.session_status("session-a", "run-a").is_none());
        }
        let mut incomplete = native.clone();
        incomplete["revoked_binding"]
            .as_object_mut()
            .unwrap()
            .remove(key);
        leases.record_status(&incomplete);
        assert!(leases.session_status("session-a", "run-a").is_none());
        let mut mixed = native.clone();
        mixed[key] = Value::Null;
        leases.record_status(&mixed);
        assert!(leases.session_status("session-a", "run-a").is_none());
    }
    let mut suppressed = native;
    suppressed["state"] = json!("suppressed");
    leases.record_status(&suppressed);
    assert!(leases.session_status("session-a", "run-a").is_none());
}

#[test]
fn new_issue_invalidates_old_terminal_even_when_the_new_enable_fails() {
    let leases = Leases::default();
    issue(&leases, "session-a", "run-a", "generation-a");
    leases.record_status(&revoked_status("session-a", "run-a", "generation-a"));
    assert!(leases.session_status("session-a", "run-a").is_some());

    let live = lease(&leases, "session-a", "generation-b");
    issue(&leases, "session-a", "run-a", "generation-b");
    assert!(leases.session_status("session-a", "run-a").is_none());
    // Error cleanup revokes execution; it must not restore the previous origin.
    leases.remove("session-a");
    assert!(!live.load(Ordering::SeqCst));
    leases.record_status(&revoked_status("session-a", "run-a", "generation-a"));
    assert!(leases.session_status("session-a", "run-a").is_none());
    leases.record_status(&revoked_status("session-a", "run-a", "generation-b"));
    assert_eq!(
        leases.session_status("session-a", "run-a").unwrap()["revoked_binding"]["generation"],
        "generation-b"
    );

    issue(&leases, "session-a", "run-b", "generation-c");
    assert!(leases.session_status("session-a", "run-a").is_none());
    assert!(leases.session_status("session-a", "run-b").is_none());
}

#[test]
fn forgetting_display_does_not_change_execution_or_allow_late_terminal_revival() {
    for was_live in [true, false] {
        let leases = Leases::default();
        let live = lease(&leases, "session-a", "generation-a");
        live.store(was_live, Ordering::SeqCst);
        issue(&leases, "session-a", "run-a", "generation-a");
        let terminal = revoked_status("session-a", "run-a", "generation-a");
        leases.record_status(&terminal);
        assert!(leases.session_status("session-a", "run-a").is_some());

        leases.forget_display("session-a");
        assert!(leases.session_status("session-a", "run-a").is_none());
        assert!(leases.display_issued.lock().unwrap().is_empty());
        let active = leases.active.lock().unwrap();
        let (generation, current_live) = active.get("session-a").unwrap();
        assert_eq!(generation, "generation-a");
        assert!(Arc::ptr_eq(&live, current_live));
        assert_eq!(current_live.load(Ordering::SeqCst), was_live);
        drop(active);

        leases.record_status(&terminal);
        assert!(leases.session_status("session-a", "run-a").is_none());
        assert!(leases.display_issued.lock().unwrap().is_empty());
    }
}

#[test]
fn session_close_and_issue_order_cannot_restore_display_or_change_execution() {
    for issue_before_stop in [true, false] {
        for was_live in [true, false] {
            let leases = Leases::default();
            let live = lease(&leases, "session-a", "generation-a");
            live.store(was_live, Ordering::SeqCst);
            let stopped = AtomicBool::new(false);
            if issue_before_stop {
                leases.record_issued("session-a", "run-a", "generation-a", &stopped);
                assert_eq!(leases.display_issued.lock().unwrap().len(), 1);
            }
            stopped.store(true, Ordering::SeqCst);
            leases.forget_display("session-a");
            if !issue_before_stop {
                leases.record_issued("session-a", "run-a", "generation-a", &stopped);
            }
            leases.record_status(&revoked_status("session-a", "run-a", "generation-a"));
            assert!(leases.session_status("session-a", "run-a").is_none());
            assert!(leases.display_issued.lock().unwrap().is_empty());
            let active = leases.active.lock().unwrap();
            let (generation, current_live) = active.get("session-a").unwrap();
            assert_eq!(generation, "generation-a");
            assert!(Arc::ptr_eq(&live, current_live));
            assert_eq!(current_live.load(Ordering::SeqCst), was_live);
        }
    }
}

#[test]
fn missing_revoked_binding_clears_terminal_without_clearing_device_setup() {
    let leases = Leases::default();
    issue(&leases, "session-a", "run-a", "generation-a");
    leases.record_status(&json!({"installed":true}));
    leases.record_status(&revoked_status("session-a", "run-a", "generation-a"));
    assert!(leases.session_status("session-a", "run-a").is_some());
    leases.record_status(
        &json!({"enabled":false,"state":"suppressed","phase":"idle","requires_manual_unlock":true}),
    );
    assert!(leases.session_status("session-a", "run-a").is_none());
    assert_eq!(leases.status().unwrap()["installed"], true);
    assert!(leases.status().unwrap().get("revoked_binding").is_none());
}

fn assert_no_caller_identity(status: &Value) {
    for key in ["session_id", "run_id", "generation", "revoked_binding"] {
        assert!(
            status.get(key).is_none(),
            "unexpected caller identity: {key}"
        );
    }
}

#[test]
fn caller_status_redacts_foreign_disable_and_capabilities_without_mutating_raw_cache() {
    let leases = Leases::default();
    lease(&leases, "session-a", "generation-a");
    issue(&leases, "session-a", "run-a", "generation-a");
    for raw in [
        native_status("session-a", "run-a", "generation-a"),
        revoked_status("session-a", "run-a", "generation-a"),
    ] {
        leases.record_status(&raw);
        let cached = leases.status.lock().unwrap().clone();
        let filtered = leases.caller_status("session-b", "run-b", &raw);
        assert_no_caller_identity(&filtered);
        assert_eq!(filtered["state"], raw["state"]);
        assert_eq!(filtered["phase"], raw["phase"]);
        assert_eq!(filtered["enabled"], raw["enabled"]);

        let capabilities = json!({"capabilities":{"locked_use":raw,
            "keyboard_input":{"unicode":true}},"other":"preserved"});
        let mut output = capabilities.clone();
        if let Some(status) = output.pointer_mut("/capabilities/locked_use") {
            *status = leases.caller_status("session-b", "run-b", status);
        }
        assert_no_caller_identity(&output["capabilities"]["locked_use"]);
        assert_eq!(
            output["capabilities"]["keyboard_input"],
            capabilities["capabilities"]["keyboard_input"]
        );
        assert_eq!(output["other"], "preserved");
        assert_eq!(capabilities["capabilities"]["locked_use"], raw);
        assert_eq!(*leases.status.lock().unwrap(), cached);
        assert_eq!(leases.session_status("session-a", "run-a"), Some(raw));
    }
}

#[test]
fn caller_status_rejects_non_objects_without_mutating_raw_cache() {
    let leases = Leases::default();
    lease(&leases, "session-a", "generation-a");
    let raw = native_status("session-a", "run-a", "generation-a");
    leases.record_status(&raw);
    let cached = leases.status.lock().unwrap().clone();
    for invalid in [
        Value::Null,
        json!(false),
        json!(3),
        json!(raw.to_string()),
        json!([
            raw.clone(),
            revoked_status("session-a", "run-a", "generation-a")
        ]),
    ] {
        assert_eq!(
            leases.caller_status("session-a", "run-a", &invalid),
            Value::Null
        );
        assert_eq!(
            leases.caller_status("session-b", "run-b", &invalid),
            Value::Null
        );
        assert_eq!(*leases.status.lock().unwrap(), cached);
    }
    assert_eq!(leases.session_status("session-a", "run-a"), Some(raw));
}

#[test]
fn caller_status_keeps_only_own_live_active_binding() {
    let leases = Leases::default();
    let live = lease(&leases, "session-a", "generation-a");
    let raw = native_status("session-a", "run-a", "generation-a");
    assert_eq!(leases.caller_status("session-a", "run-a", &raw), raw);
    assert_no_caller_identity(&leases.caller_status("session-a", "run-b", &raw));
    assert_no_caller_identity(&leases.caller_status("session-b", "run-a", &raw));
    for (key, invalid) in [
        ("generation", json!("other-generation")),
        ("enabled", json!(false)),
        ("enabled", json!("true")),
        ("state", json!("suppressed")),
        ("revoked_binding", json!({"session_id":"foreign"})),
    ] {
        let mut invalid_status = raw.clone();
        invalid_status[key] = invalid;
        assert_no_caller_identity(&leases.caller_status("session-a", "run-a", &invalid_status));
    }
    live.store(false, Ordering::SeqCst);
    assert_no_caller_identity(&leases.caller_status("session-a", "run-a", &raw));
    leases.remove("session-a");
    assert_no_caller_identity(&leases.caller_status("session-a", "run-a", &raw));
}

#[test]
fn caller_status_keeps_own_terminal_after_remove_but_rejects_stale_or_invalid_binding() {
    let leases = Leases::default();
    lease(&leases, "session-a", "generation-a");
    issue(&leases, "session-a", "run-a", "generation-a");
    leases.remove("session-a");
    let raw = revoked_status("session-a", "run-a", "generation-a");
    assert_eq!(leases.caller_status("session-a", "run-a", &raw), raw);
    assert_no_caller_identity(&leases.caller_status("session-a", "run-b", &raw));
    for (key, invalid) in [
        ("session_id", json!("session-a")),
        ("enabled", json!(true)),
        ("state", json!("active")),
        ("requires_manual_unlock", json!(true)),
        ("phase", json!("guarded")),
    ] {
        let mut invalid_status = raw.clone();
        invalid_status[key] = invalid;
        assert_no_caller_identity(&leases.caller_status("session-a", "run-a", &invalid_status));
    }
    issue(&leases, "session-a", "run-a", "generation-b");
    assert_no_caller_identity(&leases.caller_status("session-a", "run-a", &raw));
    let current = revoked_status("session-a", "run-a", "generation-b");
    assert_eq!(
        leases.caller_status("session-a", "run-a", &current),
        current
    );
    leases.forget_display("session-a");
    assert_no_caller_identity(&leases.caller_status("session-a", "run-a", &current));
}

fn session(owner: &Owner, id: &str, conversation: &str, run: &str) -> Arc<Session> {
    Arc::new(Session {
        resources: Default::default(),
        dispatch: tokio::sync::Mutex::new(()),
        owner: owner.clone(),
        context: CuaCallContext {
            user_id: owner.user_id.clone(),
            tenant_id: owner.tenant_id.clone(),
            project_id: owner.project_id.clone(),
            device_id: owner.device_id.clone(),
            session_id: id.into(),
            conversation_id: conversation.into(),
            run_id: run.into(),
            input_mode: Default::default(),
        },
        revision: 0,
        stopped: AtomicBool::new(false),
        paused: AtomicBool::new(false),
        user_control: Default::default(),
        presentation: Mutex::new(json!({"phase":"idle"})),
        child: None,
        cloud: None,
    })
}

#[test]
fn snapshot_binds_locked_status_only_to_the_matching_owner_session_and_run() {
    let state = crate::local_runtime::tests::test_state("cua-locked-projection");
    let owner = super::super::tests::owner(&state);
    let mut other_owner = owner.clone();
    other_owner.user_id = "another-user".into();
    let selected = session(&owner, "selected", "conversation-a", "run-a");
    let others = [
        session(&owner, "other-conversation", "conversation-b", "run-b"),
        session(&owner, "other-run", "conversation-a", "old-run"),
        session(&other_owner, "other-owner", "conversation-c", "run-c"),
    ];
    {
        let mut sessions = state.computer_use.sessions.lock().unwrap();
        for session in std::iter::once(&selected).chain(&others) {
            sessions.insert(session.context.session_id.clone(), session.clone());
        }
    }
    let leases = &state.computer_use.locked_use;
    lease(leases, "selected", "generation-a");
    lease(leases, "other-owner", "generation-c");
    leases.record_status(&native_status("selected", "run-a", "generation-a"));

    let snapshot = api::snapshot(&state, &owner).unwrap();
    let sessions = snapshot["sessions"].as_array().unwrap();
    assert_eq!(sessions.len(), 3);
    assert_eq!(
        sessions
            .iter()
            .filter(|s| s.get("locked_use").is_some())
            .count(),
        1
    );
    let projected = sessions
        .iter()
        .find(|s| s["session_id"] == "selected")
        .unwrap();
    assert_eq!(projected["locked_use"]["phase"], "armed");
    assert_eq!(projected["locked_use"]["session_id"], "selected");
    assert_eq!(projected["locked_use"]["run_id"], "run-a");
    assert_eq!(projected["locked_use"]["generation"], "generation-a");
    assert!(snapshot["locked_use"].get("session_id").is_none());
    let other_snapshot = api::snapshot(&state, &other_owner).unwrap();
    assert_eq!(other_snapshot["sessions"].as_array().unwrap().len(), 1);
    assert!(other_snapshot["sessions"][0].get("locked_use").is_none());

    issue(leases, "selected", "run-a", "generation-a");
    leases.remove("selected");
    leases.record_status(&revoked_status("selected", "run-a", "generation-a"));
    let terminal_snapshot = api::snapshot(&state, &owner).unwrap();
    let terminal_sessions = terminal_snapshot["sessions"].as_array().unwrap();
    assert_eq!(
        terminal_sessions
            .iter()
            .filter(|s| s.get("locked_use").is_some())
            .count(),
        1
    );
    let terminal = terminal_sessions
        .iter()
        .find(|s| s["session_id"] == "selected")
        .unwrap();
    assert_eq!(
        terminal["locked_use"]["revoked_binding"]["generation"],
        "generation-a"
    );
    assert!(terminal["locked_use"].get("generation").is_none());
    assert!(
        terminal_snapshot["locked_use"]
            .get("revoked_binding")
            .is_none()
    );
    let other_snapshot = api::snapshot(&state, &other_owner).unwrap();
    assert!(other_snapshot["sessions"][0].get("locked_use").is_none());

    selected.stopped.store(true, Ordering::SeqCst);
    let stopped = api::snapshot(&state, &owner).unwrap();
    assert!(
        stopped["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|s| s.get("locked_use").is_none())
    );
    leases.record_status(&native_status("other-owner", "run-c", "generation-c"));
    let current = api::snapshot(&state, &owner).unwrap();
    assert!(
        current["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|s| s.get("locked_use").is_none())
    );
    let other_snapshot = api::snapshot(&state, &other_owner).unwrap();
    assert_eq!(
        other_snapshot["sessions"][0]["locked_use"]["phase"],
        "armed"
    );

    let root = state.workspace_root.lock().unwrap().clone();
    drop(state);
    std::fs::remove_dir_all(root).unwrap();
}
