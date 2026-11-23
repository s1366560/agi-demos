export type WorkspaceLiveActivity = {
  id: string;
  eventType: string;
  title: string;
  detail: string | null;
};

export type WorkspaceActivityStreamResult = {
  handled: boolean;
  activities: WorkspaceLiveActivity[];
};

const blackboardEventTypes = new Set([
  'blackboard_post_created',
  'blackboard_post_updated',
  'blackboard_post_deleted',
  'blackboard_reply_created',
  'blackboard_reply_updated',
  'blackboard_reply_deleted',
  'blackboard_file_created',
  'blackboard_file_updated',
  'blackboard_file_deleted',
  'blackboard_directory_deleted',
]);

export function applyWorkspaceActivityStreamEvent(
  activities: WorkspaceLiveActivity[],
  event: unknown,
  workspaceId: string,
): WorkspaceActivityStreamResult {
  const unchanged = { handled: false, activities };
  const root = recordValue(event);
  const type = stringValue(root?.type ?? root?.event_type);
  if (!root || !type || (type !== 'topology_updated' && !blackboardEventTypes.has(type))) {
    return unchanged;
  }
  const data = recordValue(root.data) ?? recordValue(root.payload);
  if (!data) return unchanged;
  if (blackboardEventTypes.has(type) && !isOwnedBlackboardEvent(data)) return unchanged;
  const scopedWorkspaceId = workspaceIdValue(data);
  if (scopedWorkspaceId && scopedWorkspaceId !== workspaceId) return unchanged;
  if (type === 'topology_updated' && scopedWorkspaceId !== workspaceId) return unchanged;

  const activity =
    type === 'topology_updated' ? topologyActivity(type, data) : blackboardActivity(type, data);
  if (!activity) return unchanged;
  return {
    handled: true,
    activities: [activity, ...activities.filter(({ id }) => id !== activity.id)].slice(0, 8),
  };
}

function blackboardActivity(
  type: string,
  data: Record<string, unknown>,
): WorkspaceLiveActivity | null {
  if (type === 'blackboard_post_created' || type === 'blackboard_post_updated') {
    const post = recordValue(data.post);
    const id = stringValue(post?.id);
    const title = stringValue(post?.title);
    if (!id || !title) return null;
    return activityValue(type, id, title, compactText(post?.content));
  }
  if (type === 'blackboard_post_deleted') {
    const id = stringValue(data.post_id ?? data.postId);
    return id ? activityValue(type, id, id, null) : null;
  }
  if (type === 'blackboard_reply_created' || type === 'blackboard_reply_updated') {
    const reply = recordValue(data.reply);
    const id = stringValue(reply?.id);
    const title = compactText(reply?.content);
    if (!id || !title) return null;
    return activityValue(
      type,
      id,
      title,
      stringValue(data.post_id ?? data.postId ?? reply?.post_id),
    );
  }
  if (type === 'blackboard_reply_deleted') {
    const id = stringValue(data.reply_id ?? data.replyId);
    if (!id) return null;
    return activityValue(type, id, id, stringValue(data.post_id ?? data.postId));
  }
  if (type === 'blackboard_file_created' || type === 'blackboard_file_updated') {
    const file = recordValue(data.file);
    const id = stringValue(file?.id ?? data.file_id ?? data.fileId);
    const title = stringValue(file?.name ?? data.name);
    if (!id || !title) return null;
    return activityValue(type, id, title, stringValue(file?.parent_path ?? data.parent_path));
  }
  const id = stringValue(data.file_id ?? data.fileId);
  return id ? activityValue(type, id, id, null) : null;
}

function topologyActivity(
  type: string,
  data: Record<string, unknown>,
): WorkspaceLiveActivity | null {
  const operation = stringValue(data.operation);
  if (!operation) return null;
  if (operation === 'node_created' || operation === 'node_updated') {
    const node = recordValue(data.node);
    const id = stringValue(node?.id ?? data.node_id ?? data.nodeId);
    const title = stringValue(node?.title) ?? id;
    return id && title ? activityValue(type, id, title, operation) : null;
  }
  if (operation === 'node_deleted') {
    const id = stringValue(data.node_id ?? data.nodeId);
    return id ? activityValue(type, id, id, operation) : null;
  }
  if (operation === 'edge_created' || operation === 'edge_updated') {
    const edge = recordValue(data.edge);
    const id = stringValue(edge?.id ?? data.edge_id ?? data.edgeId);
    const title = stringValue(edge?.label) ?? id;
    return id && title ? activityValue(type, id, title, operation) : null;
  }
  if (operation === 'edge_deleted') {
    const id = stringValue(data.edge_id ?? data.edgeId);
    return id ? activityValue(type, id, id, operation) : null;
  }
  return null;
}

function activityValue(
  eventType: string,
  entityId: string,
  title: string,
  detail: string | null,
): WorkspaceLiveActivity {
  return { id: `${eventType}:${entityId}`, eventType, title, detail };
}

function isOwnedBlackboardEvent(data: Record<string, unknown>): boolean {
  const boundary = data.surface_boundary;
  const authority = data.authority_class;
  if (boundary === undefined && authority === undefined) return true;
  return boundary === 'owned' && authority === 'authoritative';
}

function workspaceIdValue(data: Record<string, unknown>): string | null {
  const direct = stringValue(data.workspace_id ?? data.workspaceId);
  if (direct) return direct;
  for (const key of ['post', 'reply', 'file', 'node', 'edge']) {
    const nested = recordValue(data[key]);
    const nestedWorkspaceId = stringValue(nested?.workspace_id ?? nested?.workspaceId);
    if (nestedWorkspaceId) return nestedWorkspaceId;
  }
  return null;
}

function compactText(value: unknown): string | null {
  const text = stringValue(value);
  if (!text) return null;
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
