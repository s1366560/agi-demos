use super::*;

#[cfg(target_os = "macos")]
#[test]
fn cold_nested_repl_schema_validation_survives_default_tokio_stack() {
    const CHILD: &str = "AGISTACK_COLD_NESTED_SCHEMA_TEST";
    if std::env::var_os(CHILD).is_none() {
        // Start a fresh process so other schema tests cannot warm lazy meta-schema
        // validators before the real REPL's nested tool execution reaches them.
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "local_runtime::agent_boundary_v2::tests::cold_nested_repl_schema_validation_survives_default_tokio_stack", "--nocapture"])
            .env(CHILD, "1").output().unwrap();
        assert!(
            output.status.success(),
            "cold REPL subprocess failed: {}\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        return;
    }
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .unwrap()
        .block_on(async {
            tokio::spawn(cold_nested_repl_schema_validation())
                .await
                .unwrap()
        });
}

#[cfg(target_os = "macos")]
async fn cold_nested_repl_schema_validation() {
    use crate::local_runtime::knowledge_authority_v2::agent_access::{self, RunAuthorization};
    use agistack_core::ports::ToolDefinition;
    use agistack_plugin_host::{
        desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
        parse_profile_snapshot_v2, DataPlaneTargetV2, LoaderV2,
    };
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct NativeSchemaHost(Arc<AtomicUsize>);
    #[async_trait]
    impl ToolHost for NativeSchemaHost {
        fn list_tools(&self) -> Vec<String> {
            vec![
                "computer_list_apps".into(),
                "computer_get_app_state".into(),
                "browser_read_operation".into(),
            ]
        }
        fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
            let metadata = if name == "browser_read_operation" {
                agistack_adapters_browser::host::list_tool_metadata()
                    .into_iter()
                    .find(|value| value["name"] == name)?
            } else {
                agistack_adapters_cua::tool_definitions().get(name)?.clone()
            };
            Some(ToolDefinition {
                name: name.into(),
                description: None,
                input_schema: metadata.get("inputSchema").cloned(),
            })
        }
        async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
            if tool == "browser_read_operation" {
                return Ok("[]".into());
            }
            // Keep the native host's own validator in the exercised path too.
            agistack_adapters_cua::validate_tool_input(
                tool,
                &serde_json::from_str(input).unwrap(),
            )?;
            self.0.fetch_add(1, Ordering::SeqCst);
            Ok(if tool == "computer_list_apps" {
                "{\"apps\":[]}"
            } else {
                "{\"text\":\"fixture\"}"
            }
            .into())
        }
    }
    let (state, conversation, run, root) =
        super::super::cua_repl::test_support::state("cold-nested-schema");
    let snapshot = parse_profile_snapshot_v2(include_str!(
        "../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    let generation = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
            super::super::computer_use_v2::definition().unwrap(),
        ],
    )
    .stage(snapshot.clone())
    .await
    .unwrap();
    state
        .platform_plugin_authority_v2
        .publish_local_baseline(
            &snapshot,
            &serde_json::to_value(&snapshot).unwrap(),
            generation,
        )
        .await;
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let boundary = AgentBoundaryV2::new(
        &state,
        &conversation,
        "schema-message",
        "schema-operation",
        lease.clone(),
    )
    .unwrap();
    let auth = state.session_store.validate_session_credential(
        "cold-nested-schema", chrono::Utc::now().timestamp_millis(),
    ).unwrap().unwrap();
    let authorization = RunAuthorization::capture(
        auth, Some(lease), &conversation, &run.message_id, Some(&run.id),
    ).unwrap();
    agent_access::scope(Some(authorization), async {
    state.claim_agent_run(&conversation.id, Some(&run.id)).unwrap();
    let profile = state.execution_profile(&conversation).unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let host = super::super::cua_repl::wrap_tools(
        &state,
        Arc::new(NativeSchemaHost(calls.clone())),
        &conversation,
        &run,
        &profile,
        Some(boundary.clone()),
    );
    let mut actions = [
        "const state = await cua.getState({emit:false}); if (state.errors) throw new Error(state.errors.join(';')); await nodeRepl.rpc('computer.call',{tool:'computer_get_app_state',arguments:{app:'fixture'}});",
        "await nodeRepl.rpc('computer.call',{tool:'computer_get_app_state',arguments:{app:42}})",
        "await nodeRepl.rpc('computer.call',{tool:'computer_get_app_state',arguments:{app:'fixture'}})",
    ].into_iter().map(|code| agistack_core::agent::types::AgentAction::CallTool {
        tool: "cua_repl_js".into(), input_json: json!({"code":code}).to_string(),
    }).collect::<Vec<_>>();
    actions.push(agistack_core::agent::types::AgentAction::Finish {
        answer: "checked".into(),
    });
    #[derive(Default)]
    struct Observations(Mutex<Vec<Value>>);
    #[async_trait]
    impl agistack_core::agent::react::ReActObserver for Observations {
        async fn on_tool_result(
            &self,
            _: &str,
            _: u64,
            _: &str,
            _: &str,
            output: &str,
        ) -> CoreResult<()> {
            self.0
                .lock()
                .unwrap()
                .push(serde_json::from_str(output).unwrap());
            Ok(())
        }
    }
    struct Continue;
    #[async_trait]
    impl agistack_core::agent::react::ReActControl for Continue {
        async fn directive(
            &self,
            _: &str,
            _: u64,
        ) -> CoreResult<agistack_core::agent::react::RunDirective> {
            Ok(agistack_core::agent::react::RunDirective::Continue)
        }
    }
    let observer = Arc::new(Observations::default());
    let engine = boundary.wrap_engine(ReActEngine::new(
        Arc::new(agistack_adapters_mem::ScriptedLlm::new(actions)),
        host.clone(),
        state.checkpoints.clone(),
        state.clock.clone(),
    ));
    let result = engine
        .run_observed_controlled(
            "cold-schema-engine",
            "Exercise native schema validation",
            Some(&conversation.project_id),
            observer.clone(),
            Arc::new(Continue),
        )
        .await
        .unwrap();
    assert_eq!(
        result.status,
        agistack_core::agent::types::SessionStatus::Finished
    );
    assert_eq!(
        observer
            .0
            .lock()
            .unwrap()
            .iter()
            .map(|value| value["ok"].clone())
            .collect::<Vec<_>>(),
        vec![json!(true), json!(false), json!(true)],
        "completed calls: {:?}", result.completed_tool_calls
    );
    assert_eq!(calls.load(Ordering::SeqCst), 3);
    state.cua_repl.shutdown();
    state.release_agent_run(&conversation.id);
    drop(host);
    drop(engine);
    drop(boundary);
    }).await;
    state.platform_plugin_authority_v2.deactivate().await;
    drop(state);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn pinned_execution_capture_preserves_typed_media() {
    let state = super::super::tests::test_state("pinned-media-events");
    let conversation_id = "pinned-media-conversation";
    super::super::tests::seed_plan_conversation(&state, conversation_id);
    let count = state.session_store.timeline_count(conversation_id).unwrap();
    struct MediaHost(Arc<LocalRuntimeState>);
    #[async_trait]
    impl ToolHost for MediaHost {
        fn list_tools(&self) -> Vec<String> {
            vec!["computer_get_app_state".into()]
        }
        async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
            Ok("text-only fallback".into())
        }
        async fn call_with_content(
            &self,
            _: &str,
            _: &str,
        ) -> CoreResult<agistack_core::ports::ToolResult> {
            tool_result_events_v2::append(
                &self.0,
                "pinned-media-conversation",
                json!({"id":"private-media","type":"mcp_app_result","data":{"artifact_id":"image"}}),
            );
            Ok(agistack_core::ports::ToolResult {
                control_outcome: None,
                control_generation: None,
                permission_required: None,
                output_json: "owned observation".into(),
                media: vec![agistack_core::agent::types::MediaAttachment {
                    artifact_path: "/owned/image.png".into(),
                    mime_type: "image/png".into(),
                }],
            })
        }
    }
    let context = agistack_core::agent::tool_policy::ToolPolicyContext {
        session_id: "engine-session",
        round: 7,
        tool: "computer_get_app_state",
    };
    let (result, events) = capture_content(&context, &MediaHost(state.clone()), "{}").await;
    let result = result.unwrap();
    assert_eq!(result.output_json, "owned observation");
    assert_eq!(result.media.len(), 1);
    assert_eq!(events.len(), 1);
    assert_eq!(
        state.session_store.timeline_count(conversation_id).unwrap(),
        count
    );
    tool_result_events_v2::publish(events);
    assert_eq!(
        state.session_store.timeline_count(conversation_id).unwrap(),
        count + 1
    );
}

#[tokio::test]
async fn prepared_request_replays_exact_body_after_store_reopen_without_generation() {
    let path = std::env::temp_dir().join(format!("memstack-request-log-{}.sqlite", Uuid::new_v4()));
    let store = session_store::DesktopSessionStore::open(&path).unwrap();
    let recorder = NativeModelRequestLogV2 {
        store: store.clone(),
        conversation_id: "request-conversation".into(),
        message_id: "request-message".into(),
        operation_id: "request-operation".into(),
        generation_digest: "generation-a".into(),
        contributors: json!([{"entry_id":"source-a","module_ref":"builtin://source-a","events":["agent.before_request"]}]),
    };
    let body = json!({"model": "model-a", "messages": [{"role":"user", "content":"already transformed input"}], "stream":true});
    let id = recorder
        .prepare_request("openai.chat_completions", body.clone())
        .await
        .unwrap();
    recorder
        .settle_request(&id, ModelRequestStatus::Completed)
        .await
        .unwrap();
    let cancelled = recorder
        .prepare_request("openai.chat_completions", body.clone())
        .await
        .unwrap();
    recorder.cancel_request(&cancelled);
    drop(recorder);
    drop(store);
    let reopened = session_store::DesktopSessionStore::open(&path).unwrap();
    let replay =
        replay_prepared_model_request(&reopened, "request-conversation", "request-message", &id)
            .unwrap()
            .unwrap();
    assert_eq!(
        replay,
        json!({"protocol":"openai.chat_completions","body":body})
    );
    assert!(replay_prepared_model_request(
        &reopened,
        "another-conversation",
        "request-message",
        &id
    )
    .unwrap()
    .is_none());
    assert!(replay_prepared_model_request(
        &reopened,
        "request-conversation",
        "another-message",
        &id
    )
    .unwrap()
    .is_none());
    let events = reopened.timeline("request-conversation", 10).unwrap();
    assert_eq!(events.len(), 4);
    assert_eq!(events[0]["data"]["contributors"][0]["entry_id"], "source-a");
    assert_eq!(events[3]["data"]["request"]["status"], "cancelled");
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn request_snapshots_do_not_become_next_turn_conversation_history() {
    let state = super::super::tests::test_state("request-log-test");
    super::super::tests::seed_plan_conversation(&state, "request-history");
    let recorder = NativeModelRequestLogV2 {
        store: state.session_store.clone(),
        conversation_id: "request-history".into(),
        message_id: "previous-message".into(),
        operation_id: "previous-operation".into(),
        generation_digest: "old-generation".into(),
        contributors: json!([]),
    };
    recorder
        .prepare_request(
            "openai.chat_completions",
            json!({"messages": [{"content":"PRIVATE_MODEL_PROMPT"}]}),
        )
        .await
        .unwrap();
    let checkpoint = state
        .conversation_turn_checkpoint(
            "request-history",
            "local-project",
            "next-message",
            "next goal",
        )
        .unwrap();
    assert!(checkpoint.transcript.is_empty());
}
