import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const listConversations = vi.fn();

vi.mock('@/services/agentService', () => ({
  agentService: {
    listConversations: (...args: unknown[]) => listConversations(...args),
  },
}));

import { useWorkspaceConversations } from '@/hooks/useWorkspaceConversations';

import type { Conversation } from '@/types/agent/core';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function conversation(id: string, workspaceId: string): Conversation {
  return {
    id,
    title: id,
    workspace_id: workspaceId,
  } as Conversation;
}

describe('useWorkspaceConversations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('ignores stale errors after the active workspace changes', async () => {
    const staleRequest = deferred<{
      items: Conversation[];
      has_more: boolean;
    }>();
    const activeRequest = deferred<{
      items: Conversation[];
      has_more: boolean;
    }>();
    listConversations
      .mockReturnValueOnce(staleRequest.promise)
      .mockReturnValueOnce(activeRequest.promise);

    const { result, rerender } = renderHook(
      ({ projectId, workspaceId }) => useWorkspaceConversations(projectId, workspaceId),
      {
        initialProps: { projectId: 'project-1', workspaceId: 'workspace-1' },
      }
    );

    await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(1));

    rerender({ projectId: 'project-1', workspaceId: 'workspace-2' });

    await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(2));

    await act(async () => {
      activeRequest.resolve({
        items: [conversation('conversation-2', 'workspace-2')],
        has_more: false,
      });
      await activeRequest.promise;
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.conversations.map((item) => item.id)).toEqual(['conversation-2']);
    });

    await act(async () => {
      staleRequest.reject(new Error('stale workspace failed'));
      await staleRequest.promise.catch(() => undefined);
    });

    expect(result.current.error).toBeNull();
    expect(result.current.conversations.map((item) => item.id)).toEqual(['conversation-2']);
  });

  it('clears stale state when the workspace context becomes unavailable', async () => {
    listConversations.mockResolvedValue({
      items: [conversation('conversation-1', 'workspace-1')],
      has_more: false,
    });
    const { result, rerender } = renderHook(
      ({ workspaceId }) => useWorkspaceConversations('project-1', workspaceId),
      {
        initialProps: { workspaceId: 'workspace-1' as string | null },
      }
    );

    await waitFor(() => {
      expect(result.current.conversations.map((item) => item.id)).toEqual(['conversation-1']);
    });

    rerender({ workspaceId: null });

    await waitFor(() => {
      expect(result.current.conversations).toEqual([]);
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });
  });

  it('clears stale conversations while loading a different workspace', async () => {
    const nextWorkspaceRequest = deferred<{
      items: Conversation[];
      has_more: boolean;
    }>();
    listConversations
      .mockResolvedValueOnce({
        items: [conversation('conversation-1', 'workspace-1')],
        has_more: false,
      })
      .mockReturnValueOnce(nextWorkspaceRequest.promise);

    const { result, rerender } = renderHook(
      ({ workspaceId }) => useWorkspaceConversations('project-1', workspaceId),
      {
        initialProps: { workspaceId: 'workspace-1' },
      }
    );

    await waitFor(() => {
      expect(result.current.conversations.map((item) => item.id)).toEqual(['conversation-1']);
    });

    rerender({ workspaceId: 'workspace-2' });

    await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(2));

    expect(result.current.loading).toBe(true);
    expect(result.current.conversations).toEqual([]);

    await act(async () => {
      nextWorkspaceRequest.resolve({
        items: [conversation('conversation-2', 'workspace-2')],
        has_more: false,
      });
      await nextWorkspaceRequest.promise;
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.conversations.map((item) => item.id)).toEqual(['conversation-2']);
    });
  });
});
