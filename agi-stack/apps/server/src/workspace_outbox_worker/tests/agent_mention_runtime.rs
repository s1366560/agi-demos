use super::*;

#[tokio::test]
async fn workspace_outbox_worker_binds_workspace_agent_mention_and_parks_runtime() {
    let outbox_store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut item = outbox("job-mention", WORKSPACE_AGENT_MENTION_EVENT);
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
        "source": "workspace_chat_mention",
        "workspace_llm_stage": "chat_mention"
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
            parked: 1,
            ..Default::default()
        }
    );
    let item = outbox_store.get("job-mention");
    assert_eq!(item.status, WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS);
    assert!(item.processed_at.is_none());
    assert!(item.lease_owner.is_none());
    assert!(item.lease_expires_at.is_none());
    assert_eq!(item.attempt_count, 1);
    assert_eq!(
        item.metadata_json
            .get("runtime_binding")
            .and_then(Value::as_str),
        Some("workspace_agent_mention_conversation")
    );
    assert_eq!(
        item.metadata_json
            .get("conversation_id")
            .and_then(Value::as_str),
        Some("conversation-mention")
    );

    let conversation = dispatch_store.conversation("conversation-mention");
    assert_eq!(conversation.project_id, "project-test");
    assert_eq!(conversation.tenant_id, "tenant-test");
    assert_eq!(conversation.user_id, "user-sender");
    assert_eq!(conversation.title, "Workspace Chat - Builder");
    assert_eq!(
        conversation
            .agent_config_json
            .get("selected_agent_id")
            .and_then(Value::as_str),
        Some("agent-builder")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("workspace_id")
            .and_then(Value::as_str),
        Some("workspace-test")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("agent_id")
            .and_then(Value::as_str),
        Some("agent-builder")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("source")
            .and_then(Value::as_str),
        Some("workspace_chat_mention")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("workspace_llm_stage")
            .and_then(Value::as_str),
        Some("chat_mention")
    );
    assert_eq!(dispatch_store.conversation_count(), 1);
}

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
    assert_eq!(item.metadata_json["runtime_writer"], "llm_port_single_turn");
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
    let events = dispatch_store.blackboard_outbox();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, WORKSPACE_MESSAGE_CREATED_EVENT);
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

#[tokio::test]
async fn workspace_agent_mention_handler_patches_existing_conversation_linkage() {
    let dispatch_store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    dispatch_store
        .ensure_workspace_agent_conversation(
            "conversation-mention",
            "project-test",
            "tenant-test",
            "user-original",
            "Workspace Chat - Old Agent",
            &json!({ "selected_agent_id": "agent-old" }),
            &json!({
                "workspace_id": "workspace-test",
                "agent_id": "agent-old",
                "created_at": "2026-01-02T03:04:05Z"
            }),
            "workspace-test",
            None,
            Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        )
        .await
        .unwrap();
    let handler = WorkspaceAgentMentionBindingHandler::new(
        Arc::clone(&dispatch_store) as Arc<dyn WorkspacePlanDispatchStore>
    );
    let mut item = outbox("job-mention", WORKSPACE_AGENT_MENTION_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "sender_user_id": "user-sender",
        "target_agent_id": "agent-builder",
        "agent_display_name": "Builder",
        "conversation_id": "conversation-mention",
        "linked_workspace_task_id": "root-task",
        "source": "workspace_leader_mention",
        "workspace_llm_stage": "leader_mention"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert!(matches!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Park { ref status, .. }
            if status == WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS
    ));
    let conversation = dispatch_store.conversation("conversation-mention");
    assert_eq!(conversation.title, "Workspace Chat - Old Agent");
    assert_eq!(
        conversation
            .agent_config_json
            .get("selected_agent_id")
            .and_then(Value::as_str),
        Some("agent-builder")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("agent_id")
            .and_then(Value::as_str),
        Some("agent-builder")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("workspace_task_id")
            .and_then(Value::as_str),
        Some("root-task")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("linked_workspace_task_id")
            .and_then(Value::as_str),
        Some("root-task")
    );
    assert_eq!(
        conversation
            .metadata_json
            .get("source")
            .and_then(Value::as_str),
        Some("workspace_leader_mention")
    );
    assert_eq!(
        conversation.linked_workspace_task_id.as_deref(),
        Some("root-task")
    );
    assert_eq!(dispatch_store.conversation_count(), 1);
}
