use std::collections::{BTreeSet, HashMap};

use super::*;

const ROOT_TASK_ROLE: &str = "goal_root";
const ROOT_TASK_METADATA_KEY: &str = "root_goal_task_id";
const TASK_ROLE_METADATA_KEY: &str = "task_role";
const WORKSPACE_PLAN_ID_METADATA_KEY: &str = "workspace_plan_id";
const AUTO_TRIGGER_COOLDOWN_SECONDS: i64 = 60;
const REPLAN_TRIGGER_COOLDOWN_SECONDS: i64 = 300;
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

        if !body.force
            && autonomy_is_on_cooldown(
                self.autonomy_cooldown.as_deref(),
                workspace_id,
                &root_task.id,
            )
            .await
        {
            return Ok(AutonomyTickView::new(
                false,
                Some(root_task.id),
                "cooling_down",
            ));
        }

        let Some(plan) = self
            .pg_find_root_plan(workspace_id, &root_task, &children)
            .await?
        else {
            let reason = if root_has_workspace_plan_linked_children(&children) {
                "durable_plan_active"
            } else {
                "durable_plan_unavailable"
            };
            let ttl_seconds = if reason == "durable_plan_unavailable" {
                autonomy_unavailable_cooldown_seconds(&root_task, !children.is_empty())
            } else {
                AUTO_TRIGGER_COOLDOWN_SECONDS
            };
            mark_autonomy_cooldown(
                self.autonomy_cooldown.as_deref(),
                workspace_id,
                &root_task.id,
                ttl_seconds,
            )
            .await;
            return Ok(AutonomyTickView::new(false, Some(root_task.id), reason));
        };

        let reason = self
            .pg_enqueue_supervisor_tick_if_needed(user_id, workspace_id, &root_task.id, &plan)
            .await?;
        mark_autonomy_cooldown(
            self.autonomy_cooldown.as_deref(),
            workspace_id,
            &root_task.id,
            AUTO_TRIGGER_COOLDOWN_SECONDS,
        )
        .await;
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
        // One batch fetch for every open root's children instead of a
        // sequential query per root (up to 100 round-trips per tick).
        let root_ids: Vec<String> = root_tasks.iter().map(|task| task.id.clone()).collect();
        let children = self
            .repo
            .list_tasks_by_root_goal_task_ids(workspace_id, &root_ids)
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(select_root_from_grouped_children(
            root_tasks, children, force,
        ))
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
        let candidates: Vec<WorkspacePlanRecord> = plans
            .into_iter()
            .filter(|plan| DEDUP_PLAN_STATUSES.contains(&plan.status.as_str()))
            .collect();
        if candidates.is_empty() {
            return Ok(None);
        }
        // One batch fetch for all candidate plans' nodes instead of a
        // sequential query per plan (up to 50 round-trips per tick).
        let plan_ids: Vec<String> = candidates.iter().map(|plan| plan.id.clone()).collect();
        let nodes = self
            .repo
            .list_plan_nodes_by_plan_ids(&plan_ids)
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(first_plan_linking_root(candidates, nodes, root_task))
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
        let (root_task, children) = {
            let state = self.lock_state()?;
            if !state.workspaces.contains_key(workspace_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
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
            }
        };

        if !body.force
            && autonomy_is_on_cooldown(
                self.autonomy_cooldown.as_deref(),
                workspace_id,
                &root_task.id,
            )
            .await
        {
            return Ok(AutonomyTickView::new(
                false,
                Some(root_task.id),
                "cooling_down",
            ));
        }

        let (reason, ttl_seconds) = {
            let mut state = self.lock_state()?;
            match dev_find_root_plan(&state, workspace_id, &root_task, &children) {
                None => {
                    let reason = if root_has_workspace_plan_linked_children(&children) {
                        "durable_plan_active"
                    } else {
                        "durable_plan_unavailable"
                    };
                    let ttl_seconds = if reason == "durable_plan_unavailable" {
                        autonomy_unavailable_cooldown_seconds(&root_task, !children.is_empty())
                    } else {
                        AUTO_TRIGGER_COOLDOWN_SECONDS
                    };
                    (reason, ttl_seconds)
                }
                Some(plan) if !RESUMABLE_PLAN_STATUSES.contains(&plan.status.as_str()) => {
                    ("durable_plan_active", AUTO_TRIGGER_COOLDOWN_SECONDS)
                }
                Some(plan) => {
                    let pending = state
                        .plan_outbox
                        .iter()
                        .filter(|item| item.plan_id.as_deref() == Some(plan.id.as_str()))
                        .any(supervisor_tick_is_pending);
                    if pending {
                        ("durable_plan_active", AUTO_TRIGGER_COOLDOWN_SECONDS)
                    } else {
                        state.plan_outbox.push(autonomy_supervisor_tick_outbox(
                            &plan.id,
                            workspace_id,
                            &root_task.id,
                            user_id,
                            Utc::now(),
                        ));
                        ("durable_plan_started", AUTO_TRIGGER_COOLDOWN_SECONDS)
                    }
                }
            }
        };
        mark_autonomy_cooldown(
            self.autonomy_cooldown.as_deref(),
            workspace_id,
            &root_task.id,
            ttl_seconds,
        )
        .await;
        Ok(AutonomyTickView::new(false, Some(root_task.id), reason))
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

/// Pick the first root task — in the caller's priority order — that needs
/// progress, using children batch-fetched for all open roots (one query)
/// instead of a per-root early-exit loop (one query per root). Grouping
/// preserves the batch query's per-root row order, so the selected root and
/// its children are identical to the loop form.
fn select_root_from_grouped_children(
    root_tasks: Vec<WorkspaceTaskRecord>,
    children: Vec<WorkspaceTaskRecord>,
    force: bool,
) -> RootTaskProgressSelection {
    let mut children_by_root: HashMap<String, Vec<WorkspaceTaskRecord>> = HashMap::new();
    for child in children {
        if let Some(root_id) = metadata_string(&child.metadata_json, ROOT_TASK_METADATA_KEY) {
            children_by_root.entry(root_id).or_default().push(child);
        }
    }
    for root_task in root_tasks {
        let children = children_by_root.remove(&root_task.id).unwrap_or_default();
        if root_task_needs_progress(&root_task, &children, force) {
            return RootTaskProgressSelection::Selected {
                root_task: Box::new(root_task),
                children,
            };
        }
    }
    RootTaskProgressSelection::NoRootNeedsProgress
}

/// First candidate plan — in the caller's list order — whose nodes link
/// `root_task`, using nodes batch-fetched for all candidates (one query)
/// instead of a per-plan loop. Same first-match semantics as the loop form.
fn first_plan_linking_root(
    plans: Vec<WorkspacePlanRecord>,
    nodes: Vec<WorkspacePlanNodeRecord>,
    root_task: &WorkspaceTaskRecord,
) -> Option<WorkspacePlanRecord> {
    let mut nodes_by_plan: HashMap<String, Vec<WorkspacePlanNodeRecord>> = HashMap::new();
    for node in nodes {
        nodes_by_plan.entry(node.plan_id.clone()).or_default().push(node);
    }
    plans.into_iter().find(|plan| {
        let nodes = nodes_by_plan.remove(&plan.id).unwrap_or_default();
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

async fn autonomy_is_on_cooldown(
    cooldown: Option<&dyn AutonomyCooldownStore>,
    workspace_id: &str,
    root_task_id: &str,
) -> bool {
    let Some(cooldown) = cooldown else {
        return false;
    };
    (cooldown.is_on_cooldown(workspace_id, root_task_id).await).unwrap_or_default()
}

async fn mark_autonomy_cooldown(
    cooldown: Option<&dyn AutonomyCooldownStore>,
    workspace_id: &str,
    root_task_id: &str,
    ttl_seconds: i64,
) {
    let Some(cooldown) = cooldown else {
        return;
    };
    if let Err(error) = cooldown
        .mark_cooldown(workspace_id, root_task_id, ttl_seconds)
        .await
    {
        eprintln!("[agistack] workspace autonomy cooldown mark failed: {error}");
    }
}

fn autonomy_unavailable_cooldown_seconds(
    root_task: &WorkspaceTaskRecord,
    has_children: bool,
) -> i64 {
    let remediation_status = if has_children {
        metadata_string(&root_task.metadata_json, "remediation_status")
            .unwrap_or_else(|| "none".to_string())
    } else {
        "none".to_string()
    };
    if remediation_status == "replan_required" {
        REPLAN_TRIGGER_COOLDOWN_SECONDS
    } else {
        AUTO_TRIGGER_COOLDOWN_SECONDS
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

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> DateTime<Utc> {
        "2026-01-02T03:04:05Z".parse().unwrap()
    }

    fn root_task(id: &str) -> WorkspaceTaskRecord {
        WorkspaceTaskRecord {
            id: id.to_string(),
            workspace_id: "ws".to_string(),
            title: format!("root {id}"),
            description: None,
            created_by: "user-1".to_string(),
            assignee_user_id: None,
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: 1,
            estimated_effort: None,
            blocker_reason: None,
            metadata_json: json!({"task_role": "goal_root"}),
            created_at: now(),
            updated_at: None,
            completed_at: None,
            archived_at: None,
        }
    }

    fn child_task(id: &str, root_id: &str, status: &str) -> WorkspaceTaskRecord {
        WorkspaceTaskRecord {
            id: id.to_string(),
            workspace_id: "ws".to_string(),
            title: format!("child {id}"),
            description: None,
            created_by: "user-1".to_string(),
            assignee_user_id: None,
            assignee_agent_id: None,
            status: status.to_string(),
            priority: 1,
            estimated_effort: None,
            blocker_reason: None,
            metadata_json: json!({
                "task_role": "execution_task",
                "root_goal_task_id": root_id,
            }),
            created_at: now(),
            updated_at: None,
            completed_at: None,
            archived_at: None,
        }
    }

    fn plan(id: &str, status: &str) -> WorkspacePlanRecord {
        WorkspacePlanRecord {
            id: id.to_string(),
            workspace_id: "ws".to_string(),
            goal_id: format!("goal-{id}"),
            status: status.to_string(),
            created_at: now(),
            updated_at: None,
        }
    }

    fn plan_node(id: &str, plan_id: &str, root_id: Option<&str>) -> WorkspacePlanNodeRecord {
        WorkspacePlanNodeRecord {
            id: id.to_string(),
            plan_id: plan_id.to_string(),
            parent_id: None,
            kind: "goal".to_string(),
            title: format!("node {id}"),
            description: String::new(),
            depends_on_json: Vec::new(),
            inputs_schema_json: json!({}),
            outputs_schema_json: json!({}),
            acceptance_criteria_json: Vec::new(),
            feature_checkpoint_json: None,
            handoff_package_json: None,
            recommended_capabilities_json: Vec::new(),
            preferred_agent_id: None,
            estimated_effort_json: json!({}),
            priority: 0,
            intent: "todo".to_string(),
            execution: "idle".to_string(),
            progress_json: json!({}),
            assignee_agent_id: None,
            current_attempt_id: None,
            workspace_task_id: root_id.map(str::to_string),
            metadata_json: json!({}),
            created_at: now(),
            updated_at: None,
            completed_at: None,
        }
    }

    #[test]
    fn select_root_skips_roots_not_needing_progress_and_groups_children() {
        // r1's only child is past pre-execution, so r1 needs no progress;
        // r2 has a todo child. Children arrive interleaved from the batch
        // query and must be grouped back under their own root.
        let roots = vec![root_task("r1"), root_task("r2")];
        let children = vec![
            child_task("c2-a", "r2", "todo"),
            child_task("c1-a", "r1", "in_progress"),
            child_task("c2-b", "r2", "dispatched"),
        ];
        match select_root_from_grouped_children(roots, children, false) {
            RootTaskProgressSelection::Selected {
                root_task,
                children,
            } => {
                assert_eq!(root_task.id, "r2");
                let ids: Vec<&str> = children.iter().map(|c| c.id.as_str()).collect();
                assert_eq!(ids, vec!["c2-a", "c2-b"], "group keeps batch row order");
            }
            _ => panic!("expected r2 selected"),
        }
    }

    #[test]
    fn select_root_with_empty_children_needs_progress() {
        // Same as the loop form: a root without children always needs progress.
        let roots = vec![root_task("r1")];
        match select_root_from_grouped_children(roots, Vec::new(), false) {
            RootTaskProgressSelection::Selected {
                root_task,
                children,
            } => {
                assert_eq!(root_task.id, "r1");
                assert!(children.is_empty());
            }
            _ => panic!("expected r1 selected"),
        }
    }

    #[test]
    fn select_root_returns_no_progress_when_all_roots_satisfied() {
        let roots = vec![root_task("r1")];
        let children = vec![child_task("c1", "r1", "in_progress")];
        assert!(matches!(
            select_root_from_grouped_children(roots, children, false),
            RootTaskProgressSelection::NoRootNeedsProgress
        ));
    }

    #[test]
    fn first_plan_linking_root_matches_loop_first_match_order() {
        let root = root_task("r1");
        let plans = vec![
            plan("p1", "active"),
            plan("p2", "draft"),
            plan("p3", "active"),
        ];
        // Interleaved batch rows: p1 does not link the root; p2 links via
        // metadata; p3 also links but must lose to p2 (list order wins).
        let nodes = vec![
            plan_node("n3", "p3", Some("r1")),
            plan_node("n1", "p1", Some("other-root")),
            WorkspacePlanNodeRecord {
                metadata_json: json!({"root_goal_task_id": "r1"}),
                ..plan_node("n2", "p2", None)
            },
        ];
        let found = first_plan_linking_root(plans, nodes, &root);
        assert_eq!(found.map(|p| p.id), Some("p2".to_string()));
    }

    #[test]
    fn first_plan_linking_root_returns_none_without_link() {
        let root = root_task("r1");
        let plans = vec![plan("p1", "active")];
        let nodes = vec![plan_node("n1", "p1", Some("other-root"))];
        assert!(first_plan_linking_root(plans, nodes, &root).is_none());
    }
}
