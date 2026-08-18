import { renderHook, act } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const workspaceHandlers = {
  clearPresence: vi.fn(),
  handleAgentBindingEvent: vi.fn(),
  handleAgentStatusEvent: vi.fn(),
  handleBlackboardEvent: vi.fn(),
  handleChatEvent: vi.fn(),
  handleMemberEvent: vi.fn(),
  handlePresenceEvent: vi.fn(),
  handleTaskEvent: vi.fn(),
  handleTopologyEvent: vi.fn(),
  handleWorkspaceLifecycleEvent: vi.fn(),
  setOnlineUsers: vi.fn(),
};

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: {
    getState: () => workspaceHandlers,
  },
}));

const authState = {
  user: null as { name?: string; email?: string } | null,
};

vi.mock('@/stores/auth', () => ({
  useAuthStore: (selector: (state: typeof authState) => unknown) => selector(authState),
}));

import {
  extractOnlineUsersFromPresenceJoinAck,
  resolvePresenceDisplayName,
  useWorkspaceWebSocket,
} from '@/hooks/useWorkspaceWebSocket';

describe('useWorkspaceWebSocket', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('extracts online users from a matching presence join ack', () => {
    expect(
      extractOnlineUsersFromPresenceJoinAck(
        {
          type: 'ack',
          action: 'workspace_presence_join',
          workspace_id: 'ws-1',
          online_users: [
            {
              user_id: 'user-1',
              display_name: 'Ada',
              joined_at: '2026-06-15T02:00:00Z',
              last_heartbeat: '2026-06-15T02:00:01Z',
            },
          ],
        },
        'ws-1'
      )
    ).toEqual([
      {
        user_id: 'user-1',
        display_name: 'Ada',
        joined_at: '2026-06-15T02:00:00Z',
        last_heartbeat: '2026-06-15T02:00:01Z',
      },
    ]);
  });

  it('ignores presence join acks for other workspaces', () => {
    expect(
      extractOnlineUsersFromPresenceJoinAck(
        {
          type: 'ack',
          action: 'workspace_presence_join',
          workspace_id: 'ws-other',
          online_users: [],
        },
        'ws-1'
      )
    ).toBeNull();
  });

  it('hydrates online users from the workspace presence join ack', () => {
    authState.user = { name: 'Ada Lovelace', email: 'ada@example.com' };
    try {
      const sendMessage = vi.fn();
      const { result, unmount } = renderHook(() =>
        useWorkspaceWebSocket({
          workspaceId: 'ws-1',
          sendMessage,
        })
      );

      expect(sendMessage).toHaveBeenCalledWith({
        type: 'subscribe_workspace',
        workspace_id: 'ws-1',
      });
      expect(sendMessage).toHaveBeenCalledWith({
        type: 'workspace_presence_join',
        workspace_id: 'ws-1',
        display_name: 'Ada Lovelace',
      });

      act(() => {
        result.current.handleMessage({
          type: 'ack',
          action: 'workspace_presence_join',
          workspace_id: 'ws-1',
          online_users: [
            {
              user_id: 'user-1',
              display_name: 'Ada',
              joined_at: '2026-06-15T02:00:00Z',
              last_heartbeat: '2026-06-15T02:00:01Z',
            },
          ],
        });
      });

      expect(workspaceHandlers.setOnlineUsers).toHaveBeenCalledWith([
        {
          user_id: 'user-1',
          display_name: 'Ada',
          joined_at: '2026-06-15T02:00:00Z',
          last_heartbeat: '2026-06-15T02:00:01Z',
        },
      ]);

      unmount();
      expect(workspaceHandlers.clearPresence).toHaveBeenCalled();
    } finally {
      authState.user = null;
    }
  });

  it('falls back to the account email when the profile name is blank', () => {
    expect(resolvePresenceDisplayName({ name: '   ', email: 'grace@example.com' })).toBe(
      'grace@example.com'
    );
  });

  it('falls back to "User" when no user is signed in', () => {
    expect(resolvePresenceDisplayName(null)).toBe('User');
    expect(resolvePresenceDisplayName({})).toBe('User');
  });

  it('sends the presence join with the signed-in user name', () => {
    authState.user = { name: 'Alan Turing', email: 'alan@example.com' };
    try {
      const sendMessage = vi.fn();
      const { unmount } = renderHook(() =>
        useWorkspaceWebSocket({ workspaceId: 'ws-1', sendMessage })
      );

      expect(sendMessage).toHaveBeenCalledWith({
        type: 'workspace_presence_join',
        workspace_id: 'ws-1',
        display_name: 'Alan Turing',
      });

      unmount();
    } finally {
      authState.user = null;
    }
  });
});
