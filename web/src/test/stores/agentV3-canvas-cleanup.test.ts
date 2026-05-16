import { act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '../../services/agentService';
import { useAgentV3Store } from '../../stores/agentV3';
import { useCanvasStore } from '../../stores/canvasStore';
import { useLayoutModeStore } from '../../stores/layoutMode';
import { createDefaultConversationState } from '../../types/conversationState';

import type { CanvasUpdatedTimelineEvent, Conversation } from '../../types/agent';

vi.mock('../../services/agentService', () => ({
  agentService: {
    createConversation: vi.fn(),
  },
}));

vi.mock('../../utils/conversationDB', () => ({
  saveConversationState: vi.fn(() => Promise.resolve()),
  loadConversationState: vi.fn(() => Promise.resolve(null)),
  deleteConversationState: vi.fn(() => Promise.resolve()),
}));

function makeConversation(id: string, projectId = 'proj-1'): Conversation {
  return {
    id,
    project_id: projectId,
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    title: 'New Conversation',
    status: 'active',
    message_count: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

describe('agentV3 canvas tab cleanup by conversation scope', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    useCanvasStore.getState().reset();
    useLayoutModeStore.getState().setMode('chat');

    useAgentV3Store.setState({
      conversations: [],
      activeConversationId: null,
      conversationStates: new Map(),
      timeline: [],
      messages: [],
      hasEarlier: false,
      earliestTimeUs: null,
      earliestCounter: null,
      isStreaming: false,
      streamStatus: 'idle',
      streamingAssistantContent: '',
      error: null,
      agentState: 'idle',
      currentThought: '',
      streamingThought: '',
      isThinkingStreaming: false,
      activeToolCalls: new Map(),
      pendingToolsStack: [],
      isPlanMode: false,
      pendingClarification: null,
      pendingDecision: null,
      pendingEnvVarRequest: null,
      doomLoopDetected: null,
      pinnedEventIds: new Set(),
    });
  });

  it('clears stale canvas tabs when creating a new conversation', async () => {
    useCanvasStore.getState().openTab({
      id: 'old-tab',
      title: 'Old tab',
      type: 'code',
      content: 'print("stale")',
    });
    useLayoutModeStore.getState().setMode('canvas');

    vi.mocked(agentService.createConversation).mockResolvedValue(makeConversation('conv-new'));

    await act(async () => {
      await useAgentV3Store.getState().createNewConversation('proj-1');
    });

    expect(useCanvasStore.getState().tabs).toHaveLength(0);
    expect(useLayoutModeStore.getState().mode).toBe('chat');
    expect(useAgentV3Store.getState().activeConversationId).toBe('conv-new');
  });

  it('marks creation in progress until the new conversation shell is ready', async () => {
    let resolveCreate: ((value: Conversation) => void) | undefined;

    vi.mocked(agentService.createConversation).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        })
    );

    const createPromise = useAgentV3Store.getState().createNewConversation('proj-1');
    await act(async () => {
      await Promise.resolve();
    });

    expect(useAgentV3Store.getState().isCreatingConversation).toBe(true);

    resolveCreate?.(makeConversation('conv-pending'));

    await act(async () => {
      await createPromise;
    });

    expect(useAgentV3Store.getState().isCreatingConversation).toBe(false);
    expect(useAgentV3Store.getState().activeConversationId).toBe('conv-pending');
  });

  it('clears old tabs then replays only the target conversation canvas timeline', () => {
    useCanvasStore.getState().openTab({
      id: 'old-tab',
      title: 'Old tab',
      type: 'code',
      content: 'print("old")',
    });

    const canvasEvent: CanvasUpdatedTimelineEvent = {
      id: 'canvas-event-1',
      type: 'canvas_updated',
      eventTimeUs: 1_000_000,
      eventCounter: 1,
      timestamp: Date.now(),
      action: 'created',
      block_id: 'block-new',
      block: {
        id: 'block-new',
        block_type: 'markdown',
        title: 'Current conversation tab',
        content: '# hello',
      },
    };

    const targetConversationState = createDefaultConversationState();
    targetConversationState.timeline = [canvasEvent];

    useAgentV3Store.setState({
      activeConversationId: 'conv-old',
      conversationStates: new Map([['conv-target', targetConversationState]]),
    });

    act(() => {
      useAgentV3Store.getState().setActiveConversation('conv-target');
    });

    const tabs = useCanvasStore.getState().tabs;
    expect(tabs).toHaveLength(1);
    expect(tabs[0]?.id).toBe('block-new');
    expect(tabs.some((tab) => tab.id === 'old-tab')).toBe(false);
    expect(useLayoutModeStore.getState().mode).toBe('canvas');
  });
});
