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

    expect(mockListConversations).toHaveBeenCalledWith('project-1', undefined, 20, 0, undefined);
    expect(set).toHaveBeenLastCalledWith({
      conversations: [conversation('new-conversation', 'project-1')],
      hasMoreConversations: false,
      conversationsTotal: 1,
    });
  });
});
