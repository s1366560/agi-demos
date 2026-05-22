import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  subscribeProject: vi.fn(),
  unsubscribeProject: vi.fn(),
  loadConversations: vi.fn(),
  conversations: [] as Array<{ id: string; project_id?: string }>,
}));

vi.mock('@/services/unifiedEventService', () => ({
  unifiedEventService: {
    subscribeProject: mocks.subscribeProject,
  },
}));

vi.mock('@/stores/agentV3', () => ({
  useAgentV3Store: {
    getState: () => ({
      loadConversations: mocks.loadConversations,
    }),
  },
}));

vi.mock('@/stores/agent/conversationsStore', () => ({
  useConversationsStore: {
    getState: () => ({
      conversations: mocks.conversations,
    }),
  },
}));

vi.mock('@/utils/logger', () => ({
  logger: {
    debug: vi.fn(),
  },
}));

import { useConversationListAutoRefresh } from '@/hooks/useConversationListAutoRefresh';

function projectHandler(): (event: Record<string, unknown>) => void {
  return mocks.subscribeProject.mock.calls[0]?.[1] as (event: Record<string, unknown>) => void;
}

async function flushTimers(ms: number): Promise<void> {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
  });
}

describe('useConversationListAutoRefresh', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.conversations = [];
    mocks.subscribeProject.mockReset();
    mocks.unsubscribeProject.mockReset();
    mocks.loadConversations.mockReset();
    mocks.subscribeProject.mockReturnValue(mocks.unsubscribeProject);
    mocks.loadConversations.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('subscribes to the active project and unsubscribes on unmount', () => {
    const { unmount } = renderHook(() => useConversationListAutoRefresh('project-1'));

    expect(mocks.subscribeProject).toHaveBeenCalledWith('project-1', expect.any(Function));

    unmount();

    expect(mocks.unsubscribeProject).toHaveBeenCalledTimes(1);
  });

  it('debounces conversation_created events and forces a silent refresh', async () => {
    renderHook(() => useConversationListAutoRefresh('project-1'));

    act(() => {
      projectHandler()({
        type: 'conversation_created',
        project_id: 'project-1',
        data: { conversation_id: 'conversation-2', project_id: 'project-1' },
      });
    });

    expect(mocks.loadConversations).not.toHaveBeenCalled();

    await flushTimers(300);

    expect(mocks.loadConversations).toHaveBeenCalledWith(
      'project-1',
      expect.objectContaining({
        force: true,
        silent: true,
        limit: 10,
        signal: expect.any(AbortSignal),
      })
    );
  });

  it('ignores events for other projects', async () => {
    renderHook(() => useConversationListAutoRefresh('project-1'));

    act(() => {
      projectHandler()({
        type: 'conversation_created',
        project_id: 'project-2',
        data: { conversation_id: 'conversation-2', project_id: 'project-2' },
      });
    });

    await flushTimers(300);

    expect(mocks.loadConversations).not.toHaveBeenCalled();
  });

  it('skips refresh when the conversation is already loaded', async () => {
    mocks.conversations = [{ id: 'conversation-1', project_id: 'project-1' }];
    renderHook(() => useConversationListAutoRefresh('project-1'));

    act(() => {
      projectHandler()({
        type: 'conversation_created',
        project_id: 'project-1',
        data: { conversation_id: 'conversation-1', project_id: 'project-1' },
      });
    });

    await flushTimers(300);

    expect(mocks.loadConversations).not.toHaveBeenCalled();
  });

  it('uses the visible-tab polling fallback', async () => {
    const visibilitySpy = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    mocks.conversations = Array.from({ length: 12 }, (_, index) => ({
      id: `conversation-${index}`,
      project_id: 'project-1',
    }));

    renderHook(() => useConversationListAutoRefresh('project-1'));

    await flushTimers(30000);

    expect(mocks.loadConversations).toHaveBeenCalledWith(
      'project-1',
      expect.objectContaining({
        force: true,
        silent: true,
        limit: 12,
      })
    );

    visibilitySpy.mockRestore();
  });

  it('caps auto-refresh requests to the conversations API page limit', async () => {
    const visibilitySpy = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    mocks.conversations = Array.from({ length: 314 }, (_, index) => ({
      id: `conversation-${index}`,
      project_id: 'project-1',
    }));

    renderHook(() => useConversationListAutoRefresh('project-1'));

    await flushTimers(30000);

    expect(mocks.loadConversations).toHaveBeenCalledWith(
      'project-1',
      expect.objectContaining({
        force: true,
        silent: true,
        limit: 100,
      })
    );

    visibilitySpy.mockRestore();
  });

  it('clears pending event refresh timers on unmount', async () => {
    const { unmount } = renderHook(() => useConversationListAutoRefresh('project-1'));

    act(() => {
      projectHandler()({
        type: 'conversation_created',
        project_id: 'project-1',
        data: { conversation_id: 'conversation-2', project_id: 'project-1' },
      });
    });

    unmount();
    await flushTimers(300);

    expect(mocks.loadConversations).not.toHaveBeenCalled();
  });

  it('clears pending event refresh timers when the project changes', async () => {
    const { rerender } = renderHook(({ projectId }) => useConversationListAutoRefresh(projectId), {
      initialProps: { projectId: 'project-1' },
    });

    act(() => {
      projectHandler()({
        type: 'conversation_created',
        project_id: 'project-1',
        data: { conversation_id: 'conversation-2', project_id: 'project-1' },
      });
    });

    rerender({ projectId: 'project-2' });
    await flushTimers(300);

    expect(mocks.unsubscribeProject).toHaveBeenCalledTimes(1);
    expect(mocks.subscribeProject).toHaveBeenLastCalledWith('project-2', expect.any(Function));
    expect(mocks.loadConversations).not.toHaveBeenCalled();
  });
});
