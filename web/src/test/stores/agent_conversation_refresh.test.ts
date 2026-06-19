import { act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockListConversations = vi.fn();

vi.mock('../../services/agentService', () => ({
  agentService: {
    listConversations: (...args: unknown[]) => mockListConversations(...args),
  },
}));

import { createConversationLifecycleActions } from '../../stores/agent/conversationLifecycleActions';
import { initialState, useConversationsStore } from '../../stores/agent/conversationsStore';

import type { Conversation } from '../../types/agent';
import type { ConversationState } from '../../types/conversationState';

function createDeferred<T>() {
  let resolve: (value: T | PromiseLike<T>) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, resolve, reject };
}

function conversation(id: string, projectId: string): Conversation {
  return {
    id,
    project_id: projectId,
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    title: id,
    status: 'active',
    agent_config: {},
    metadata: {},
    message_count: 0,
    created_at: '2026-05-13T00:00:00Z',
    updated_at: null,
  } as Conversation;
}

describe('conversation lifecycle refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useConversationsStore.setState(initialState);
    mockListConversations.mockResolvedValue({
      items: [conversation('new-conversation', 'project-1')],
      has_more: false,
      total: 1,
    });
  });

  it('keeps same-project loads cached unless force is requested', async () => {
    useConversationsStore.setState({
      conversations: [conversation('old-conversation', 'project-1')],
      conversationListProjectId: 'project-1',
      hasMoreConversations: false,
      conversationsTotal: 1,
    });
    let state = {
      activeConversationId: null,
      conversations: [conversation('old-conversation', 'project-1')],
      conversationStates: new Map<string, ConversationState>(),
      hasMoreConversations: false,
    };
    const set = vi.fn((updates: Partial<typeof state>) => {
      state = { ...state, ...updates };
    });
    const actions = createConversationLifecycleActions({
      get: () => state,
      set,
      resetCanvasForConversationScope: vi.fn(),
    });

    await act(async () => {
      await actions.loadConversations('project-1');
    });

    expect(mockListConversations).not.toHaveBeenCalled();

    await act(async () => {
      await actions.loadConversations('project-1', {
        force: true,
        silent: true,
        limit: 20,
      });
    });

    expect(mockListConversations).toHaveBeenCalledWith('project-1', undefined, 20, 0, undefined, {
      groupByWorkspace: true,
    });
    expect(set).toHaveBeenLastCalledWith({
      conversations: [conversation('new-conversation', 'project-1')],
      hasMoreConversations: false,
      conversationsTotal: 1,
    });
  });

  it('caps implicit forced refreshes for large conversation lists', async () => {
    const existingConversations = Array.from({ length: 80 }, (_, index) =>
      conversation(`conversation-${String(index)}`, 'project-1')
    );
    let state = {
      activeConversationId: null,
      conversations: existingConversations,
      conversationStates: new Map<string, ConversationState>(),
      hasMoreConversations: true,
    };
    const set = vi.fn((updates: Partial<typeof state>) => {
      state = { ...state, ...updates };
    });
    const actions = createConversationLifecycleActions({
      get: () => state,
      set,
      resetCanvasForConversationScope: vi.fn(),
    });

    await act(async () => {
      await actions.loadConversations('project-1', {
        force: true,
        silent: true,
      });
    });

    expect(mockListConversations).toHaveBeenCalledWith('project-1', undefined, 25, 0, undefined, {
      groupByWorkspace: true,
    });
  });

  it('does not rewrite agent state when the cached conversation snapshot already matches', async () => {
    const cachedConversation = conversation('cached-conversation', 'project-1');
    useConversationsStore.setState({
      conversations: [cachedConversation],
      conversationListProjectId: 'project-1',
      hasMoreConversations: false,
      conversationsTotal: 1,
    });
    const state = {
      activeConversationId: null,
      conversations: [cachedConversation],
      conversationStates: new Map<string, ConversationState>(),
      hasMoreConversations: false,
      conversationsTotal: 1,
    };
    const set = vi.fn();
    const actions = createConversationLifecycleActions({
      get: () => state,
      set,
      resetCanvasForConversationScope: vi.fn(),
    });

    await act(async () => {
      await actions.loadConversations('project-1');
    });

    expect(mockListConversations).not.toHaveBeenCalled();
    expect(set).not.toHaveBeenCalled();
  });

  it('reloads when only legacy agent state still has same-project conversations', async () => {
    let state = {
      activeConversationId: null,
      conversations: [conversation('stale-conversation', 'project-1')],
      conversationStates: new Map<string, ConversationState>(),
      hasMoreConversations: false,
    };
    const set = vi.fn((updates: Partial<typeof state>) => {
      state = { ...state, ...updates };
    });
    const actions = createConversationLifecycleActions({
      get: () => state,
      set,
      resetCanvasForConversationScope: vi.fn(),
    });

    await act(async () => {
      await actions.loadConversations('project-1');
    });

    expect(mockListConversations).toHaveBeenCalledWith('project-1', undefined, 10, 0, undefined, {
      groupByWorkspace: true,
    });
    expect(set).toHaveBeenLastCalledWith({
      conversations: [conversation('new-conversation', 'project-1')],
      hasMoreConversations: false,
      conversationsTotal: 1,
    });
  });

  it('coalesces concurrent same-project loads before syncing agent state', async () => {
    const response = createDeferred<{
      items: Conversation[];
      has_more: boolean;
      total: number;
    }>();
    mockListConversations.mockReturnValueOnce(response.promise);
    let state = {
      activeConversationId: null,
      conversations: [],
      conversationStates: new Map<string, ConversationState>(),
      hasMoreConversations: false,
    };
    const set = vi.fn((updates: Partial<typeof state>) => {
      state = { ...state, ...updates };
    });
    const actions = createConversationLifecycleActions({
      get: () => state,
      set,
      resetCanvasForConversationScope: vi.fn(),
    });

    const firstLoad = actions.loadConversations('project-1');
    const secondLoad = actions.loadConversations('project-1');

    expect(mockListConversations).toHaveBeenCalledTimes(1);

    await act(async () => {
      response.resolve({
        items: [conversation('new-conversation', 'project-1')],
        has_more: false,
        total: 1,
      });
      await Promise.all([firstLoad, secondLoad]);
    });

    expect(mockListConversations).toHaveBeenCalledTimes(1);
    expect(set).toHaveBeenCalledTimes(1);
    expect(set).toHaveBeenLastCalledWith({
      conversations: [conversation('new-conversation', 'project-1')],
      hasMoreConversations: false,
      conversationsTotal: 1,
    });
  });

  it('caches an empty project conversation list without refetching', async () => {
    mockListConversations.mockResolvedValueOnce({
      items: [],
      has_more: false,
      total: 0,
    });
    let state = {
      activeConversationId: null,
      conversations: [],
      conversationStates: new Map<string, ConversationState>(),
      hasMoreConversations: false,
    };
    const set = vi.fn((updates: Partial<typeof state>) => {
      state = { ...state, ...updates };
    });
    const actions = createConversationLifecycleActions({
      get: () => state,
      set,
      resetCanvasForConversationScope: vi.fn(),
    });

    await act(async () => {
      await actions.loadConversations('project-empty');
      await actions.loadConversations('project-empty');
    });

    expect(mockListConversations).toHaveBeenCalledTimes(1);
    expect(set).toHaveBeenLastCalledWith({
      conversations: [],
      hasMoreConversations: false,
      conversationsTotal: 0,
    });
  });
});
