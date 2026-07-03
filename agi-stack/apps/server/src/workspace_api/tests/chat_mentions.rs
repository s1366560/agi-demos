use super::*;

#[tokio::test]
async fn dev_service_roundtrips_workspace_chat_messages() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = service
        .create_workspace(
            "user-1",
            "tenant-1",
            "project-1",
            WorkspaceCreatePayload {
                name: "Chat Workspace".to_string(),
                description: None,
                metadata: json!({}),
                use_case: Some("programming".to_string()),
                collaboration_mode: Some("multi_agent_shared".to_string()),
                autonomy_profile: None,
                sandbox_code_root: None,
            },
        )
        .await
        .unwrap();
    let first = service
        .send_message(
            "user-1",
            "Alice",
            "tenant-1",
            "project-1",
            &workspace.id,
            SendMessagePayload {
                content: "hello".to_string(),
                sender_type: "human".to_string(),
                parent_message_id: None,
                mentions: vec![" user-1 ".to_string(), "user-1".to_string()],
            },
        )
        .await
        .unwrap();
    assert_eq!(first.mentions, vec!["user-1"]);
    assert_eq!(first.metadata["sender_name"], "Alice");
    let second = service
        .send_message(
            "user-1",
            "Alice",
            "tenant-1",
            "project-1",
            &workspace.id,
            SendMessagePayload {
                content: "broadcast".to_string(),
                sender_type: "human".to_string(),
                parent_message_id: Some(first.id.clone()),
                mentions: vec!["all".to_string()],
            },
        )
        .await
        .unwrap();
    assert!(second.mentions.is_empty());

    let listed = service
        .list_messages(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            MessageListQuery::default(),
        )
        .await
        .unwrap();
    assert_eq!(listed.items.len(), 2);
    assert_eq!(listed.items[0].id, first.id);
    assert_eq!(listed.items[1].id, second.id);

    let before_second = service
        .list_messages(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            MessageListQuery {
                limit: None,
                before: Some(second.id.clone()),
            },
        )
        .await
        .unwrap();
    assert_eq!(before_second.items.len(), 1);
    assert_eq!(before_second.items[0].id, first.id);

    let mentions = service
        .list_mentions(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            "user-1",
            MessageMentionQuery::default(),
        )
        .await
        .unwrap();
    assert_eq!(mentions.items.len(), 1);
    assert_eq!(mentions.items[0].id, first.id);

    let invalid_mention = service
        .send_message(
            "user-1",
            "Alice",
            "tenant-1",
            "project-1",
            &workspace.id,
            SendMessagePayload {
                content: "bad".to_string(),
                sender_type: "human".to_string(),
                parent_message_id: None,
                mentions: vec!["missing-user".to_string()],
            },
        )
        .await
        .unwrap_err();
    assert_eq!(invalid_mention.status, StatusCode::BAD_REQUEST);
    assert_eq!(invalid_mention.detail, "Invalid workspace chat request");

    let invalid_sender = service
        .send_message(
            "user-1",
            "Alice",
            "tenant-1",
            "project-1",
            &workspace.id,
            SendMessagePayload {
                content: "bad".to_string(),
                sender_type: "agent".to_string(),
                parent_message_id: None,
                mentions: Vec::new(),
            },
        )
        .await
        .unwrap_err();
    assert_eq!(invalid_sender.status, StatusCode::BAD_REQUEST);
    assert_eq!(invalid_sender.detail, "Invalid workspace chat request");

    let state = service.state.lock().expect("workspace dev state");
    let chat_events = state
        .outbox
        .iter()
        .filter(|event| event.event_type == "workspace_message_created")
        .count();
    assert_eq!(chat_events, 2);
}

#[tokio::test]
async fn dev_service_enqueues_agent_mention_runtime_admissions() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = service
        .create_workspace(
            "user-1",
            "tenant-1",
            "project-1",
            WorkspaceCreatePayload {
                name: "Mention Workspace".to_string(),
                description: None,
                metadata: json!({}),
                use_case: Some("programming".to_string()),
                collaboration_mode: Some("multi_agent_shared".to_string()),
                autonomy_profile: None,
                sandbox_code_root: None,
            },
        )
        .await
        .unwrap();
    {
        let mut state = service.state.lock().expect("workspace dev state");
        state.workspace_agents.push(WorkspaceAgentRecord {
            id: "wa-1".to_string(),
            workspace_id: workspace.id.clone(),
            agent_id: "agent-1".to_string(),
            display_name: Some("Builder".to_string()),
        });
        state.workspace_agents.push(WorkspaceAgentRecord {
            id: "wa-2".to_string(),
            workspace_id: workspace.id.clone(),
            agent_id: "agent-2".to_string(),
            display_name: None,
        });
    }

    let message = service
        .send_message(
            "user-1",
            "Alice",
            "tenant-1",
            "project-1",
            &workspace.id,
            SendMessagePayload {
                content: "please help".to_string(),
                sender_type: "human".to_string(),
                parent_message_id: None,
                mentions: vec![
                    "user-1".to_string(),
                    "agent-1".to_string(),
                    "agent-2".to_string(),
                ],
            },
        )
        .await
        .unwrap();
    assert_eq!(message.mentions, vec!["user-1", "agent-1", "agent-2"]);

    let state = service.state.lock().expect("workspace dev state");
    let mention_jobs: Vec<_> = state
        .plan_outbox
        .iter()
        .filter(|item| item.event_type == WORKSPACE_AGENT_MENTION_EVENT)
        .collect();
    assert_eq!(mention_jobs.len(), 2);
    assert!(mention_jobs
        .iter()
        .all(|item| { item.plan_id.is_none() && item.status == WORKSPACE_AGENT_MENTION_STATUS }));

    let first = mention_jobs[0];
    assert_eq!(first.payload_json["message_id"], message.id);
    assert_eq!(first.payload_json["sender_user_id"], "user-1");
    assert_eq!(first.payload_json["sender_name"], "Alice");
    assert_eq!(first.payload_json["target_agent_id"], "agent-1");
    assert_eq!(first.payload_json["target_workspace_agent_id"], "wa-1");
    assert_eq!(first.payload_json["agent_name"], "Builder");
    assert_eq!(
        first.payload_json["conversation_id"],
        workspace_conversation_id(&workspace.id, "agent-1", None)
    );
    assert_eq!(
        first.payload_json["user_prompt"],
        "[Workspace Chat] Alice mentioned you:\n\nplease help"
    );
    assert_eq!(
        first.metadata_json["runtime_bridge"],
        "p3_workspace_mention"
    );
    assert_eq!(first.metadata_json["target_agent_id"], "agent-1");

    let second = mention_jobs[1];
    assert_eq!(second.payload_json["target_agent_id"], "agent-2");
    assert_eq!(second.payload_json["agent_name"], "agent-2");
}

#[test]
fn workspace_conversation_id_matches_python_uuid5_contract() {
    assert_eq!(
        workspace_conversation_id("ws-mention", "agent-1", None),
        "ef99c6b6-cccc-5451-aecd-4fd3540b79f8"
    );
    assert_eq!(
        workspace_conversation_id("ws-mention", "agent-1", Some("objective:root-1")),
        "fff68776-271e-5a89-9a5b-def41746ef56"
    );
}
