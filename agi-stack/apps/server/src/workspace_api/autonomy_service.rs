use std::collections::BTreeSet;

use super::*;

const ROOT_TASK_ROLE: &str = "goal_root";
const ROOT_TASK_METADATA_KEY: &str = "root_goal_task_id";
const TASK_ROLE_METADATA_KEY: &str = "task_role";
const WORKSPACE_PLAN_ID_METADATA_KEY: &str = "workspace_plan_id";
const NON_OPEN_ROOT_STATUSES: &[&str] = &["done", "blocked"];
const REMEDIATION_STATUSES_NEEDING_PROGRESS: &[&str] = &["replan_required", "ready_for_completion"];
const PRE_EXECUTION_STATUSES: &[&str] = &["todo", "dispatched"];
const RESUMABLE_PLAN_STATUSES: &[&str] = &["active", "draft"];
const DEDUP_PLAN_STATUSES: &[&str] = &["active", "draft", "completed"];

enum RootTaskProgressSelection {
    NoOpenRoot,
    NoRootNeedsProgress,
    Selected {
        root_task: Box<WorkspaceTaskRecord>,
        children: Vec<WorkspaceTaskRecord>,
    },
}

impl PgWorkspaceService {
    pub(super) async fn pg_trigger_autonomy_tick(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: AutonomyTickRequest,
    ) -> Result<AutonomyTickView, WorkspaceApiError> {
        if self
            .repo
            .workspace_scope(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .is_none()
        {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;

        let (root_task, children) = match self
            .pg_select_root_task_needing_progress(workspace_id, body.force)
            .await?
        {
            RootTaskProgressSelection::NoOpenRoot => {
                return Ok(AutonomyTickView::new(false, None, "no_open_root"));
            }
            RootTaskProgressSelection::NoRootNeedsProgress => {
                return Ok(AutonomyTickView::new(false, None, "no_root_needs_progress"));
            }
            RootTaskProgressSelection::Selected {
                root_task,
                children,
            } => (*root_task, children),
        };

        let Some(plan) = self
            .pg_find_root_plan(workspace_id, &root_task, &children)
            .await?
        else {
            let reason = if root_has_workspace_plan_linked_children(&children) {
                "durable_plan_active"
            } else {
                "durable_plan_unavailable"
            };
            return Ok(AutonomyTickView::new(false, Some(root_task.id), reason));
        };

        let reason = self
            .pg_enqueue_supervisor_tick_if_needed(user_id, workspace_id, &root_task.id, &plan)
            .await?;
        Ok(AutonomyTickView::new(false, Some(root_task.id), reason))
    }

    async fn pg_select_root_task_needing_progress(
        &self,
        workspace_id: &str,
        force: bool,
    ) -> Result<RootTaskProgressSelection, WorkspaceApiError> {
        let mut root_tasks = self
            .repo
            .list_tasks(workspace_id, None, 100, 0)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .filter(open_root_task)
            .collect::<Vec<_>>();
        if root_tasks.is_empty() {
            return Ok(RootTaskProgressSelection::NoOpenRoot);
        }
        root_tasks.sort_by(root_task_priority_cmp);
        for root_task in root_tasks {
            let children = self
                .repo
                .list_tasks_by_root_goal_task_id(workspace_id, &root_task.id)
                .await
                .map_err(WorkspaceApiError::internal)?;
            if root_task_needs_progress(&root_task, &children, force) {
                return Ok(RootTaskProgressSelection::Selected {
                    root_task: Box::new(root_task),
                    children,
                });
            }
        }
        Ok(RootTaskProgressSelection::NoRootNeedsProgress)
    }

    async fn pg_find_root_plan(
        &self,
        workspace_id: &str,
        root_task: &WorkspaceTaskRecord,
        children: &[WorkspaceTaskRecord],
    ) -> Result<Option<WorkspacePlanRecord>, WorkspaceApiError> {
        for plan_id in root_plan_ids_from_tasks(root_task, children) {
            let Some(plan) = self
                .repo
                .get_plan(&plan_id)
                .await
                .map_err(WorkspaceApiError::internal)?
            else {
                continue;
            };
            if plan.workspace_id == workspace_id
                && DEDUP_PLAN_STATUSES.contains(&plan.status.as_str())
            {
                return Ok(Some(plan));
            }
        }

        let plans = self
            .repo
            .list_plans(workspace_id, 50)
            .await
            .map_err(WorkspaceApiError::internal)?;
        for plan in plans {
            if !DEDUP_PLAN_STATUSES.contains(&plan.status.as_str()) {
                continue;
            }
            let nodes = self
                .repo
                .list_plan_nodes(&plan.id)
                .await
                .map_err(WorkspaceApiError::internal)?;
            if plan_nodes_link_root(&nodes, root_task) {
                return Ok(Some(plan));
            }
        }
        Ok(None)
    }

    async fn pg_enqueue_supervisor_tick_if_needed(
        &self,
        user_id: &str,
        workspace_id: &str,
        root_task_id: &str,
        plan: &WorkspacePlanRecord,
    ) -> Result<&'static str, WorkspaceApiError> {
        if !RESUMABLE_PLAN_STATUSES.contains(&plan.status.as_str()) {
            return Ok("durable_plan_active");
        }
        let outbox = self
            .repo
            .list_plan_outbox(&plan.id, 250)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if has_pending_supervisor_tick(&outbox) {
            return Ok("durable_plan_active");
        }
        self.repo
            .enqueue_plan_outbox(autonomy_supervisor_tick_outbox(
                &plan.id,
                workspace_id,
                root_task_id,
                user_id,
                Utc::now(),
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok("durable_plan_started")
    }
}

impl DevWorkspaceService {
    pub(super) async fn dev_trigger_autonomy_tick(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: AutonomyTickRequest,
    ) -> Result<AutonomyTickView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let (root_task, children) =
            match dev_select_root_task_needing_progress(&state, workspace_id, body.force) {
                RootTaskProgressSelection::NoOpenRoot => {
                    return Ok(AutonomyTickView::new(false, None, "no_open_root"));
                }
                RootTaskProgressSelection::NoRootNeedsProgress => {
                    return Ok(AutonomyTickView::new(false, None, "no_root_needs_progress"));
                }
                RootTaskProgressSelection::Selected {
                    root_task,
                    children,
                } => (*root_task, children),
            };

        let Some(plan) = dev_find_root_plan(&state, workspace_id, &root_task, &children) else {
            let reason = if root_has_workspace_plan_linked_children(&children) {
                "durable_plan_active"
            } else {
                "durable_plan_unavailable"
            };
            return Ok(AutonomyTickView::new(false, Some(root_task.id), reason));
        };

        if !RESUMABLE_PLAN_STATUSES.contains(&plan.status.as_str()) {
            return Ok(AutonomyTickView::new(
                false,
                Some(root_task.id),
                "durable_plan_active",
            ));
        }
        let pending = state
            .plan_outbox
            .iter()
            .filter(|item| item.plan_id.as_deref() == Some(plan.id.as_str()))
            .any(supervisor_tick_is_pending);
        if pending {
            return Ok(AutonomyTickView::new(
                false,
                Some(root_task.id),
                "durable_plan_active",
            ));
        }
        state.plan_outbox.push(autonomy_supervisor_tick_outbox(
            &plan.id,
            workspace_id,
            &root_task.id,
            user_id,
            Utc::now(),
        ));
        Ok(AutonomyTickView::new(
            false,
            Some(root_task.id),
            "durable_plan_started",
        ))
    }
}

fn dev_select_root_task_needing_progress(
    state: &DevWorkspaceState,
    workspace_id: &str,
    force: bool,
) -> RootTaskProgressSelection {
    let mut root_tasks = state
        .tasks
        .values()
        .filter(|task| task.workspace_id == workspace_id)
        .filter(|task| open_root_task(task))
        .cloned()
        .collect::<Vec<_>>();
    if root_tasks.is_empty() {
        return RootTaskProgressSelection::NoOpenRoot;
    }
    root_tasks.sort_by(root_task_priority_cmp);
    root_tasks
        .into_iter()
        .find_map(|root_task| {
            let children = state
                .tasks
                .values()
                .filter(|task| task.workspace_id == workspace_id)
                .filter(|task| task.archived_at.is_none())
                .filter(|task| {
                    metadata_string(&task.metadata_json, ROOT_TASK_METADATA_KEY).as_deref()
                        == Some(root_task.id.as_str())
                })
                .cloned()
                .collect::<Vec<_>>();
            if root_task_needs_progress(&root_task, &children, force) {
                Some(RootTaskProgressSelection::Selected {
                    root_task: Box::new(root_task),
                    children,
                })
            } else {
                None
            }
        })
        .unwrap_or(RootTaskProgressSelection::NoRootNeedsProgress)
}

fn dev_find_root_plan(
    state: &DevWorkspaceState,
    workspace_id: &str,
    root_task: &WorkspaceTaskRecord,
    children: &[WorkspaceTaskRecord],
) -> Option<WorkspacePlanRecord> {
    for plan_id in root_plan_ids_from_tasks(root_task, children) {
        let Some(plan) = state.plans.get(&plan_id) else {
            continue;
        };
        if plan.workspace_id == workspace_id && DEDUP_PLAN_STATUSES.contains(&plan.status.as_str())
        {
            return Some(plan.clone());
        }
    }
    let mut plans = state
        .plans
        .values()
        .filter(|plan| plan.workspace_id == workspace_id)
        .filter(|plan| DEDUP_PLAN_STATUSES.contains(&plan.status.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    plans.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(a.id.cmp(&b.id)));
    plans.into_iter().find(|plan| {
        let nodes = state
            .plan_nodes
            .values()
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .collect::<Vec<_>>();
        plan_nodes_link_root(&nodes, root_task)
    })
}

fn open_root_task(task: &WorkspaceTaskRecord) -> bool {
    task.archived_at.is_none()
        && !NON_OPEN_ROOT_STATUSES.contains(&task.status.as_str())
        && metadata_string(&task.metadata_json, TASK_ROLE_METADATA_KEY).as_deref()
            == Some(ROOT_TASK_ROLE)
}

fn root_task_needs_progress(
    root_task: &WorkspaceTaskRecord,
    children: &[WorkspaceTaskRecord],
    force: bool,
) -> bool {
    if children.is_empty() || force {
        return true;
    }
    let remediation_status = metadata_string(&root_task.metadata_json, "remediation_status")
        .unwrap_or_else(|| "none".to_string());
    REMEDIATION_STATUSES_NEEDING_PROGRESS.contains(&remediation_status.as_str())
        || children
            .iter()
            .any(|child| PRE_EXECUTION_STATUSES.contains(&child.status.as_str()))
}

fn root_task_priority_cmp(a: &WorkspaceTaskRecord, b: &WorkspaceTaskRecord) -> std::cmp::Ordering {
    root_task_priority(a)
        .cmp(&root_task_priority(b))
        .then(a.id.cmp(&b.id))
}

fn root_task_priority(task: &WorkspaceTaskRecord) -> i32 {
    match metadata_string(&task.metadata_json, "remediation_status").as_deref() {
        Some("ready_for_completion") => 0,
        Some("replan_required") => 1,
        _ => 2,
    }
}

fn root_plan_ids_from_tasks(
    root_task: &WorkspaceTaskRecord,
    children: &[WorkspaceTaskRecord],
) -> BTreeSet<String> {
    std::iter::once(root_task)
        .chain(children.iter())
        .filter_map(|task| metadata_string(&task.metadata_json, WORKSPACE_PLAN_ID_METADATA_KEY))
        .filter(|plan_id| !plan_id.trim().is_empty())
        .collect()
}

fn plan_nodes_link_root(
    nodes: &[WorkspacePlanNodeRecord],
    root_task: &WorkspaceTaskRecord,
) -> bool {
    nodes.iter().any(|node| {
        node.workspace_task_id.as_deref() == Some(root_task.id.as_str())
            || metadata_string(&node.metadata_json, ROOT_TASK_METADATA_KEY).as_deref()
                == Some(root_task.id.as_str())
    })
}

fn root_has_workspace_plan_linked_children(children: &[WorkspaceTaskRecord]) -> bool {
    children.iter().any(|child| {
        metadata_string(&child.metadata_json, WORKSPACE_PLAN_ID_METADATA_KEY)
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
    })
}

fn has_pending_supervisor_tick(outbox: &[WorkspacePlanOutboxRecord]) -> bool {
    outbox.iter().any(supervisor_tick_is_pending)
}

fn supervisor_tick_is_pending(item: &WorkspacePlanOutboxRecord) -> bool {
    item.event_type == SUPERVISOR_TICK_EVENT
        && matches!(item.status.as_str(), "pending" | "processing" | "failed")
}

fn metadata_string(metadata: &Value, key: &str) -> Option<String> {
    string_from_value(metadata.get(key))
}

fn autonomy_supervisor_tick_outbox(
    plan_id: &str,
    workspace_id: &str,
    root_task_id: &str,
    actor_id: &str,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    plan_actions::plan_action_outbox(
        plan_id,
        workspace_id,
        SUPERVISOR_TICK_EVENT,
        json!({
            "workspace_id": workspace_id,
            "root_task_id": root_task_id,
            "actor_user_id": actor_id,
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        }),
        json!({
            "source": "workspace.autonomy_tick",
            "resume_existing_root_plan": true,
        }),
        created_at,
    )
}
