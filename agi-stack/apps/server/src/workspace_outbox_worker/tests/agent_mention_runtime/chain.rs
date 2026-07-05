use super::*;

#[tokio::test]
async fn workspace_outbox_worker_enqueues_agent_chain_mention_from_terminal_response() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    dispatch_store.insert_agent("workspace-test", "agent-reviewer", Some("Reviewer"));
    let mut item = outbox("job-mention-chain", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-builder",
        "conversation_scope": "objective:root-1",
        "message_id": "message-1",
        "final_content": "Reviewer should inspect this.",
        "response_mentions": ["agent-reviewer", "missing-agent", "agent-reviewer"],
        "chain_depth": 1
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
    let messages = dispatch_store.messages();
    assert_eq!(messages.len(), 1);
    assert_eq!(
        messages[0].mentions_json,
        vec!["agent-reviewer", "missing-agent", "agent-reviewer"]
    );
    let chained = dispatch_store.outbox();
    assert_eq!(chained.len(), 1);
    let next = &chained[0];
    assert_eq!(next.event_type, WORKSPACE_AGENT_MENTION_EVENT);
    assert_eq!(next.status, WORKSPACE_AGENT_MENTION_PENDING_RUNTIME_STATUS);
    assert_eq!(next.payload_json["target_agent_id"], "agent-reviewer");
    assert_eq!(
        next.payload_json["target_workspace_agent_id"],
        "workspace-agent-agent-reviewer"
    );
    assert_eq!(next.payload_json["sender_user_id"], "user-sender");
    assert_eq!(next.payload_json["sender_name"], "Builder");
    assert_eq!(next.payload_json["source_agent_id"], "agent-builder");
    assert_eq!(
        next.payload_json["source"],
        WORKSPACE_AGENT_CHAIN_MENTION_SOURCE
    );
    assert_eq!(
        next.payload_json["workspace_llm_stage"],
        WORKSPACE_AGENT_CHAIN_MENTION_STAGE
    );
    assert_eq!(next.payload_json["chain_depth"], 2);
    assert_eq!(
        next.payload_json["user_prompt"],
        "[Workspace Chat] Builder mentioned you:\n\nReviewer should inspect this."
    );
    assert_eq!(
        next.payload_json["conversation_id"],
        workspace_agent_conversation_id(
            "workspace-test",
            "agent-reviewer",
            Some("objective:root-1")
        )
    );
    assert_eq!(next.metadata_json["chain_depth"], 2);
    assert_eq!(next.metadata_json["source_agent_id"], "agent-builder");
}

#[tokio::test]
async fn workspace_outbox_worker_does_not_enqueue_agent_chain_past_depth_limit() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store.insert_member("workspace-test", "user-sender");
    dispatch_store.insert_agent("workspace-test", "agent-reviewer", Some("Reviewer"));
    let mut item = outbox("job-mention-chain-limit", WORKSPACE_AGENT_MENTION_EVENT);
    item.plan_id = None;
    item.status = WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS.to_string();
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_name": "Builder",
        "conversation_id": "conversation-builder",
        "message_id": "message-1",
        "final_content": "Reviewer should inspect this.",
        "response_mentions": ["agent-reviewer"],
        "chain_depth": MAX_WORKSPACE_AGENT_MENTION_CHAIN_DEPTH
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
    assert_eq!(dispatch_store.messages().len(), 1);
    assert!(dispatch_store.outbox().is_empty());
}
