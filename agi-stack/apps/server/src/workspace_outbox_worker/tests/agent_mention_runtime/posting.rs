use super::*;

#[tokio::test]
async fn workspace_outbox_worker_posts_agent_response_when_runtime_result_ready() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let mut item = outbox("job-mention-response", WORKSPACE_AGENT_MENTION_EVENT);
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
        "final_content": "Done from runtime",
        "response_mentions": ["agent-reviewer"]
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
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
    let item = outbox_store.get("job-mention-response");
    assert_eq!(item.status, "completed");
    assert!(item.processed_at.is_some());
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    let message = &messages[0];
    assert_eq!(message.workspace_id, "workspace-test");
    assert_eq!(message.sender_id, "agent-builder");
    assert_eq!(message.sender_type, "agent");
    assert_eq!(message.content, "Done from runtime");
    assert_eq!(message.mentions_json, vec!["agent-reviewer"]);
    assert_eq!(message.parent_message_id.as_deref(), Some("message-1"));
    assert_eq!(
        message
            .metadata_json
            .get("sender_name")
            .and_then(Value::as_str),
        Some("Builder")
    );
    let events = dispatch_store.blackboard_outbox();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, WORKSPACE_MESSAGE_CREATED_EVENT);
    assert_eq!(
        events[0].payload_json["message"]["content"],
        "Done from runtime"
    );
    assert_eq!(events[0].payload_json["message"]["sender_type"], "agent");
    assert_eq!(
        events[0].metadata_json["runtime_bridge"],
        "p3_workspace_mention"
    );
}

#[tokio::test]
async fn workspace_outbox_worker_posts_agent_error_when_runtime_error_ready() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    let mut item = outbox("job-mention-error", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_display_name": "Builder",
        "conversation_id": "conversation-mention",
        "message_id": "message-1",
        "runtime_error_detail": "model unavailable"
    });
    outbox_store.insert(item);
    let handlers = workspace_plan_outbox_handlers(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
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
    let item = outbox_store.get("job-mention-error");
    assert_eq!(item.status, "completed");
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    let message = &messages[0];
    assert_eq!(
        message.content,
        "[Error] Builder could not process your request: model unavailable"
    );
    assert_eq!(message.sender_id, "agent-builder");
    assert_eq!(message.parent_message_id.as_deref(), Some("message-1"));
    let events = dispatch_store.blackboard_outbox();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].payload_json["message"]["content"],
        "[Error] Builder could not process your request: model unavailable"
    );
}
