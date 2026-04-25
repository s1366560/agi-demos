import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const handlers = {
  handlePresenceEvent: vi.fn(),
  handleAgentStatusEvent: vi.fn(),
  handleTaskEvent: vi.fn(),
  handlePlanEvent: vi.fn(),
  handleBlackboardEvent: vi.fn(),
  handleChatEvent: vi.fn(),
  handleMemberEvent: vi.fn(),
  handleWorkspaceLifecycleEvent: vi.fn(),
  handleAgentBindingEvent: vi.fn(),
  handleTopologyEvent: vi.fn(),
};

const subscribeWorkspace = vi.fn();

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: {
    getState: () => handlers,
  },
}));

vi.mock('@/services/unifiedEventService', () => ({
  unifiedEventService: {
    subscribeWorkspace: (...args: unknown[]) => subscribeWorkspace(...args),
  },
}));

import { useBlackboardSSE } from '@/hooks/useBlackboardSSE';
import { classifyWorkspaceEventType } from '@/components/blackboard/blackboardSurfaceContract';

function HookHarness({ workspaceId }: { workspaceId: string | null }) {
  useBlackboardSSE(workspaceId);
  return null;
}

describe('useBlackboardSSE', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('classifies workspace event channels explicitly', () => {
    expect(classifyWorkspaceEventType('workspace.presence.joined')).toBe('presence');
    expect(classifyWorkspaceEventType('workspace.agent_status.updated')).toBe('agent_status');
    expect(classifyWorkspaceEventType('workspace_task_updated')).toBe('task');
    expect(classifyWorkspaceEventType('workspace_plan_updated')).toBe('plan');
    expect(classifyWorkspaceEventType('blackboard_post_created')).toBe('blackboard');
    expect(classifyWorkspaceEventType('workspace_message_created')).toBe('chat');
    expect(classifyWorkspaceEventType('workspace_member_joined')).toBe('member');
    expect(classifyWorkspaceEventType('workspace_updated')).toBe('lifecycle');
    expect(classifyWorkspaceEventType('workspace_agent_bound')).toBe('agent_binding');
    expect(classifyWorkspaceEventType('workspace.topology.agent_moved')).toBe('topology');
    expect(classifyWorkspaceEventType('unknown_event')).toBe('ignore');
  });

  it('routes subscribed events to the correct workspace handlers', () => {
    const unsubscribe = vi.fn();
    let callback: ((event: { type: string; data: Record<string, unknown> }) => void) | null = null;
    subscribeWorkspace.mockImplementation((_workspaceId: string, cb: typeof callback) => {
      callback = cb;
      return unsubscribe;
    });

    const { unmount } = render(<HookHarness workspaceId="ws-1" />);

    expect(subscribeWorkspace).toHaveBeenCalledWith('ws-1', expect.any(Function));
    callback?.({ type: 'blackboard_post_created', data: { post: { id: 'post-1' } } });
    callback?.({ type: 'workspace_message_created', data: { id: 'msg-1' } });
    callback?.({ type: 'workspace.presence.joined', data: { user_id: 'u-1' } });
    callback?.({ type: 'topology_updated', data: { node_id: 'n-1' } });
    callback?.({ type: 'workspace_plan_updated', data: { workspace_id: 'ws-1' } });
    callback?.({ type: 'unknown_event', data: {} });

    expect(handlers.handleBlackboardEvent).toHaveBeenCalledWith({
      type: 'blackboard_post_created',
      data: { post: { id: 'post-1' } },
    });
    expect(handlers.handleChatEvent).toHaveBeenCalledWith({
      type: 'workspace_message_created',
      data: { id: 'msg-1' },
    });
    expect(handlers.handlePresenceEvent).toHaveBeenCalledWith({
      type: 'workspace.presence.joined',
      data: { user_id: 'u-1' },
    });
    expect(handlers.handleTopologyEvent).toHaveBeenCalledWith({
      type: 'topology_updated',
      data: { node_id: 'n-1' },
    });
    expect(handlers.handlePlanEvent).toHaveBeenCalledWith({
      type: 'workspace_plan_updated',
      data: { workspace_id: 'ws-1' },
    });
    expect(handlers.handleMemberEvent).not.toHaveBeenCalled();

    unmount();
    expect(unsubscribe).toHaveBeenCalled();
  });
});
