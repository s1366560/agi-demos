use super::super::*;

#[allow(clippy::too_many_arguments)]
pub(super) async fn ensure_worker_launch_conversation(
    store: &FakeWorkspacePlanDispatchStore,
    conversation_id: &str,
    project_id: &str,
    tenant_id: &str,
    user_id: &str,
    title: &str,
    agent_config_json: &Value,
    metadata_json: &Value,
    participant_agents_json: &[String],
    focused_agent_id: &str,
    workspace_id: &str,
    linked_workspace_task_id: &str,
    now: DateTime<Utc>,
) -> CoreResult<()> {
    let mut conversations = store.conversations.lock().unwrap();
    if let Some(existing) = conversations.get(conversation_id) {
        if existing.workspace_id != workspace_id
            || existing.linked_workspace_task_id.as_deref() != Some(linked_workspace_task_id)
        {
            return Err(CoreError::Storage(format!(
                "worker launch conversation {conversation_id} is linked to another workspace task"
            )));
        }
    }
    conversations.insert(
        conversation_id.to_string(),
        FakeWorkerConversationRecord {
            id: conversation_id.to_string(),
            project_id: project_id.to_string(),
            tenant_id: tenant_id.to_string(),
            user_id: user_id.to_string(),
            title: title.to_string(),
            agent_config_json: agent_config_json.clone(),
            metadata_json: metadata_json.clone(),
            participant_agents_json: participant_agents_json.to_vec(),
            focused_agent_id: focused_agent_id.to_string(),
            workspace_id: workspace_id.to_string(),
            linked_workspace_task_id: Some(linked_workspace_task_id.to_string()),
            updated_at: now,
        },
    );
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub(super) async fn ensure_workspace_agent_conversation(
    store: &FakeWorkspacePlanDispatchStore,
    conversation_id: &str,
    project_id: &str,
    tenant_id: &str,
    user_id: &str,
    title: &str,
    agent_config_json: &Value,
    metadata_json: &Value,
    workspace_id: &str,
    linked_workspace_task_id: Option<&str>,
    now: DateTime<Utc>,
) -> CoreResult<()> {
    let mut conversations = store.conversations.lock().unwrap();
    if let Some(existing) = conversations.get_mut(conversation_id) {
        if existing.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace agent conversation {conversation_id} is linked to another workspace"
            )));
        }
        existing.agent_config_json = agent_config_json.clone();
        existing.metadata_json = metadata_json.clone();
        if let Some(task_id) = linked_workspace_task_id {
            existing.linked_workspace_task_id = Some(task_id.to_string());
        }
        existing.updated_at = now;
        return Ok(());
    }
    conversations.insert(
        conversation_id.to_string(),
        FakeWorkerConversationRecord {
            id: conversation_id.to_string(),
            project_id: project_id.to_string(),
            tenant_id: tenant_id.to_string(),
            user_id: user_id.to_string(),
            title: title.to_string(),
            agent_config_json: agent_config_json.clone(),
            metadata_json: metadata_json.clone(),
            participant_agents_json: Vec::new(),
            focused_agent_id: String::new(),
            workspace_id: workspace_id.to_string(),
            linked_workspace_task_id: linked_workspace_task_id.map(ToOwned::to_owned),
            updated_at: now,
        },
    );
    Ok(())
}

pub(super) async fn list_workspace_member_user_ids(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_id: &str,
) -> CoreResult<Vec<String>> {
    let mut members = store
        .members
        .lock()
        .unwrap()
        .get(workspace_id)
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .collect::<Vec<_>>();
    members.sort();
    Ok(members)
}

pub(super) async fn list_active_workspace_agents(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_id: &str,
) -> CoreResult<Vec<WorkspaceAgentRecord>> {
    Ok(store
        .agents
        .lock()
        .unwrap()
        .get(workspace_id)
        .cloned()
        .unwrap_or_default())
}

pub(super) async fn create_workspace_message(
    store: &FakeWorkspacePlanDispatchStore,
    message: WorkspaceMessageRecord,
) -> CoreResult<WorkspaceMessageRecord> {
    store
        .messages
        .lock()
        .unwrap()
        .insert(message.id.clone(), message.clone());
    Ok(message)
}

pub(super) async fn enqueue_blackboard_outbox(
    store: &FakeWorkspacePlanDispatchStore,
    outbox: BlackboardOutboxRecord,
) -> CoreResult<()> {
    store.blackboard_outbox.lock().unwrap().push(outbox);
    Ok(())
}

pub(super) async fn create_plan_event(
    store: &FakeWorkspacePlanDispatchStore,
    event: WorkspacePlanEventRecord,
) -> CoreResult<WorkspacePlanEventRecord> {
    store.plan_events.lock().unwrap().push(event.clone());
    Ok(event)
}

pub(super) async fn enqueue_plan_outbox(
    store: &FakeWorkspacePlanDispatchStore,
    item: WorkspacePlanOutboxRecord,
) -> CoreResult<WorkspacePlanOutboxRecord> {
    store.outbox.lock().unwrap().push(item.clone());
    Ok(item)
}
