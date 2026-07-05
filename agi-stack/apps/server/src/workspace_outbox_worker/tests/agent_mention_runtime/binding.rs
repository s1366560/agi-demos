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
