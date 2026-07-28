const WORKSPACE_COLLABORATION_EVENT_TYPES = new Set([
  'blackboard_directory_deleted',
  'blackboard_file_created',
  'blackboard_file_deleted',
  'blackboard_file_updated',
  'blackboard_post_created',
  'blackboard_post_deleted',
  'blackboard_post_updated',
  'blackboard_reply_created',
  'blackboard_reply_deleted',
  'blackboard_reply_updated',
  'topology_updated',
  'workspace_agent_bound',
  'workspace_agent_unbound',
  'workspace_deleted',
  'workspace_member_joined',
  'workspace_member_left',
  'workspace_member_updated',
  'workspace_message_created',
  'workspace_task_assigned',
  'workspace_task_created',
  'workspace_task_deleted',
  'workspace_task_status_changed',
  'workspace_task_updated',
  'workspace_updated',
]);

export function workspaceCollaborationAuthorityEvent(
  event: unknown,
  workspaceId: string,
): boolean {
  const expectedWorkspaceId = workspaceId.trim();
  if (!expectedWorkspaceId) return false;
  const root = recordValue(event);
  const type = stringValue(root?.type ?? root?.event_type);
  if (!root || !type || !WORKSPACE_COLLABORATION_EVENT_TYPES.has(type)) return false;
  const data = recordValue(root.data) ?? recordValue(root.payload);
  if (!data) return false;
  const message = recordValue(data.message);
  const eventWorkspaceId = stringValue(
    data.workspace_id ??
      data.workspaceId ??
      message?.workspace_id ??
      message?.workspaceId,
  );
  return eventWorkspaceId === expectedWorkspaceId;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
