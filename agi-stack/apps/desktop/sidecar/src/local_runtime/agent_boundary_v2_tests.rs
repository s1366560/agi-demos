use super::*;

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
