use std::collections::{HashMap, HashSet};

use agistack_adapters_postgres::{
    ProjectMyWorkHitlAuthorityRecord, ProjectMyWorkWorkspaceAttemptRecord,
};

use super::*;

const RUNNING_ATTEMPT_STATUSES: &[&str] = &["pending", "running", "awaiting_leader_adjudication"];
const HIDDEN_ATTEMPT_STATUSES: &[&str] = &["accepted", "rejected", "cancelled"];
const INPUT_HITL_TYPES: &[&str] = &["clarification", "decision", "env_var", "a2ui_action"];

impl PgWorkspaceService {
    pub(super) async fn pg_list_project_my_work(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMyWorkResponse, WorkspaceApiError> {
        let allowed = self
            .repo
            .user_can_access_project_my_work(user_id, project_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if !allowed {
            return Err(WorkspaceApiError::forbidden());
        }

        let now = Utc::now();
        let (attempts, hitl_requests) = tokio::try_join!(
            self.repo
                .list_latest_project_my_work_attempts(project_id, user_id),
            self.repo
                .list_pending_project_my_work_hitl(project_id, user_id, now),
        )
        .map_err(WorkspaceApiError::internal)?;
        Ok(project_my_work_response(
            project_id,
            attempts,
            hitl_requests,
            now,
        ))
    }
}

impl DevWorkspaceService {
    pub(super) async fn dev_list_project_my_work(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMyWorkResponse, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let accessible_workspaces: HashMap<_, _> = state
            .workspaces
            .values()
            .filter(|workspace| workspace.project_id == project_id && !workspace.is_archived)
            .filter(|workspace| {
                state.workspace_members.iter().any(|membership| {
                    membership.workspace_id == workspace.id && membership.user_id == user_id
                })
            })
            .map(|workspace| (workspace.id.as_str(), workspace))
            .collect();
        if accessible_workspaces.is_empty() {
            return Err(WorkspaceApiError::forbidden());
        }

        let mut latest_by_task: HashMap<&str, &WorkspaceTaskSessionAttemptRecord> = HashMap::new();
        for attempt in state.task_attempts.values().filter(|attempt| {
            attempt.conversation_id.is_some()
                && accessible_workspaces.contains_key(attempt.workspace_id.as_str())
        }) {
            match latest_by_task.get(attempt.workspace_task_id.as_str()) {
                Some(current) if !attempt_is_newer(attempt, current) => {}
                _ => {
                    latest_by_task.insert(attempt.workspace_task_id.as_str(), attempt);
                }
            }
        }
        let attempts = latest_by_task
            .into_values()
            .filter_map(|attempt| {
                let task = state.tasks.get(&attempt.workspace_task_id)?;
                if task.workspace_id != attempt.workspace_id || task.archived_at.is_some() {
                    return None;
                }
                let workspace = accessible_workspaces.get(attempt.workspace_id.as_str())?;
                Some(ProjectMyWorkWorkspaceAttemptRecord {
                    authority_id: attempt.id.clone(),
                    conversation_id: attempt.conversation_id.clone()?,
                    workspace_id: attempt.workspace_id.clone(),
                    project_id: workspace.project_id.clone(),
                    title: task.title.clone(),
                    status: attempt.status.clone(),
                    attempt_number: attempt.attempt_number,
                    conversation_agent_config: None,
                    workspace_metadata: workspace.metadata_json.clone(),
                    created_at: attempt.created_at,
                    updated_at: attempt.updated_at,
                })
            })
            .collect();
        Ok(project_my_work_response(
            project_id,
            attempts,
            Vec::new(),
            Utc::now(),
        ))
    }
}

fn attempt_is_newer(
    candidate: &WorkspaceTaskSessionAttemptRecord,
    current: &WorkspaceTaskSessionAttemptRecord,
) -> bool {
    candidate.attempt_number > current.attempt_number
        || (candidate.attempt_number == current.attempt_number
            && (candidate.created_at > current.created_at
                || (candidate.created_at == current.created_at && candidate.id < current.id)))
}

pub(super) fn project_my_work_response(
    project_id: &str,
    attempts: Vec<ProjectMyWorkWorkspaceAttemptRecord>,
    hitl_requests: Vec<ProjectMyWorkHitlAuthorityRecord>,
    now: DateTime<Utc>,
) -> ProjectMyWorkResponse {
    let mut hitl_conversation_ids = HashSet::new();
    let mut items = Vec::with_capacity(attempts.len() + hitl_requests.len());
    for source in hitl_requests {
        if source.expires_at <= now {
            continue;
        }
        let conversation_id = source.conversation_id.clone();
        if let Some(item) = hitl_item(source) {
            hitl_conversation_ids.insert(conversation_id);
            items.push(item);
        }
    }
    items.extend(
        attempts
            .into_iter()
            .filter(|source| !hitl_conversation_ids.contains(&source.conversation_id))
            .filter_map(attempt_item),
    );
    items.sort_by(|left, right| {
        right
            .updated_at
            .cmp(&left.updated_at)
            .then_with(|| right.authority_id.cmp(&left.authority_id))
    });
    ProjectMyWorkResponse {
        project_id: project_id.to_string(),
        total: items.len(),
        items,
    }
}

fn attempt_item(source: ProjectMyWorkWorkspaceAttemptRecord) -> Option<ProjectWorkItem> {
    if HIDDEN_ATTEMPT_STATUSES.contains(&source.status.as_str()) {
        return None;
    }
    let (group, status, required_action) =
        if RUNNING_ATTEMPT_STATUSES.contains(&source.status.as_str()) {
            (
                MyWorkGroup::Running,
                MyWorkStatus::Running,
                MyWorkRequiredAction::Observe,
            )
        } else if source.status == "blocked" {
            (
                MyWorkGroup::NeedsInput,
                MyWorkStatus::Failed,
                MyWorkRequiredAction::InspectFailure,
            )
        } else {
            return None;
        };
    let updated_at = source.updated_at.unwrap_or(source.created_at);
    Some(ProjectWorkItem {
        id: format!("workspace_attempt:{}", source.authority_id),
        authority_kind: MyWorkAuthorityKind::WorkspaceAttempt,
        authority_id: source.authority_id,
        run_id: None,
        conversation_id: source.conversation_id,
        workspace_id: source.workspace_id,
        project_id: source.project_id,
        title: source.title,
        capability_mode: capability_mode(
            source.conversation_agent_config.as_ref(),
            Some(&source.workspace_metadata),
        ),
        group,
        status,
        required_action,
        revision: None,
        permission_profile: None,
        environment: None,
        error: None,
        attempt_number: Some(source.attempt_number),
        created_at: source.created_at,
        updated_at,
        last_heartbeat_at: None,
    })
}

fn hitl_item(source: ProjectMyWorkHitlAuthorityRecord) -> Option<ProjectWorkItem> {
    let trusted_type = trusted_hitl_type(&source);
    let (group, status, required_action) = if trusted_type == "permission" {
        (
            MyWorkGroup::NeedsApproval,
            MyWorkStatus::NeedsApproval,
            MyWorkRequiredAction::ReviewApproval,
        )
    } else if INPUT_HITL_TYPES.contains(&trusted_type) {
        (
            MyWorkGroup::NeedsInput,
            MyWorkStatus::NeedsInput,
            MyWorkRequiredAction::ProvideInput,
        )
    } else {
        return None;
    };
    Some(ProjectWorkItem {
        id: format!("hitl_request:{}", source.authority_id),
        authority_kind: MyWorkAuthorityKind::HitlRequest,
        authority_id: source.authority_id,
        run_id: None,
        conversation_id: source.conversation_id,
        workspace_id: source.workspace_id,
        project_id: source.project_id,
        title: source.title,
        capability_mode: capability_mode(
            source.conversation_agent_config.as_ref(),
            Some(&source.workspace_metadata),
        ),
        group,
        status,
        required_action,
        revision: None,
        permission_profile: None,
        environment: None,
        error: None,
        attempt_number: None,
        created_at: source.created_at,
        updated_at: source.created_at,
        last_heartbeat_at: None,
    })
}

fn capability_mode(
    values: Option<&Value>,
    fallback: Option<&Value>,
) -> Option<MyWorkCapabilityMode> {
    [values, fallback].into_iter().flatten().find_map(|value| {
        match value.get("capability_mode").and_then(Value::as_str) {
            Some("work") => Some(MyWorkCapabilityMode::Work),
            Some("code") => Some(MyWorkCapabilityMode::Code),
            _ => None,
        }
    })
}

fn trusted_hitl_type(source: &ProjectMyWorkHitlAuthorityRecord) -> &str {
    let metadata_type = source
        .request_metadata
        .as_ref()
        .and_then(|metadata| metadata.get("hitl_type"))
        .and_then(Value::as_str);
    match metadata_type {
        Some(value) if value == "permission" || INPUT_HITL_TYPES.contains(&value) => value,
        _ => source.request_type.as_str(),
    }
}
