import type { BlackboardTab } from './BlackboardTabBar';

export type BlackboardBoundaryClass = 'owned' | 'hosted';
export type BlackboardAuthorityClass = 'authoritative' | 'non-authoritative';
export type BlackboardSignalRole = 'sensing-capable';

export const OWNED: BlackboardBoundaryClass = 'owned';
export const HOSTED: BlackboardBoundaryClass = 'hosted';

export const AUTHORITATIVE: BlackboardAuthorityClass = 'authoritative';
export const NON_AUTHORITATIVE: BlackboardAuthorityClass = 'non-authoritative';

export const SENSING_CAPABLE: BlackboardSignalRole = 'sensing-capable';

export type WorkspaceEventChannel =
  | 'presence'
  | 'agent_status'
  | 'task'
  | 'plan'
  | 'blackboard'
  | 'chat'
  | 'member'
  | 'lifecycle'
  | 'agent_binding'
  | 'topology'
  | 'ignore';

export const BLACKBOARD_TAB_META: Record<
  BlackboardTab,
  {
    boundary: BlackboardBoundaryClass;
    authority: BlackboardAuthorityClass;
  }
> = {
  goals: { boundary: HOSTED, authority: NON_AUTHORITATIVE },
  discussion: { boundary: OWNED, authority: AUTHORITATIVE },
  collaboration: { boundary: HOSTED, authority: NON_AUTHORITATIVE },
  members: { boundary: HOSTED, authority: NON_AUTHORITATIVE },
  genes: { boundary: HOSTED, authority: NON_AUTHORITATIVE },
  files: { boundary: OWNED, authority: AUTHORITATIVE },
  status: { boundary: HOSTED, authority: NON_AUTHORITATIVE },
  notes: { boundary: HOSTED, authority: NON_AUTHORITATIVE },
  topology: { boundary: HOSTED, authority: NON_AUTHORITATIVE },
  settings: { boundary: HOSTED, authority: NON_AUTHORITATIVE },
};

export function classifyWorkspaceEventType(type: string): WorkspaceEventChannel {
  if (type.startsWith('workspace.presence.')) {
    return 'presence';
  }
  if (type.startsWith('workspace.agent_status.')) {
    return 'agent_status';
  }
  if (type.startsWith('workspace_task_') || type === 'workspace_task_assigned') {
    return 'task';
  }
  if (type === 'workspace_plan_updated') {
    return 'plan';
  }
  if (type.startsWith('blackboard_')) {
    return 'blackboard';
  }
  if (type === 'workspace_message_created') {
    return 'chat';
  }
  if (type === 'workspace_member_joined' || type === 'workspace_member_left') {
    return 'member';
  }
  if (type === 'workspace_updated' || type === 'workspace_deleted') {
    return 'lifecycle';
  }
  if (type === 'workspace_agent_bound' || type === 'workspace_agent_unbound') {
    return 'agent_binding';
  }
  if (type === 'topology_updated' || type.startsWith('workspace.topology.')) {
    return 'topology';
  }
  return 'ignore';
}

export function isOwnedBlackboardEventData(data: Record<string, unknown>): boolean {
  const boundary = data.surface_boundary;
  const authority = data.authority_class;
  if (boundary === undefined && authority === undefined) {
    return true;
  }
  return boundary === OWNED && authority === AUTHORITATIVE;
}

export function isHostedSensingChatEventData(data: Record<string, unknown>): boolean {
  const boundary = data.surface_boundary;
  const signalRole = data.signal_role;
  if (boundary === undefined && signalRole === undefined) {
    return true;
  }
  return boundary === HOSTED && signalRole === SENSING_CAPABLE;
}
