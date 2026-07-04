use super::chat_mentions::{
    resolve_structured_mentions, workspace_agent_mention_outbox_records,
    WorkspaceAgentMentionOutboxInput,
};
use super::*;

impl PgWorkspaceService {
    pub(super) async fn pg_send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        validate_non_empty(&body.content, "content")?;
        if body.sender_type != "human" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace chat request",
            ));
        }
        let member_ids = self
            .repo
            .list_workspace_member_user_ids(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let agents = self
            .repo
            .list_active_workspace_agents(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let agent_ids: Vec<_> = agents.iter().map(|agent| agent.agent_id.clone()).collect();
        let mentions = resolve_structured_mentions(&body.mentions, &member_ids, &agent_ids)?;
        let sender_name = self
            .repo
            .get_user_email(user_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .unwrap_or_else(|| sender_name.to_string());
        let now = Utc::now();
        let message = self
            .repo
            .create_message(WorkspaceMessageRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                sender_id: user_id.to_string(),
                sender_type: "human".to_string(),
                content: body.content,
                mentions_json: mentions,
                parent_message_id: body.parent_message_id,
                metadata_json: json!({ "sender_name": sender_name }),
                created_at: now,
            })
            .await
            .map_err(WorkspaceApiError::internal)?;
        let view = MessageView::from(message);
        self.enqueue_chat_event(
            tenant_id,
            project_id,
            workspace_id,
            "workspace_message_created",
            json!({ "message": &view }),
        )
        .await?;
        let mention_outbox =
            workspace_agent_mention_outbox_records(WorkspaceAgentMentionOutboxInput {
                tenant_id,
                project_id,
                workspace_id,
                sender_user_id: user_id,
                sender_name: &sender_name,
                message: &view,
                agents: &agents,
                now,
            });
        for outbox in mention_outbox {
            self.repo
                .enqueue_plan_outbox(outbox)
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        Ok(view)
    }

    pub(super) async fn pg_list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let messages = self
            .repo
            .list_messages(
                workspace_id,
                clamp_limit(query.limit, 50, 200),
                query.before.as_deref(),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(MessageListView {
            items: messages.into_iter().map(MessageView::from).collect(),
        })
    }

    pub(super) async fn pg_list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let messages = self
            .repo
            .list_messages_mentioning(workspace_id, target_id, clamp_limit(query.limit, 50, 200))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(MessageListView {
            items: messages.into_iter().map(MessageView::from).collect(),
        })
    }
}

impl DevWorkspaceService {
    pub(super) async fn dev_send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.content, "content")?;
        if body.sender_type != "human" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace chat request",
            ));
        }
        let mut state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let member_ids = vec![self.dev_user_id.clone()];
        let agents: Vec<_> = state
            .workspace_agents
            .iter()
            .filter(|agent| agent.workspace_id == workspace_id)
            .cloned()
            .collect();
        let agent_ids: Vec<_> = agents.iter().map(|agent| agent.agent_id.clone()).collect();
        let mentions = resolve_structured_mentions(&body.mentions, &member_ids, &agent_ids)?;
        let now = Utc::now();
        let message = WorkspaceMessageRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            sender_id: user_id.to_string(),
            sender_type: "human".to_string(),
            content: body.content,
            mentions_json: mentions,
            parent_message_id: body.parent_message_id,
            metadata_json: json!({ "sender_name": sender_name }),
            created_at: now,
        };
        state.messages.insert(message.id.clone(), message.clone());
        let view = MessageView::from(message);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "workspace_message_created".to_string(),
            payload_json: json!({ "message": &view }),
            metadata_json: json!({
                "tenant_id": tenant_id,
                "project_id": project_id,
                "surface_owner": "workspace-chat",
                "surface_boundary": "hosted",
                "authority_class": "non-authoritative",
                "signal_role": "sensing-capable"
            }),
            correlation_id: None,
        });
        state
            .plan_outbox
            .extend(workspace_agent_mention_outbox_records(
                WorkspaceAgentMentionOutboxInput {
                    tenant_id,
                    project_id,
                    workspace_id,
                    sender_user_id: user_id,
                    sender_name,
                    message: &view,
                    agents: &agents,
                    now,
                },
            ));
        Ok(view)
    }

    pub(super) async fn dev_list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let before = query
            .before
            .as_deref()
            .and_then(|id| state.messages.get(id))
            .map(|message| (message.created_at, message.id.clone()));
        let limit = clamp_limit(query.limit, 50, 200) as usize;
        let mut messages: Vec<_> = state
            .messages
            .values()
            .filter(|message| {
                message.workspace_id == workspace_id
                    && before
                        .as_ref()
                        .map(|(created_at, id)| {
                            message.created_at < *created_at
                                || (message.created_at == *created_at && message.id < *id)
                        })
                        .unwrap_or(true)
            })
            .cloned()
            .collect();
        messages.sort_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)));
        Ok(MessageListView {
            items: messages
                .into_iter()
                .take(limit)
                .map(MessageView::from)
                .collect(),
        })
    }

    pub(super) async fn dev_list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let limit = clamp_limit(query.limit, 50, 200) as usize;
        let mut messages: Vec<_> = state
            .messages
            .values()
            .filter(|message| {
                message.workspace_id == workspace_id
                    && message
                        .mentions_json
                        .iter()
                        .any(|mention| mention == target_id)
            })
            .cloned()
            .collect();
        messages.sort_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)));
        Ok(MessageListView {
            items: messages
                .into_iter()
                .take(limit)
                .map(MessageView::from)
                .collect(),
        })
    }
}
