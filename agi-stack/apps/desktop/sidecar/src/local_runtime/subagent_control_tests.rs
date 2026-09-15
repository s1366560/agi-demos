async fn setup_child_control() -> (
    Arc<LocalRuntimeState>,
    AuthenticatedContext,
    LocalConversation,
    DesktopRun,
    Arc<LocalRunControl>,
) {
    let state = test_state("subagent-control-test-session");
    let auth = state
        .session_store
        .validate_session_credential(
            "subagent-control-test-session",
            Utc::now().timestamp_millis(),
        )
        .expect("session")
        .expect("authenticated");
    let (conversation, run) = seed_controlled_run(&state, "subagent-controls");
    state
        .ensure_authoritative_launch_checkpoint(&run)
        .await
        .expect("authoritative parent checkpoint");
    state.session_store.put_managed_resource(
        ManagedResourceKind::SubAgent, "tenant", "local", "control-reader", "active", None,
        json!({"id":"control-reader", "name":"control-reader", "status":"active", "enabled":true,
            "project_id":"local-project", "system_prompt":"Inspect only.", "allowed_tools":[], "allowed_skills":[], "allowed_mcp_servers":[]}),
        Utc::now().timestamp_millis(),
    ).expect("subagent");
    let parent = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .expect("parent claim");
    (state, auth, conversation, run, parent)
}

fn child_command(
    conversation: &LocalConversation,
    run: &DesktopRun,
    child: &str,
    action: &str,
    key: &str,
) -> Value {
    json!({"type":action, "conversation_id":conversation.id, "run_id":child,
        "expected_run_revision":run.revision, "idempotency_key":key,
        "instruction": if action == "steer" { json!("Use the revised child-only objective") } else { Value::Null }})
}

#[tokio::test]
async fn subagent_steering_reaches_real_child_checkpoint_and_isolates_sibling_and_parent() {
    let (state, auth, conversation, run, parent) = setup_child_control().await;
    let child = state
        .subagent_controls
        .register(
            "child-a",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            Arc::clone(&parent),
        )
        .expect("child");
    let sibling = state
        .subagent_controls
        .register(
            "child-b",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            Arc::clone(&parent),
        )
        .expect("sibling");
    let command = child_command(&conversation, &run, "child-a", "steer", "steer-1");
    let receipt = subagent_control::handle_command(&state, &auth, &command).await;
    assert_eq!(receipt["accepted"], true, "{receipt}");
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &command).await["duplicate"],
        true
    );
    assert!(matches!(
        sibling
            .directive("child-b", 0)
            .await
            .expect("sibling directive"),
        RunDirective::Continue
    ));
    assert!(matches!(
        parent
            .directive(&conversation.id, 0)
            .await
            .expect("parent directive"),
        RunDirective::Continue
    ));
    let host = Arc::new(state.tool_host.lock().expect("tools").clone());
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "child complete".to_string(),
        }])),
        host,
        Arc::clone(&state.checkpoints),
        state.clock.clone(),
    );
    let outcome = engine
        .run_controlled(
            "child-a",
            "Original child goal",
            Some(&run.project_id),
            child,
        )
        .await
        .expect("controlled engine");
    assert_eq!(outcome.status, SessionStatus::Finished);
    assert_eq!(outcome.applied_steering_ids.len(), 1);
    assert!(outcome
        .transcript
        .iter()
        .any(|entry| entry.role == Role::Human
            && entry.content == "Use the revised child-only objective"));
    let persisted = state
        .checkpoints
        .load("child-a")
        .await
        .expect("load checkpoint")
        .expect("child checkpoint");
    assert_eq!(persisted.applied_steering_ids, outcome.applied_steering_ids);
    assert!(!state.subagent_controls.complete("child-a"));
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &command).await["duplicate"],
        true
    );
    let new_command = child_command(
        &conversation,
        &run,
        "child-a",
        "steer",
        "steer-after-terminal",
    );
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &new_command).await["accepted"],
        false
    );
}

#[tokio::test]
async fn subagent_kill_stops_real_execution_and_parent_cancel_propagates_to_remaining_child() {
    let (state, auth, conversation, run, parent) = setup_child_control().await;
    let child = state
        .subagent_controls
        .register(
            "child-kill",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            Arc::clone(&parent),
        )
        .expect("child");
    let sibling = state
        .subagent_controls
        .register(
            "child-survivor",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            Arc::clone(&parent),
        )
        .expect("sibling");
    let command = child_command(&conversation, &run, "child-kill", "kill_run", "kill-1");
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &command).await["accepted"],
        true
    );
    assert!(matches!(
        sibling
            .directive("child-survivor", 0)
            .await
            .expect("sibling directive"),
        RunDirective::Continue
    ));
    assert!(matches!(
        parent
            .directive(&conversation.id, 0)
            .await
            .expect("parent directive"),
        RunDirective::Continue
    ));
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![])),
        Arc::new(state.tool_host.lock().expect("tools").clone()),
        Arc::clone(&state.checkpoints),
        state.clock.clone(),
    );
    let outcome = engine
        .run_controlled(
            "child-kill",
            "Never execute this goal",
            Some(&run.project_id),
            child,
        )
        .await
        .expect("cancel engine");
    assert_eq!(outcome.status, SessionStatus::Cancelled);
    assert_eq!(outcome.round, 0);
    assert!(state.subagent_controls.complete("child-kill"));
    parent.request_cancel();
    let sibling_outcome = engine
        .run_controlled(
            "child-survivor",
            "Stop with parent",
            Some(&run.project_id),
            sibling,
        )
        .await
        .expect("cancel sibling");
    assert_eq!(sibling_outcome.status, SessionStatus::Cancelled);
    assert!(state.subagent_controls.complete("child-survivor"));
}

#[tokio::test]
async fn subagent_controls_reject_wrong_identity_revision_scope_and_changed_authority() {
    let (state, auth, conversation, run, parent) = setup_child_control().await;
    let child = state
        .subagent_controls
        .register(
            "child-scoped",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            Arc::clone(&parent),
        )
        .expect("child");
    let command = child_command(&conversation, &run, "child-scoped", "steer", "scope-check");
    for changes in [
        json!({"run_id":run.id}),
        json!({"run_id":"missing-child"}),
        json!({"expected_run_revision":run.revision + 1}),
        json!({"conversation_id":"foreign-conversation"}),
        json!({"cascade":true}),
        json!({"instruction":" "}),
    ] {
        let mut denied = command.clone();
        denied
            .as_object_mut()
            .expect("command")
            .extend(changes.as_object().expect("changes").clone());
        assert_eq!(
            subagent_control::handle_command(&state, &auth, &denied).await["accepted"],
            false,
            "{denied}"
        );
    }
    let mut foreign_auth = auth.clone();
    foreign_auth.workspace.tenant_id = "other-tenant".to_string();
    assert_eq!(
        subagent_control::handle_command(&state, &foreign_auth, &command).await["accepted"],
        false
    );
    assert!(matches!(
        child
            .directive("child-scoped", 0)
            .await
            .expect("unmodified child"),
        RunDirective::Continue
    ));
    assert!(matches!(
        parent
            .directive(&conversation.id, 0)
            .await
            .expect("unmodified parent"),
        RunDirective::Continue
    ));
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &command).await["accepted"],
        true
    );
    let mut collision = command.clone();
    collision["instruction"] = json!("Different instruction with same key");
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &collision).await["reason_code"],
        "control_idempotency_conflict"
    );
    state.session_store.put_managed_resource(
        ManagedResourceKind::SubAgent, "tenant", "local", "control-reader", "active", None,
        json!({"id":"control-reader", "name":"control-reader", "enabled":false, "status":"active"}),
        Utc::now().timestamp_millis(),
    ).expect("disable target");
    let revoked = child_command(&conversation, &run, "child-scoped", "kill_run", "revoked");
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &revoked).await["reason_code"],
        "subagent_control_denied"
    );
}

#[tokio::test]
async fn subagent_participants_are_actual_executions_and_old_parent_registration_is_retired() {
    let (state, _auth, conversation, run, parent) = setup_child_control().await;
    assert!(state
        .subagent_controls
        .participants(&conversation.id)
        .is_empty());
    let initial_view = state.conversation_value(&conversation);
    assert_eq!(initial_view["participant_agents"], json!(["builtin:all-access"]));
    assert_eq!(initial_view["coordinator_agent_id"], "builtin:all-access");
    assert_eq!(initial_view["focused_agent_id"], "builtin:all-access");
    state
        .subagent_controls
        .register(
            "previous-child",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            Arc::clone(&parent),
        )
        .expect("registered child");
    assert_eq!(
        state.subagent_controls.participants(&conversation.id),
        ["control-reader"]
    );
    state.subagent_controls.complete("previous-child");
    let mut next_run = run.clone();
    next_run.id = "next-parent-run".to_string();
    state
        .subagent_controls
        .register(
            "next-child",
            &conversation.id,
            &next_run,
            "next-reader",
            "builtin:all-access",
            parent,
        )
        .expect("next child");
    assert!(!state.subagent_controls.is_registered("previous-child"));
    assert_eq!(
        state.subagent_controls.participants(&conversation.id),
        ["next-reader"]
    );
    state.release_agent_run(&conversation.id);
    assert!(!state.subagent_controls.is_registered("next-child"));
}

#[tokio::test]
async fn subagent_host_emits_registered_execution_identity_for_each_real_invocation() {
    let (state, _auth, conversation, run, _parent) = setup_child_control().await;
    let agent = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Agent,
            "project",
            &conversation.project_id,
            "builtin:all-access",
        )
        .expect("agent")
        .expect("builtin");
    let profile =
        execution_profile::ExecutionProfile::resolve("builtin:all-access", &agent, None, None)
            .expect("profile");
    let host = state
        .subagent_agent_tool_host(
            &conversation,
            &run,
            &profile,
            &[],
            Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
                answer: "Child answer".to_string(),
            }])),
            4,
        ).await
        .expect("host")
        .expect("delegation host");
    let output = authorized_tool_host::with_authorized_invocation_context(
        authorized_tool_host::AuthorizedInvocationContext {
            invocation_id: "child-authorized-invocation".to_string(),
            run_id: run.id.clone(),
            run_revision: run.revision,
        },
        host.call(
            "subagent",
            &json!({"subagent_id":"control-reader", "task":"Do the child task"}).to_string(),
        ),
    )
    .await
    .expect("real delegated child");
    assert!(output.contains("Child answer"));
    let retry = authorized_tool_host::with_authorized_invocation_context(
        authorized_tool_host::AuthorizedInvocationContext {
            invocation_id: "child-authorized-invocation".to_string(),
            run_id: run.id.clone(),
            run_revision: run.revision,
        },
        host.call(
            "subagent",
            &json!({"subagent_id":"control-reader", "task":"Do the child task"}).to_string(),
        ),
    )
    .await
    .expect("same real invocation reuses terminal child checkpoint");
    assert_eq!(retry, output);
    let timeline = state
        .session_store
        .timeline(&conversation.id, 100)
        .expect("timeline");
    assert_eq!(
        timeline
            .iter()
            .filter(|event| event["type"] == "subagent_started")
            .count(),
        1,
        "terminal invocation replay must not publish another execution"
    );
    assert_eq!(
        timeline
            .iter()
            .filter(|event| event["type"] == "subagent_completed")
            .count(),
        1
    );
    let started = timeline
        .iter()
        .find(|event| event["type"] == "subagent_started")
        .expect("started");
    let completed = timeline
        .iter()
        .find(|event| event["type"] == "subagent_completed")
        .expect("completed");
    assert_eq!(started["payload"]["control_registered"], true);
    assert_eq!(started["payload"]["parent_run_id"], run.id);
    assert_eq!(started["payload"]["parent_run_revision"], run.revision);
    let child_id = started["payload"]["run_id"].as_str().expect("execution id");
    assert!(child_id.starts_with("local-subagent-"));
    assert_ne!(child_id, run.id);
    assert_eq!(completed["payload"]["run_id"], child_id);
    assert!(state
        .checkpoints
        .load(child_id)
        .await
        .expect("checkpoint")
        .is_some());
}

#[tokio::test]
async fn subagent_websocket_control_returns_the_existing_ack_channel_and_steers_the_child() {
    use tokio_tungstenite::tungstenite::client::IntoClientRequest;
    let (state, _auth, conversation, run, parent) = setup_child_control().await;
    let child = state
        .subagent_controls
        .register(
            "child-ws",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            parent,
        )
        .expect("child");
    let listener = TcpListener::bind(("127.0.0.1", 0)).await.expect("listener");
    let address = listener.local_addr().expect("address");
    let app = local_router(Arc::clone(&state));
    let server = tokio::spawn(async move { axum::serve(listener, app).await.expect("server") });
    let mut request = format!("ws://{address}/api/v1/agent/ws")
        .into_client_request()
        .expect("request");
    request.headers_mut().insert(
        "Authorization",
        "Bearer subagent-control-test-session"
            .parse()
            .expect("header"),
    );
    let (mut socket, _) = tokio_tungstenite::connect_async(request)
        .await
        .expect("authenticated websocket");
    let command = child_command(&conversation, &run, "child-ws", "steer", "ws-steer");
    socket
        .send(tokio_tungstenite::tungstenite::Message::Text(
            command.to_string(),
        ))
        .await
        .expect("control message");
    let response = tokio::time::timeout(std::time::Duration::from_secs(2), socket.next())
        .await
        .expect("bounded acknowledgement")
        .expect("response")
        .expect("websocket response");
    let receipt: Value = serde_json::from_str(response.to_text().expect("text")).expect("ack json");
    assert_eq!(receipt["type"], "control_command_ack");
    assert_eq!(receipt["action"], "steer");
    assert_eq!(receipt["run_id"], "child-ws");
    assert_eq!(receipt["accepted"], true, "{receipt}");
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "Socket-directed answer".to_string(),
        }])),
        Arc::new(state.tool_host.lock().expect("tools").clone()),
        Arc::clone(&state.checkpoints),
        state.clock.clone(),
    );
    let outcome = engine
        .run_controlled("child-ws", "Child goal", Some(&run.project_id), child)
        .await
        .expect("child engine");
    assert!(outcome
        .transcript
        .iter()
        .any(|entry| entry.role == Role::Human
            && entry.content == "Use the revised child-only objective"));
    socket.close(None).await.expect("close websocket");
    server.abort();
}

#[tokio::test]
async fn subagent_controls_require_the_current_parent_checkpoint_ownership() {
    let (state, auth, conversation, run, parent) = setup_child_control().await;
    let child = state
        .subagent_controls
        .register(
            "child-owned",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            Arc::clone(&parent),
        )
        .expect("child");
    state
        .checkpoints
        .delete(&conversation.id)
        .await
        .expect("remove parent checkpoint");
    let steer = child_command(
        &conversation,
        &run,
        "child-owned",
        "steer",
        "missing-checkpoint",
    );
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &steer).await["reason_code"],
        "checkpoint_control_authority_unavailable"
    );
    state
        .ensure_authoritative_launch_checkpoint(&run)
        .await
        .expect("restore checkpoint");
    let mut replacement = run.clone();
    replacement.id = "different-parent-authority".to_string();
    state
        .session_store
        .bind_checkpoint_authority(&replacement, &now_iso())
        .expect("new owner");
    let kill = child_command(
        &conversation,
        &run,
        "child-owned",
        "kill_run",
        "foreign-checkpoint",
    );
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &kill).await["reason_code"],
        "checkpoint_control_authority_unavailable"
    );
    assert!(matches!(
        child
            .directive("child-owned", 0)
            .await
            .expect("child remains unmodified"),
        RunDirective::Continue
    ));
    assert!(matches!(
        parent
            .directive(&conversation.id, 0)
            .await
            .expect("parent remains unmodified"),
        RunDirective::Continue
    ));
}

#[tokio::test]
async fn subagent_controls_pin_the_launch_agent_and_propagate_parent_pause() {
    let (state, auth, conversation, run, parent) = setup_child_control().await;
    let child = state
        .subagent_controls
        .register(
            "child-original-agent",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            Arc::clone(&parent),
        )
        .expect("child");
    assert!(
        state
            .subagent_controls
            .register(
                "child-original-agent",
                &conversation.id,
                &run,
                "control-reader",
                "builtin:all-access",
                Arc::clone(&parent)
            )
            .is_err(),
        "active invocation cannot run twice"
    );
    state
        .session_store
        .save_execution_selection(
            &conversation.id,
            "changed-agent-message",
            &execution_selection::ExecutionSelection {
                agent_id: Some("different-agent".to_string()),
                forced_skill_id: None,
                subagent_id: None,
            },
            &now_iso(),
        )
        .expect("select a different parent agent");
    let steer = child_command(
        &conversation,
        &run,
        "child-original-agent",
        "steer",
        "changed-agent",
    );
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &steer).await["reason_code"],
        "subagent_control_denied"
    );
    parent.request_pause();
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![])),
        Arc::new(state.tool_host.lock().expect("tools").clone()),
        Arc::clone(&state.checkpoints),
        state.clock.clone(),
    );
    let outcome = engine
        .run_controlled(
            "child-original-agent",
            "Pause with parent",
            Some(&run.project_id),
            child,
        )
        .await
        .expect("pause child");
    assert_eq!(outcome.status, SessionStatus::Paused);
    assert_eq!(outcome.round, 0);
}

#[tokio::test]
async fn subagent_cancel_between_steering_delivery_and_ack_persists_cancellation() {
    let (state, auth, conversation, run, parent) = setup_child_control().await;
    let child = state
        .subagent_controls
        .register(
            "child-cancel-race",
            &conversation.id,
            &run,
            "control-reader",
            "builtin:all-access",
            parent,
        )
        .expect("child");
    let steer = child_command(
        &conversation,
        &run,
        "child-cancel-race",
        "steer",
        "delivered-steer",
    );
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &steer).await["accepted"],
        true
    );
    let RunDirective::Steer(instruction) = child
        .directive("child-cancel-race", 0)
        .await
        .expect("deliver steering")
    else {
        panic!("expected actual steering instruction");
    };
    let kill = child_command(
        &conversation,
        &run,
        "child-cancel-race",
        "kill_run",
        "concurrent-kill",
    );
    assert_eq!(
        subagent_control::handle_command(&state, &auth, &kill).await["accepted"],
        true
    );
    child
        .acknowledge_steering("child-cancel-race", &instruction.id, 0)
        .await
        .expect("cancelled delivery acknowledgement is safe");
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![])),
        Arc::new(state.tool_host.lock().expect("tools").clone()),
        Arc::clone(&state.checkpoints),
        state.clock.clone(),
    );
    let outcome = engine
        .run_controlled(
            "child-cancel-race",
            "Stop at boundary",
            Some(&run.project_id),
            child,
        )
        .await
        .expect("cancel at boundary");
    assert_eq!(outcome.status, SessionStatus::Cancelled);
    assert_eq!(
        state
            .checkpoints
            .load("child-cancel-race")
            .await
            .expect("checkpoint")
            .expect("cancelled checkpoint")
            .status,
        SessionStatus::Cancelled
    );
}
