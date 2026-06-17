import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useMCPAppOpen } from '@/components/agent/timeline/useMCPAppOpen';

import type { TimelineStep } from '@/components/agent/timeline/ExecutionTimeline';

const openTab = vi.fn();
const setActiveTab = vi.fn();
const setMode = vi.fn();
const getHtmlByUri = vi.fn();
const fetchApps = vi.fn();

const mockState = vi.hoisted(() => ({
  tabs: [] as Array<{ id: string; type: string; mcpToolName?: string }>,
  apps: {} as Record<string, unknown>,
  currentProjectId: 'stale-project',
  conversationProjectId: 'conversation-project',
}));

vi.mock('@/stores/canvasStore', () => ({
  useCanvasStore: {
    getState: () => ({
      tabs: mockState.tabs,
      openTab,
      setActiveTab,
    }),
  },
}));

vi.mock('@/stores/layoutMode', () => ({
  useLayoutModeStore: {
    getState: () => ({ setMode }),
  },
}));

vi.mock('@/stores/mcpAppStore', () => ({
  useMCPAppStore: {
    getState: () => ({
      apps: mockState.apps,
      fetchApps,
      getHtmlByUri,
    }),
  },
}));

vi.mock('@/stores/project', () => ({
  useProjectStore: {
    getState: () => ({ currentProject: { id: mockState.currentProjectId } }),
  },
}));

vi.mock('@/stores/agent/conversationsStore', () => ({
  useConversationsStore: {
    getState: () => ({
      currentConversation: { project_id: mockState.conversationProjectId },
    }),
  },
}));

const step = {
  id: 'step-1',
  toolName: 'mcp__charts__render',
  output: { ok: true },
  mcpUiMetadata: {
    resource_uri: 'ui://charts/app.html',
    title: 'Charts',
    server_name: 'charts',
  },
} as TimelineStep;

describe('useMCPAppOpen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.tabs = [];
    mockState.apps = {};
    mockState.currentProjectId = 'stale-project';
    mockState.conversationProjectId = 'conversation-project';
    getHtmlByUri.mockReturnValue(null);
  });

  it('prefers the conversation project over stale global project state', async () => {
    const { result } = renderHook(() => useMCPAppOpen(step));

    await act(async () => {
      await result.current({
        stopPropagation: vi.fn(),
      } as unknown as React.MouseEvent<HTMLButtonElement>);
    });

    expect(openTab).toHaveBeenCalledWith(
      expect.objectContaining({
        mcpProjectId: 'conversation-project',
      })
    );
    expect(setMode).toHaveBeenCalledWith('canvas');
  });

  it('keeps explicit MCP UI project metadata authoritative', async () => {
    const { result } = renderHook(() =>
      useMCPAppOpen({
        ...step,
        mcpUiMetadata: {
          ...step.mcpUiMetadata,
          project_id: 'ui-project',
        },
      } as TimelineStep)
    );

    await act(async () => {
      await result.current({
        stopPropagation: vi.fn(),
      } as unknown as React.MouseEvent<HTMLButtonElement>);
    });

    expect(openTab).toHaveBeenCalledWith(
      expect.objectContaining({
        mcpProjectId: 'ui-project',
      })
    );
  });
});
