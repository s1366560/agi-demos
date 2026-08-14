#[tokio::test]
async fn attached_subagent_selection_with_null_allowlist_remains_a_real_delegation_target() {
    const CHILD_ANSWER: &str = "README evidence verified child-answer-secret-a68b";
    const CHILD_TASK: &str = "Inspect README.md task-secret-a68b";
    let state = test_state("attached-subagent-a68b-secret");
    let (seeded_conversation, run) = seed_controlled_run(&state, "a68b-attached-subagent");
    let conversation = state
        .session_store
        .conversation(&seeded_conversation.id)
        .expect("load a68b conversation")
        .expect("a68b conversation");
    assert_eq!(conversation.current_mode, ConversationRunMode::Build);

    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Skill,
            "project",
            "local-project",
            "qa-read-skill",
            "active",
            None,
            json!({
                "id": "qa-read-skill",
                "name": "qa-read-skill",
                "display_name": "QA Read Skill",
                "status": "active",
                "description": "Use direct read evidence.",
                "tools": ["read", "write"],
            }),
            Utc::now().timestamp_millis(),
        )
        .expect("seed forced skill");
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Agent,
            "project",
            "local-project",
            "qa-read-agent",
            "active",
            None,
            json!({
                "id": "qa-read-agent",
                "name": "qa-read-agent",
                "display_name": "QA Read Agent",
                "project_id": "local-project",
                "enabled": true,
                "status": "active",
                "system_prompt": "PARENT_AGENT_INSTRUCTIONS",
                "allowed_tools": ["read", "write", "glob", "grep"],
                "allowed_skills": ["qa-read-skill"],
                "allowed_mcp_servers": [],
                "can_spawn": true,
                "spawn_policy": {
                    "allowed_subagents": null
                },
            }),
            Utc::now().timestamp_millis(),
        )
        .expect("seed QA Read Agent");
    for (id, prompt, tools) in [
        (
            "qa-path-reader",
            "CHILD_PATH_READER_INSTRUCTIONS",
            json!(["read"]),
        ),
        (
            "qa-other-reader",
            "OTHER_CHILD_INSTRUCTIONS",
            json!(["write"]),
        ),
    ] {
        state
            .session_store
            .put_managed_resource(
                ManagedResourceKind::SubAgent,
                "tenant",
                "local",
                id,
                "active",
                None,
                json!({
                    "id": id,
                    "tenant_id": "local",
                    "project_id": "local-project",
                    "name": id,
                    "display_name": if id == "qa-path-reader" {
                        "QA Path Reader"
                    } else {
                        "QA Other Reader"
                    },
                    "system_prompt": prompt,
                    "enabled": true,
                    "status": "active",
                    "source": "database",
                    "allowed_tools": tools,
                    "allowed_skills": ["qa-read-skill"],
                    "allowed_mcp_servers": [],
                }),
                Utc::now().timestamp_millis(),
            )
            .expect("seed attached SubAgent fixture");
    }
    state
        .session_store
        .save_execution_selection(
            &conversation.id,
            "message-a68b-attached-subagent",
            &execution_selection::ExecutionSelection {
                agent_id: Some("qa-read-agent".to_string()),
                forced_skill_id: Some("qa-read-skill".to_string()),
                subagent_id: Some("qa-path-reader".to_string()),
            },
            &now_iso(),
        )
        .expect("save a68b execution selection");

    let parent_profile = state
        .execution_profile(&conversation)
        .expect("resolve parent execution profile");
    assert_eq!(parent_profile.agent.id, "qa-read-agent");
    assert_eq!(
        parent_profile.skill.as_ref().map(|skill| skill.id.as_str()),
        Some("qa-read-skill")
    );
    assert_eq!(parent_profile.subagent, None);
    assert_eq!(parent_profile.allowed_tools, ["read", "write"]);
    assert!(parent_profile
        .instructions
        .contains("PARENT_AGENT_INSTRUCTIONS"));
    assert!(!parent_profile
        .instructions
        .contains("CHILD_PATH_READER_INSTRUCTIONS"));

    let observer = LocalTimelineObserver::new(
        Arc::clone(&state),
        conversation.id.clone(),
        "message-a68b-attached-subagent".to_string(),
        parent_profile.clone(),
        "Inspect README through the attached SubAgent".to_string(),
    );
    observer
        .on_finish(&conversation.id, 0, "Parent has not delegated yet")
        .await
        .expect("finish parent observation");
    assert!(!state
        .session_store
        .timeline(&conversation.id, 100)
        .expect("pre-delegation timeline")
        .iter()
        .any(|event| event["type"]
            .as_str()
            .is_some_and(|kind| kind.starts_with("subagent_"))));

    let base_tool_hosts: Vec<Arc<dyn ToolHost>> = vec![Arc::new(
        state.tool_host.lock().expect("local tool host").clone(),
    )];
    let host = state
        .subagent_agent_tool_host(
            &conversation,
            &run,
            &parent_profile,
            &base_tool_hosts,
            Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
                answer: CHILD_ANSWER.to_string(),
            }])),
            4,
        )
        .expect("build SubAgent delegation host")
        .expect("attached SubAgent must expose delegation");
    assert_eq!(host.list_tools(), ["subagent"]);
    assert_eq!(
        host.authority_metadata_by_name()["subagent"].effect,
        tool_authority::ToolEffect::Read,
        "child authority must be narrowed by the forced Skill and attached SubAgent"
    );
    let error = host
        .call(
            "subagent",
            r#"{"subagent_id":"qa-other-reader","task":"Inspect Cargo.toml"}"#,
        )
        .await
        .expect_err("attached selection must exclude every other authorized SubAgent");
    assert!(error.to_string().contains("not uniquely authorized"));
    let output = authorized_tool_host::with_authorized_invocation_context(
        authorized_tool_host::AuthorizedInvocationContext {
            invocation_id: "local-invocation-a68b-attached-subagent".to_string(),
            run_id: run.id.clone(),
            run_revision: run.revision,
        },
        host.call(
            "subagent",
            &json!({
                "subagent_id": "qa-path-reader",
                "task": CHILD_TASK,
            })
            .to_string(),
        ),
    )
    .await
    .expect("delegate to the exact attached SubAgent");
    assert!(output.contains(CHILD_ANSWER));

    let timeline = state
        .session_store
        .timeline(&conversation.id, 100)
        .expect("delegation timeline");
    for event_type in [
        "subagent_routed",
        "subagent_started",
        "subagent_session_update",
        "subagent_completed",
    ] {
        assert_eq!(
            timeline
                .iter()
                .filter(|event| event["type"] == event_type)
                .count(),
            1,
            "{event_type} must be emitted exactly once by real delegation"
        );
    }
    assert!(timeline.iter().any(|event| {
        event["type"] == "subagent_completed"
            && event["payload"]["subagent_id"] == "qa-path-reader"
            && event["payload"]["success"] == true
    }));
    let started = timeline
        .iter()
        .find(|event| event["type"] == "subagent_started")
        .expect("SubAgent start event");
    assert_eq!(started["payload"]["task"], "Delegated SubAgent task");
    assert_eq!(started["payload"]["task_bytes"], CHILD_TASK.len());
    let completed = timeline
        .iter()
        .find(|event| event["type"] == "subagent_completed")
        .expect("SubAgent completion event");
    assert_eq!(completed["payload"]["summary"], "SubAgent completed");
    assert_eq!(completed["payload"]["result_bytes"], CHILD_ANSWER.len());
    let serialized_timeline = serde_json::to_string(&timeline).expect("serialize timeline");
    assert!(!serialized_timeline.contains(CHILD_TASK));
    assert!(!serialized_timeline.contains(CHILD_ANSWER));
    assert!(!serialized_timeline.contains("task_digest"));
    assert!(!serialized_timeline.contains("result_digest"));
}

#[test]
fn invalid_authorized_subagent_profile_is_reported_instead_of_silently_hidden() {
    let state = test_state("invalid-subagent-profile-secret");
    let (conversation, run) = seed_controlled_run(&state, "invalid-subagent-profile");
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::SubAgent,
            "tenant",
            "local",
            "malformed-reviewer",
            "active",
            None,
            json!({
                "id": "malformed-reviewer",
                "tenant_id": "local",
                "project_id": "local-project",
                "name": "malformed-reviewer",
                "display_name": "Malformed Reviewer",
                "system_prompt": "This resource intentionally lacks allowed_tools.",
                "enabled": true,
                "status": "active",
                "source": "database",
                "allowed_skills": [],
                "allowed_mcp_servers": [],
            }),
            Utc::now().timestamp_millis(),
        )
        .expect("seed malformed SubAgent profile");
    let parent_profile = state
        .execution_profile(&conversation)
        .expect("resolve parent execution profile");
    let base_tool_hosts: Vec<Arc<dyn ToolHost>> = vec![Arc::new(
        state.tool_host.lock().expect("local tool host").clone(),
    )];

    let error = match state.subagent_agent_tool_host(
        &conversation,
        &run,
        &parent_profile,
        &base_tool_hosts,
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "must not run".to_string(),
        }])),
        4,
    ) {
        Ok(_) => panic!("invalid authorized target must fail host construction"),
        Err(error) => error,
    };

    assert!(error.contains("malformed-reviewer"));
    assert!(error.contains("allowed_tools"));
}

#[tokio::test]
async fn explicit_skill_and_subagent_execute_with_structured_lifecycle_evidence() {
    let state = test_state("execution-profile-secret");
    let conversation_id = "conversation-execution-profile";
    seed_plan_conversation(&state, conversation_id);
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::SubAgent,
            "tenant",
            "local",
            "qa-reviewer",
            "active",
            None,
            json!({
                "id": "qa-reviewer",
                "tenant_id": "local",
                "project_id": "local-project",
                "name": "qa-reviewer",
                "display_name": "QA Reviewer",
                "system_prompt": "Verify the plan using direct evidence.",
                "enabled": true,
                "status": "active",
                "source": "database",
                "allowed_tools": ["read", "glob", "grep"],
                "allowed_skills": ["code-exploration"],
                "allowed_mcp_servers": [],
            }),
            Utc::now().timestamp_millis(),
        )
        .expect("create QA Sub Agent");
    let response = local_router(Arc::clone(&state))
        .oneshot(authenticated_json_request(
            "POST",
            &format!("/api/v1/agent/conversations/{conversation_id}/messages"),
            "execution-profile-secret",
            json!({
                "project_id": "local-project",
                "message": "inspect and submit a plan",
                "message_id": "execution-profile-message",
                "agent_id": "builtin:all-access",
                "forced_skill_name": "code-exploration",
                "subagent_id": "qa-reviewer",
            }),
        ))
        .await
        .expect("execution profile response");
    assert_eq!(response.status(), StatusCode::OK);

    let timeline = loop {
        let timeline = state
            .session_store
            .timeline(conversation_id, 100)
            .expect("execution profile timeline");
        let active = state
            .agent_runs
            .lock()
            .expect("active agent runs")
            .contains_key(conversation_id);
        if !active && timeline.iter().any(|event| event["type"] == "complete") {
            break timeline;
        }
        tokio::task::yield_now().await;
    };
    for event_type in [
        "skill_matched",
        "skill_execution_start",
        "skill_tool_start",
        "skill_tool_result",
        "skill_execution_complete",
        "act",
        "observe",
        "complete",
    ] {
        assert!(
            timeline.iter().any(|event| event["type"] == event_type),
            "missing lifecycle event {event_type}"
        );
    }
    assert!(!timeline.iter().any(|event| {
        event["type"]
            .as_str()
            .is_some_and(|kind| kind.starts_with("subagent_"))
    }));
    assert_eq!(
        state
            .session_store
            .execution_selection(conversation_id)
            .expect("execution selection")
            .expect("stored execution selection")
            .subagent_id
            .as_deref(),
        Some("qa-reviewer")
    );
    assert!(timeline.iter().any(|event| {
        event["type"] == "complete"
            && event["message_id"] == "execution-profile-message"
            && event["payload"]["success"] == true
    }));
    assert_eq!(
        state
            .session_store
            .list_agent_plan_tasks(conversation_id)
            .expect("submitted plan")
            .len(),
        3
    );
}

#[tokio::test]
async fn active_runs_reject_cross_project_and_disabled_subagents_before_engine_start() {
    let state = test_state("execution-subagent-scope-secret");
    for (id, project_id, status, enabled) in [
        ("foreign-reviewer", "desktop-client", "active", true),
        ("disabled-reviewer", "local-project", "disabled", false),
    ] {
        state
            .session_store
            .put_managed_resource(
                ManagedResourceKind::SubAgent,
                "tenant",
                "local",
                id,
                status,
                None,
                json!({
                    "id": id,
                    "tenant_id": "local",
                    "project_id": project_id,
                    "name": id,
                    "display_name": id,
                    "system_prompt": "Review only within the declared project.",
                    "enabled": enabled,
                    "status": status,
                    "source": "database",
                    "allowed_tools": ["read"],
                    "allowed_skills": [],
                    "allowed_mcp_servers": [],
                }),
                Utc::now().timestamp_millis(),
            )
            .expect("seed guarded SubAgent");

        let conversation_id = format!("conversation-{id}");
        seed_plan_conversation(&state, &conversation_id);
        state
            .session_store
            .save_execution_selection(
                &conversation_id,
                &format!("message-{id}"),
                &execution_selection::ExecutionSelection {
                    agent_id: Some("builtin:all-access".to_string()),
                    forced_skill_id: None,
                    subagent_id: Some(id.to_string()),
                },
                &now_iso(),
            )
            .expect("save guarded execution selection");
        state.agent_engine_attempts.store(0, Ordering::SeqCst);

        Arc::clone(&state)
            .run_agent_message(
                conversation_id.clone(),
                "local-project".to_string(),
                "Inspect the active project".to_string(),
                format!("message-{id}"),
                None,
                None,
            )
            .await;

        assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 0);
        let timeline = state
            .session_store
            .timeline(&conversation_id, 100)
            .expect("guarded SubAgent timeline");
        assert!(timeline.iter().any(|item| {
            item["type"] == "error"
                && item["payload"]["error"]
                    .as_str()
                    .is_some_and(|error| error.contains("Sub Agent"))
        }));
        assert!(!timeline.iter().any(|item| {
            matches!(
                item["type"].as_str(),
                Some("act" | "observe" | "subagent_started" | "complete")
            )
        }));
    }
}

#[test]
fn composer_context_authority_scopes_structured_subagent_slots() {
    let state = test_state("composer-subagent-secret");
    let authenticated = state
        .session_store
        .validate_session_credential("composer-subagent-secret", Utc::now().timestamp_millis())
        .expect("validate session credential")
        .expect("authenticated context");
    for (id, project_id, status, enabled) in [
        ("tenant-inspector", Value::Null, "active", true),
        ("project-inspector", json!("local-project"), "active", true),
        ("foreign-inspector", json!("desktop-client"), "active", true),
        (
            "disabled-inspector",
            json!("local-project"),
            "disabled",
            false,
        ),
    ] {
        state
            .session_store
            .put_managed_resource(
                ManagedResourceKind::SubAgent,
                "tenant",
                "local",
                id,
                status,
                None,
                json!({
                    "id": id,
                    "tenant_id": "local",
                    "project_id": project_id,
                    "name": id,
                    "display_name": id,
                    "system_prompt": "Inspect the workspace using read-only tools.",
                    "enabled": enabled,
                    "status": status,
                    "source": "database",
                }),
                Utc::now().timestamp_millis(),
            )
            .expect("create scoped SubAgent");
    }
    let context = |id: &str| {
        [ComposerContextItem {
            kind: ComposerContextKind::Agent,
            resource_id: id.to_string(),
            label: id.to_string(),
            metadata: Some(json!({
                "mention_target": false,
                "execution_slot": "subagent",
                "execution_subagent_name": id,
            })),
        }]
    };

    for id in ["tenant-inspector", "project-inspector"] {
        assert!(validate_composer_context_authority(
            &state,
            &authenticated,
            "local-workspace",
            &context(id),
        )
        .is_ok());
    }
    for id in ["foreign-inspector", "disabled-inspector"] {
        assert!(validate_composer_context_authority(
            &state,
            &authenticated,
            "local-workspace",
            &context(id),
        )
        .is_err());
    }
}

#[test]
fn composer_context_authority_accepts_active_tenant_and_project_skills() {
    let state = test_state("composer-skill-secret");
    let authenticated = state
        .session_store
        .validate_session_credential("composer-skill-secret", Utc::now().timestamp_millis())
        .expect("validate session credential")
        .expect("authenticated context");
    for (scope_kind, scope_id, skill_id, status) in [
        ("tenant", "local", "tenant-review", "active"),
        (
            "project",
            "local-project",
            "project-review-disabled",
            "disabled",
        ),
        ("project", "local-project", "project-review", "active"),
    ] {
        state
            .session_store
            .put_managed_resource(
                ManagedResourceKind::Skill,
                scope_kind,
                scope_id,
                skill_id,
                status,
                None,
                json!({
                    "id": skill_id,
                    "name": skill_id,
                    "status": status,
                }),
                Utc::now().timestamp_millis(),
            )
            .expect("create managed Skill");
    }

    let tenant_context = [ComposerContextItem {
        kind: ComposerContextKind::Skill,
        resource_id: "tenant-review".to_string(),
        label: "Tenant review".to_string(),
        metadata: Some(json!({ "execution_slot": "skill" })),
    }];
    assert!(validate_composer_context_authority(
        &state,
        &authenticated,
        "local-workspace",
        &tenant_context,
    )
    .is_ok());

    let disabled_project_context = [ComposerContextItem {
        kind: ComposerContextKind::Skill,
        resource_id: "project-review-disabled".to_string(),
        label: "Disabled project review".to_string(),
        metadata: Some(json!({ "execution_slot": "skill" })),
    }];
    assert!(validate_composer_context_authority(
        &state,
        &authenticated,
        "local-workspace",
        &disabled_project_context,
    )
    .is_err());

    let project_context = [ComposerContextItem {
        kind: ComposerContextKind::Skill,
        resource_id: "project-review".to_string(),
        label: "Project review".to_string(),
        metadata: Some(json!({ "execution_slot": "skill" })),
    }];
    assert!(validate_composer_context_authority(
        &state,
        &authenticated,
        "local-workspace",
        &project_context,
    )
    .is_ok());
}
