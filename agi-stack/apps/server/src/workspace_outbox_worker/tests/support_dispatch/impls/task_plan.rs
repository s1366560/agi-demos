use super::super::*;

pub(super) async fn get_workspace(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_id: &str,
) -> CoreResult<Option<WorkspaceRecord>> {
    Ok(store.workspaces.lock().unwrap().get(workspace_id).cloned())
}

pub(super) async fn get_task(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_id: &str,
    task_id: &str,
) -> CoreResult<Option<WorkspaceTaskRecord>> {
    Ok(store
        .tasks
        .lock()
        .unwrap()
        .get(task_id)
        .filter(|task| task.workspace_id == workspace_id)
        .cloned())
}

pub(super) async fn list_tasks_by_root_goal_task_id(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_id: &str,
    root_goal_task_id: &str,
) -> CoreResult<Vec<WorkspaceTaskRecord>> {
    let mut tasks = store
        .tasks
        .lock()
        .unwrap()
        .values()
        .filter(|task| {
            task.workspace_id == workspace_id
                && task.archived_at.is_none()
                && string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).as_deref()
                    == Some(root_goal_task_id)
        })
        .cloned()
        .collect::<Vec<_>>();
    tasks.sort_by(|left, right| {
        left.created_at
            .cmp(&right.created_at)
            .then_with(|| left.id.cmp(&right.id))
    });
    Ok(tasks)
}

pub(super) async fn list_current_plan_child_tasks_by_root_goal_task_id(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_id: &str,
    root_goal_task_id: &str,
) -> CoreResult<Vec<WorkspaceTaskRecord>> {
    let nodes = store.nodes.lock().unwrap().clone();
    let mut tasks = store
        .tasks
        .lock()
        .unwrap()
        .values()
        .filter(|task| {
            if task.workspace_id != workspace_id || task.archived_at.is_some() {
                return false;
            }
            if string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).as_deref()
                != Some(root_goal_task_id)
            {
                return false;
            }
            let Some(plan_id) = string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_ID)
            else {
                return false;
            };
            let Some(node_id) =
                string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_NODE_ID)
            else {
                return false;
            };
            nodes.get(&node_id).is_some_and(|node| {
                node.plan_id == plan_id
                    && node.workspace_task_id.as_deref() == Some(task.id.as_str())
            })
        })
        .cloned()
        .collect::<Vec<_>>();
    tasks.sort_by(|left, right| {
        left.created_at
            .cmp(&right.created_at)
            .then_with(|| left.id.cmp(&right.id))
    });
    Ok(tasks)
}

pub(super) async fn save_task(
    store: &FakeWorkspacePlanDispatchStore,
    task: WorkspaceTaskRecord,
) -> CoreResult<WorkspaceTaskRecord> {
    store
        .tasks
        .lock()
        .unwrap()
        .insert(task.id.clone(), task.clone());
    Ok(task)
}

pub(super) async fn get_plan(
    store: &FakeWorkspacePlanDispatchStore,
    plan_id: &str,
) -> CoreResult<Option<WorkspacePlanRecord>> {
    Ok(store.plans.lock().unwrap().get(plan_id).cloned())
}

pub(super) async fn list_plan_nodes(
    store: &FakeWorkspacePlanDispatchStore,
    plan_id: &str,
) -> CoreResult<Vec<WorkspacePlanNodeRecord>> {
    Ok(store
        .nodes
        .lock()
        .unwrap()
        .values()
        .filter(|node| node.plan_id == plan_id)
        .cloned()
        .collect())
}

pub(super) async fn create_plan_node(
    store: &FakeWorkspacePlanDispatchStore,
    node: WorkspacePlanNodeRecord,
) -> CoreResult<WorkspacePlanNodeRecord> {
    store
        .nodes
        .lock()
        .unwrap()
        .insert(node.id.clone(), node.clone());
    Ok(node)
}

pub(super) async fn save_plan_node(
    store: &FakeWorkspacePlanDispatchStore,
    node: WorkspacePlanNodeRecord,
) -> CoreResult<WorkspacePlanNodeRecord> {
    store
        .nodes
        .lock()
        .unwrap()
        .insert(node.id.clone(), node.clone());
    Ok(node)
}
