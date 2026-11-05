use super::*;
use agistack_adapters_mem::InMemoryEventStream;

#[test]
fn unbound_filter_is_explicit_and_cannot_combine_with_workspace_scope() {
    let request: ConversationListRequest =
        serde_urlencoded::from_str("project_id=project&unbound_only=true&limit=1&offset=1")
            .unwrap();
    assert!(request.validated().unwrap().unbound_only);
    let default: ConversationListRequest =
        serde_urlencoded::from_str("project_id=project").unwrap();
    assert!(!default.validated().unwrap().unbound_only);
    let conflict: ConversationListRequest =
        serde_urlencoded::from_str("project_id=project&workspace_id=workspace&unbound_only=true")
            .unwrap();
    assert_eq!(
        conflict.validated().unwrap_err().status,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert!(serde_urlencoded::from_str::<ConversationListRequest>(
        "project_id=project&unbound_only=not-a-boolean",
    )
    .is_err());
}

#[test]
fn effective_workspace_binding_uses_typed_fields_then_legacy_protocol_segments() {
    use agistack_adapters_postgres::effective_conversation_workspace_id as workspace;
    assert_eq!(
        workspace(
            "workspace-worker:legacy:task:agent",
            None,
            Some(&json!({"workspace_id":7}))
        ),
        Some("legacy")
    );
    assert_eq!(
        workspace(
            "workspace-chat:legacy",
            Some(" direct "),
            Some(&json!({"workspace_id":"meta"}))
        ),
        Some("direct")
    );
    assert_eq!(
        workspace(
            "workspace-worker:legacy:task",
            Some("  "),
            Some(&json!({"workspace_id":" meta "}))
        ),
        Some("meta")
    );
    assert_eq!(workspace("workspace-worker:  :task", None, None), None);
    assert_eq!(
        workspace("ordinary:other", None, Some(&json!({"workspace_id":false}))),
        None
    );
}

#[tokio::test]
async fn unbound_conversation_list_filters_before_pagination_and_rejects_bound_filter() {
    let api = DevAgentConversationService::new(Arc::new(InMemoryEventStream::new()));
    for (id, workspace_id) in [
        ("bound", Some("workspace")),
        ("free-a", None),
        ("free-b", None),
    ] {
        let mut conversation = api
            .create_conversation(
                "dev-user",
                CreateConversationRequest {
                    project_id: "dev-project".into(),
                    title: Some(id.into()),
                    agent_config: None,
                },
            )
            .await
            .unwrap();
        conversation.id = id.into();
        conversation.workspace_id = workspace_id.map(str::to_owned);
        conversation.created_at = format!(
            "2026-10-29T00:00:0{}Z",
            if workspace_id.is_some() {
                9
            } else if id == "free-a" {
                2
            } else {
                1
            }
        );
        api.conversations
            .lock()
            .unwrap()
            .retain(|_, row| row.title != id);
        api.conversations
            .lock()
            .unwrap()
            .insert(id.into(), conversation);
    }
    let request = |offset| {
        serde_json::from_value(json!({"project_id":"dev-project","status":"active","limit":1,"offset":offset,"unbound_only":true})).unwrap()
    };
    let first = api
        .list_conversations("dev-user", request(0))
        .await
        .unwrap();
    assert_eq!(first.total, 2);
    assert_eq!(first.items[0].id, "free-a");
    assert!(first.items[0].workspace_id.is_none());
    assert!(first.has_more);
    assert_eq!(first.next_offset, Some(1));
    let second = api
        .list_conversations("dev-user", request(1))
        .await
        .unwrap();
    assert_eq!(second.total, 2);
    assert_eq!(second.items[0].id, "free-b");
    assert!(!second.has_more);
    let conflict = serde_json::from_value(
        json!({"project_id":"dev-project","workspace_id":"workspace","unbound_only":true}),
    )
    .unwrap();
    assert_eq!(
        api.list_conversations("dev-user", conflict)
            .await
            .unwrap_err()
            .status,
        StatusCode::UNPROCESSABLE_ENTITY
    );
}
