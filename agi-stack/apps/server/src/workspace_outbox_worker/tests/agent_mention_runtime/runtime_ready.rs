use super::*;
use agistack_adapters_mem::InMemoryEventStream;
use agistack_core::ports::EventStream;

#[tokio::test]
async fn workspace_outbox_worker_writes_agent_mention_runtime_response_ready() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let runtime = Arc::new(FakeWorkspaceAgentMentionRuntime::ok("Runtime answer"));
    let mut item = outbox("job-mention-runtime", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = "pending_runtime".to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "sender_name": "Ada",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "user_prompt": "Please summarize this plan.",
        "source": "workspace_chat_mention",
        "workspace_llm_stage": "chat_mention"
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>,
        None,
        None,
        None,
        Some(Arc::clone(&runtime) as Arc<dyn WorkspaceAgentMentionRuntime>),
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let first = worker.run_once().await.unwrap();

    assert_eq!(
        first,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            parked: 1,
            ..Default::default()
        }
    );
    assert_eq!(runtime.prompts(), vec!["Please summarize this plan."]);
    let item = outbox_store.get("job-mention-runtime");
    assert_eq!(item.status, WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS);
    assert_eq!(item.payload_json["final_content"], "Runtime answer");
    assert_eq!(
        item.payload_json["runtime_token_chunks"],
        json!(["Runtime answer"])
    );
    assert_eq!(item.metadata_json["runtime_writer"], "llm_port_single_turn");
    assert_eq!(
        item.metadata_json["runtime_stream_delivery"],
        "final_content_chunks"
    );
    assert_eq!(item.metadata_json["runtime_token_chunk_count"], 1);
    assert_eq!(dispatch_store.messages().len(), 0);

    let second = worker.run_once().await.unwrap();

    assert_eq!(
        second,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let item = outbox_store.get("job-mention-runtime");
    assert_eq!(item.status, "completed");
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].content, "Runtime answer");
    assert_eq!(
        messages[0].metadata_json["runtime_stream_delivery"],
        "blackboard_token_chunks"
    );
    assert_eq!(messages[0].metadata_json["runtime_token_chunk_count"], 1);
    let events = dispatch_store.blackboard_outbox();
    assert_eq!(events.len(), 2);
    assert_eq!(
        events[0].event_type,
        WORKSPACE_AGENT_MENTION_TOKEN_CHUNK_EVENT
    );
    assert_eq!(events[0].payload_json["message_id"], messages[0].id);
    assert_eq!(events[0].payload_json["parent_message_id"], "message-1");
    assert_eq!(
        events[0].payload_json["conversation_id"],
        "conversation-mention"
    );
    assert_eq!(events[0].payload_json["chunk_index"], 0);
    assert_eq!(events[0].payload_json["chunk_count"], 1);
    assert_eq!(events[0].payload_json["content_delta"], "Runtime answer");
    assert_eq!(events[0].payload_json["is_final"], true);
    assert_eq!(
        events[0].metadata_json["runtime_stream_delivery"],
        "blackboard_token_chunks"
    );
    assert_eq!(
        events[0].correlation_id.as_deref(),
        Some(messages[0].id.as_str())
    );
    assert_eq!(events[1].event_type, WORKSPACE_MESSAGE_CREATED_EVENT);
}

#[tokio::test]
async fn workspace_outbox_worker_fans_out_runtime_chunks_to_event_stream() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let event_stream = Arc::new(InMemoryEventStream::new());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let mut item = outbox("job-mention-runtime-stream", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "final_content": "streamed answer",
        "runtime_token_chunks": ["streamed ", "answer"]
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers_with_runtime_state_and_streams(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>,
        None,
        None,
        None,
        None,
        Some(Arc::clone(&event_stream) as Arc<dyn EventStream>),
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    let entries = event_stream
        .read_after(
            &workspace_agent_mention_event_stream_topic("workspace-test"),
            "",
            10,
        )
        .await
        .unwrap();
    assert_eq!(entries.len(), 3);
    let first: Value = serde_json::from_str(&entries[0].payload).unwrap();
    assert_eq!(first["type"], WORKSPACE_AGENT_MENTION_TOKEN_CHUNK_EVENT);
    assert_eq!(first["workspace_id"], "workspace-test");
    assert_eq!(first["data"]["message_id"], messages[0].id.as_str());
    assert_eq!(first["data"]["chunk_index"], 0);
    assert_eq!(first["data"]["content_delta"], "streamed ");
    assert_eq!(first["data"]["is_final"], false);
    assert_eq!(first["correlation_id"], messages[0].id.as_str());
    let second: Value = serde_json::from_str(&entries[1].payload).unwrap();
    assert_eq!(second["type"], WORKSPACE_AGENT_MENTION_TOKEN_CHUNK_EVENT);
    assert_eq!(second["data"]["chunk_index"], 1);
    assert_eq!(second["data"]["content_delta"], "answer");
    assert_eq!(second["data"]["is_final"], true);
    let final_event: Value = serde_json::from_str(&entries[2].payload).unwrap();
    assert_eq!(final_event["type"], WORKSPACE_MESSAGE_CREATED_EVENT);
    assert_eq!(final_event["data"]["message"]["content"], "streamed answer");
    assert!(final_event["event_time_us"].as_i64().is_some());
}

#[tokio::test]
async fn workspace_outbox_worker_applies_backpressure_to_runtime_token_chunks() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let chunks: Vec<String> = (0..(MAX_WORKSPACE_AGENT_MENTION_STREAM_CHUNKS + 2))
        .map(|index| format!("chunk-{index}"))
        .collect();
    let mut item = outbox(
        "job-mention-runtime-backpressure",
        WORKSPACE_AGENT_MENTION_EVENT,
    );
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "final_content": "full answer survives chunk backpressure",
        "runtime_token_chunks": chunks
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>,
        None,
        None,
        None,
        None,
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    assert_eq!(
        messages[0].content,
        "full answer survives chunk backpressure"
    );
    assert_eq!(
        messages[0].metadata_json["runtime_token_chunk_count"],
        MAX_WORKSPACE_AGENT_MENTION_STREAM_CHUNKS
    );
    assert_eq!(
        messages[0].metadata_json["runtime_stream_backpressure"],
        "truncated"
    );
    assert_eq!(
        messages[0].metadata_json["runtime_token_chunk_original_count"],
        MAX_WORKSPACE_AGENT_MENTION_STREAM_CHUNKS + 2
    );

    let events = dispatch_store.blackboard_outbox();
    let token_events: Vec<_> = events
        .iter()
        .filter(|event| event.event_type == WORKSPACE_AGENT_MENTION_TOKEN_CHUNK_EVENT)
        .collect();
    assert_eq!(
        token_events.len(),
        MAX_WORKSPACE_AGENT_MENTION_STREAM_CHUNKS
    );
    let last = token_events
        .last()
        .expect("backpressure keeps bounded token events");
    assert_eq!(
        last.payload_json["chunk_index"],
        MAX_WORKSPACE_AGENT_MENTION_STREAM_CHUNKS - 1
    );
    assert_eq!(
        last.payload_json["chunk_count"],
        MAX_WORKSPACE_AGENT_MENTION_STREAM_CHUNKS
    );
    assert_eq!(last.payload_json["is_final"], false);
    assert_eq!(last.payload_json["is_backpressure_truncated"], true);
    assert_eq!(
        last.payload_json["runtime_stream_backpressure"],
        "truncated"
    );
    assert_eq!(
        last.metadata_json["runtime_token_chunk_max"],
        MAX_WORKSPACE_AGENT_MENTION_STREAM_CHUNKS
    );
    assert_eq!(
        last.metadata_json["runtime_token_char_max"],
        MAX_WORKSPACE_AGENT_MENTION_STREAM_CHARS
    );
    assert_eq!(
        events.last().expect("message event exists").event_type,
        WORKSPACE_MESSAGE_CREATED_EVENT
    );
}

#[tokio::test]
async fn workspace_outbox_worker_writes_agent_mention_runtime_error_ready() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let runtime = Arc::new(FakeWorkspaceAgentMentionRuntime::err(
        "provider unavailable",
    ));
    let mut item = outbox("job-mention-runtime-error", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = "pending_runtime".to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "source_message": {"content": "Please run this."}
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>,
        None,
        None,
        None,
        Some(runtime as Arc<dyn WorkspaceAgentMentionRuntime>),
    );
    let worker = worker(Arc::clone(&outbox_store), handlers);

    let first = worker.run_once().await.unwrap();

    assert_eq!(
        first,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            parked: 1,
            ..Default::default()
        }
    );
    let item = outbox_store.get("job-mention-runtime-error");
    assert_eq!(item.status, WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS);
    assert_eq!(
        item.payload_json["runtime_error_detail"],
        "llm error: provider unavailable"
    );

    let second = worker.run_once().await.unwrap();

    assert_eq!(
        second,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    assert_eq!(
        messages[0].content,
        "[Error] Builder could not process your request: llm error: provider unavailable"
    );
}
