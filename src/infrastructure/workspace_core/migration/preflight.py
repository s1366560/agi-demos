"""Deterministic source integrity checks for the Workspace migration."""

from __future__ import annotations

from .model import PreflightCheck

PREFLIGHT_CHECKS: tuple[PreflightCheck, ...] = (
    PreflightCheck(
        code="workspace_scope_invalid",
        description="workspace tenant/project ownership is missing or inconsistent",
        sql="""
            SELECT w.id::text AS sample
            FROM workspaces w
            LEFT JOIN tenants t ON t.id = w.tenant_id
            LEFT JOIN projects p ON p.id = w.project_id
            WHERE t.id IS NULL OR p.id IS NULL OR p.tenant_id <> w.tenant_id
        """,
    ),
    PreflightCheck(
        code="workspace_member_orphan",
        description="workspace member references a missing workspace or user",
        sql="""
            SELECT m.id::text AS sample
            FROM workspace_members m
            LEFT JOIN workspaces w ON w.id = m.workspace_id
            LEFT JOIN users u ON u.id = m.user_id
            WHERE w.id IS NULL OR u.id IS NULL
        """,
    ),
    PreflightCheck(
        code="workspace_member_role_invalid",
        description="workspace member role is outside owner/editor/viewer",
        sql="""
            SELECT m.id::text AS sample
            FROM workspace_members m
            WHERE m.role NOT IN ('owner', 'editor', 'viewer')
        """,
    ),
    PreflightCheck(
        code="workspace_child_orphan",
        description="workspace child row references a missing workspace",
        sql="""
            SELECT child_table || ':' || child_id AS sample
            FROM (
                SELECT 'workspace_agents' AS child_table, id::text AS child_id, workspace_id
                FROM workspace_agents
                UNION ALL SELECT 'blackboard_posts', id::text, workspace_id FROM blackboard_posts
                UNION ALL SELECT 'blackboard_files', id::text, workspace_id FROM blackboard_files
                UNION ALL SELECT 'workspace_tasks', id::text, workspace_id FROM workspace_tasks
                UNION ALL SELECT 'topology_nodes', id::text, workspace_id FROM topology_nodes
                UNION ALL SELECT 'topology_edges', id::text, workspace_id FROM topology_edges
                UNION ALL SELECT 'cyber_objectives', id::text, workspace_id FROM cyber_objectives
                UNION ALL SELECT 'cyber_genes', id::text, workspace_id FROM cyber_genes
                UNION ALL SELECT 'workspace_messages', id::text, workspace_id FROM workspace_messages
                UNION ALL SELECT 'workspace_plans', id::text, workspace_id FROM workspace_plans
            ) children
            LEFT JOIN workspaces w ON w.id = children.workspace_id
            WHERE w.id IS NULL
        """,
    ),
    PreflightCheck(
        code="blackboard_reply_scope_invalid",
        description="blackboard reply and post do not belong to the same workspace",
        sql="""
            SELECT r.id::text AS sample
            FROM blackboard_replies r
            LEFT JOIN blackboard_posts p ON p.id = r.post_id
            WHERE p.id IS NULL OR p.workspace_id <> r.workspace_id
        """,
    ),
    PreflightCheck(
        code="topology_edge_scope_invalid",
        description="topology edge endpoints are missing or cross workspace scope",
        sql="""
            SELECT e.id::text AS sample
            FROM topology_edges e
            LEFT JOIN topology_nodes source ON source.id = e.source_node_id
            LEFT JOIN topology_nodes target ON target.id = e.target_node_id
            WHERE source.id IS NULL OR target.id IS NULL
               OR source.workspace_id <> e.workspace_id
               OR target.workspace_id <> e.workspace_id
        """,
    ),
    PreflightCheck(
        code="objective_parent_scope_invalid",
        description="objective parent is missing or belongs to another workspace",
        sql="""
            SELECT objective.id::text AS sample
            FROM cyber_objectives objective
            LEFT JOIN cyber_objectives parent ON parent.id = objective.parent_id
            WHERE objective.parent_id IS NOT NULL
              AND (parent.id IS NULL OR parent.workspace_id <> objective.workspace_id)
        """,
    ),
    PreflightCheck(
        code="task_attempt_scope_invalid",
        description="task attempt references a missing or cross-workspace task",
        sql="""
            SELECT attempt.id::text AS sample
            FROM workspace_task_session_attempts attempt
            LEFT JOIN workspace_tasks task ON task.id = attempt.workspace_task_id
            LEFT JOIN workspace_tasks root ON root.id = attempt.root_goal_task_id
            WHERE task.id IS NULL OR root.id IS NULL
               OR task.workspace_id <> attempt.workspace_id
               OR root.workspace_id <> attempt.workspace_id
        """,
    ),
    PreflightCheck(
        code="plan_child_scope_invalid",
        description="plan child references a missing plan or a different workspace",
        sql="""
            SELECT child_table || ':' || child_id AS sample
            FROM (
                SELECT 'workspace_plan_nodes' AS child_table, n.id::text AS child_id,
                       n.plan_id, t.workspace_id
                FROM workspace_plan_nodes n
                LEFT JOIN workspace_tasks t ON t.id = n.workspace_task_id
                UNION ALL
                SELECT 'workspace_plan_events', e.id::text, e.plan_id, e.workspace_id
                FROM workspace_plan_events e
            ) children
            LEFT JOIN workspace_plans p ON p.id = children.plan_id
            WHERE p.id IS NULL
               OR (children.workspace_id IS NOT NULL AND children.workspace_id <> p.workspace_id)
        """,
    ),
)
