//! Recorded requests use ordinary conversation replay authorization, without plugins.

use agistack_core::model_request::ModelRequestReplay;

use super::*;

#[derive(Deserialize)]
pub(super) struct RequestQuery {
    project_id: String,
}

pub(super) async fn get(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((conversation_id, message_id, attempt_id)): Path<(String, String, String)>,
    Query(query): Query<RequestQuery>,
) -> Result<Json<ModelRequestReplay>, AgentConversationsApiError> {
    ensure_project_access(&app, &identity, &query.project_id).await?;
    read(
        &app.agent_conversations,
        app.agent_event_writer.as_ref(),
        &identity.user_id,
        &conversation_id,
        &query.project_id,
        &message_id,
        &attempt_id,
    )
    .await
    .map(Json)
}

async fn read(
    conversations: &SharedAgentConversations,
    events: Option<&PgAgentExecutionEventRepository>,
    user_id: &str,
    conversation_id: &str,
    project_id: &str,
    message_id: &str,
    attempt_id: &str,
) -> Result<ModelRequestReplay, AgentConversationsApiError> {
    match conversations
        .authorize_event_subscription(user_id, conversation_id)
        .await?
    {
        ConversationSocketAccess::Allowed => {}
        ConversationSocketAccess::Denied => {
            return Err(AgentConversationsApiError::forbidden(
                "Access denied to this conversation",
            ))
        }
        ConversationSocketAccess::NotFound => {
            return Err(AgentConversationsApiError::not_found(
                "Conversation not found",
            ))
        }
    }
    // Reuse the exact history authority, including Workspace Core task membership
    // and project/conversation matching, before touching private request records.
    conversations
        .authorize_model_request_replay(user_id, conversation_id, project_id)
        .await?;
    let request = if let Some(events) = events {
        events
            .replay_prepared_model_request(conversation_id, Some(message_id), attempt_id)
            .await
            .map_err(AgentConversationsApiError::internal)?
    } else {
        None
    };
    Ok(ModelRequestReplay::from_stored_request(
        attempt_id.into(),
        request,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_adapters_mem::InMemoryEventStream;

    #[tokio::test]
    async fn request_replay_preserves_history_authority_and_marks_legacy_missing() {
        let conversations: SharedAgentConversations = Arc::new(DevAgentConversationService::new(
            Arc::new(InMemoryEventStream::new()),
        ));
        let conversation = conversations
            .create_conversation(
                "owner",
                CreateConversationRequest {
                    project_id: "project".into(),
                    title: Some("private".into()),
                    agent_config: None,
                },
            )
            .await
            .unwrap();
        let own = read(
            &conversations,
            None,
            "owner",
            &conversation.id,
            "project",
            "message",
            "attempt",
        )
        .await
        .unwrap();
        assert_eq!(own.status, "snapshot_missing");
        assert_eq!(own.reason_code, Some("model_request_snapshot_missing"));
        assert!(read(
            &conversations,
            None,
            "other-user",
            &conversation.id,
            "project",
            "message",
            "attempt"
        )
        .await
        .is_err());
        assert!(read(
            &conversations,
            None,
            "owner",
            &conversation.id,
            "other-project",
            "message",
            "attempt"
        )
        .await
        .is_err());
    }
}
