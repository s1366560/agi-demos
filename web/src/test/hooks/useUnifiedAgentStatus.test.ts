/**
 * Tests for useUnifiedAgentStatus hook
 *
 * TDD: Red-Green-Refactor
 * 1. RED: Write failing tests first
 * 2. GREEN: Implement minimal code to pass tests
 * 3. REFACTOR: Improve implementation
 */

import { renderHook, cleanup } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { useAgentLifecycleState } from '../../hooks/useAgentLifecycleState';
// eslint-disable-next-line import/order
import {
  useUnifiedAgentStatus,
  type ProjectAgentLifecycleState,
} from '../../hooks/useUnifiedAgentStatus';
// Mock stores
vi.mock('../../stores/agentV3', () => ({
  useAgentV3Store: vi.fn(),
}));

vi.mock('../../stores/agent/streamingStore', () => ({
  useStreamingStore: vi.fn(),
}));

vi.mock('../../stores/sandbox', () => ({
  useSandboxStore: vi.fn(),
}));

// Mock useAgentLifecycleState hook
vi.mock('../../hooks/useAgentLifecycleState', () => ({
  useAgentLifecycleState: vi.fn(),
}));

import { useStreamingStore } from '../../stores/agent/streamingStore';
import { useAgentV3Store } from '../../stores/agentV3';
import { useSandboxStore } from '../../stores/sandbox';

import type { LifecycleStateData } from '../../types/agent';

describe('useUnifiedAgentStatus - TDD RED Phase', () => {
  const mockProjectId = 'test-project-123';
  const mockTenantId = 'test-tenant-456';

  // Default mock states
  const defaultAgentV3State = {
    agentState: 'idle' as const,
    isStreaming: false,
    activeToolCalls: new Map(),
    timeline: [],
  };

  const defaultStreamingState = {
    isStreaming: false,
    streamStatus: 'idle' as const,
  };

  const defaultSandboxState = {
    activeSandboxId: null,
  };

  const defaultLifecycleState: LifecycleStateData = {
    lifecycleState: 'ready',
    isInitialized: true,
    isActive: true,
    toolCount: 25,
    builtinToolCount: 10,
    mcpToolCount: 15,
    skillCount: 5,
    totalSkillCount: 10,
    loadedSkillCount: 5,
    subagentCount: 3,
  };

  const setupMocks = (lifecycleState: LifecycleStateData | null = defaultLifecycleState) => {
    vi.mocked(useAgentV3Store).mockImplementation((selector) => {
      const state = defaultAgentV3State;
      return selector(state);
    });

    vi.mocked(useStreamingStore).mockImplementation((selector) => {
      const state = defaultStreamingState;
      return selector(state);
    });

    vi.mocked(useSandboxStore).mockImplementation((selector) => {
      const state = defaultSandboxState;
      return selector(state);
    });

    vi.mocked(useAgentLifecycleState).mockReturnValue({
      lifecycleState,
      isConnected: true,
      error: null,
      status: {
        label: 'Ready',
        color: 'text-emerald-500',
        icon: 'CheckCircle',
        description: 'Agent ready',
      },
    });
  };

  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  afterEach(() => {
    cleanup();
  });

  describe('Unified Status Interface', () => {
    it('should return unified status structure with all required fields', () => {
      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      expect(result.current.status).toBeDefined();
      expect(result.current.status.lifecycle).toBeDefined();
      expect(result.current.status.planMode).toBeDefined();
      expect(result.current.status.resources).toBeDefined();
      expect(result.current.status.toolStats).toBeDefined();
      expect(result.current.status.skillStats).toBeDefined();
      expect(result.current.status.connection).toBeDefined();
    });

    it('should have correct types for all status properties', () => {
      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      // Lifecycle should be one of the valid states
      const validLifecycleStates: ProjectAgentLifecycleState[] = [
        'uninitialized',
        'initializing',
        'ready',
        'executing',
        'paused',
        'error',
        'shutting_down',
      ];
      expect(validLifecycleStates).toContain(result.current.status.lifecycle);

      // Plan mode should be an object
      expect(result.current.status.planMode).toEqual(
        expect.objectContaining({
          isActive: expect.any(Boolean),
        })
      );

      // Resources should have counts (legacy)
      expect(result.current.status.resources).toEqual(
        expect.objectContaining({
          tools: expect.any(Number),
          activeCalls: expect.any(Number),
          messages: expect.any(Number),
        })
      );

      // Tool stats should have detailed breakdown
      expect(result.current.status.toolStats).toEqual(
        expect.objectContaining({
          total: expect.any(Number),
          builtin: expect.any(Number),
          mcp: expect.any(Number),
        })
      );

      // Skill stats should have detailed breakdown
      expect(result.current.status.skillStats).toEqual(
        expect.objectContaining({
          total: expect.any(Number),
          loaded: expect.any(Number),
        })
      );

      // Connection should have boolean flags
      expect(result.current.status.connection).toEqual(
        expect.objectContaining({
          websocket: expect.any(Boolean),
          sandbox: expect.any(Boolean),
        })
      );
    });
  });

  describe('Status Priority Rules', () => {
    it('should use lifecycle state from useAgentLifecycleState', () => {
      const errorLifecycleState: LifecycleStateData = {
        lifecycleState: 'error',
        isInitialized: false,
        isActive: false,
        errorMessage: 'Something went wrong',
      };

      setupMocks(errorLifecycleState);

      // Agent store shows 'idle' state (lower priority)
      vi.mocked(useAgentV3Store).mockImplementation((selector) => {
        const state = { ...defaultAgentV3State, agentState: 'thinking' as const };
        return selector(state);
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      // Lifecycle should show 'error' despite agent store showing 'thinking'
      expect(result.current.status.lifecycle).toBe('error');
    });

    it('should derive lifecycle from lifecycleState when provided', () => {
      const executingLifecycleState: LifecycleStateData = {
        lifecycleState: 'executing',
        isInitialized: true,
        isActive: true,
      };

      setupMocks(executingLifecycleState);

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      expect(result.current.status.lifecycle).toBe('executing');
    });

    it('should show "uninitialized" when no lifecycle state available', () => {
      setupMocks(null);

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      expect(result.current.status.lifecycle).toBe('uninitialized');
    });

    it('should derive lifecycle state from flags when lifecycleState is null', () => {
      const lifecycleStateWithoutState: LifecycleStateData = {
        lifecycleState: null,
        isInitialized: true,
        isActive: true,
      };

      setupMocks(lifecycleStateWithoutState);

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      expect(result.current.status.lifecycle).toBe('ready');
    });
  });

  describe('Resource Counts', () => {
    it('should aggregate tool count from lifecycle state', () => {
      const lifecycleStateWithCounts: LifecycleStateData = {
        lifecycleState: 'ready',
        isInitialized: true,
        isActive: true,
        toolCount: 42,
        builtinToolCount: 20,
        mcpToolCount: 22,
        skillCount: 8,
        totalSkillCount: 10,
        loadedSkillCount: 8,
        subagentCount: 4,
      };

      setupMocks(lifecycleStateWithCounts);

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      // Legacy resources
      expect(result.current.status.resources.tools).toBe(42);
      expect(result.current.status.resources.skills).toBe(8);

      // New detailed stats
      expect(result.current.status.toolStats.total).toBe(42);
      expect(result.current.status.toolStats.builtin).toBe(20);
      expect(result.current.status.toolStats.mcp).toBe(22);
      expect(result.current.status.skillStats.total).toBe(10);
      expect(result.current.status.skillStats.loaded).toBe(8);
    });

    it('should count active tool calls from agent store', () => {
      const _activeToolCalls = new Map([
        ['read', { status: 'running', startTime: Date.now() }],
        ['write', { status: 'running', startTime: Date.now() }],
      ]);

      vi.mocked(useAgentV3Store).mockImplementation((selector) => {
        const state = { ...defaultAgentV3StateiveToolCalls };
        return selector(state);
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.status.resources.activeCalls).toBe(2);
    });

    it('should default to zero when no lifecycle state available', () => {
      setupMocks(null);

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.status.resources.tools).toBe(0);
      expect(result.current.status.resources.skills).toBe(0);
      expect(result.current.status.toolStats.total).toBe(0);
      expect(result.current.status.toolStats.builtin).toBe(0);
      expect(result.current.status.toolStats.mcp).toBe(0);
      expect(result.current.status.skillStats.total).toBe(0);
      expect(result.current.status.skillStats.loaded).toBe(0);
    });
  });

  describe('Connection Status', () => {
    it('should show sandbox connected when activeSandboxId exists', () => {
      vi.mocked(useSandboxStore).mockImplementation((selector) => {
        const state = {
          ...defaultSandboxState,
          activeSandboxId: 'sandbox-123',
        };
        return selector(state);
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.status.connection.sandbox).toBe(true);
    });

    it('should show sandbox disconnected when no active sandbox', () => {
      vi.mocked(useSandboxStore).mockImplementation((selector) => {
        const state = {
          ...defaultSandboxState,
          activeSandboxId: null,
        };
        return selector(state);
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.status.connection.sandbox).toBe(false);
    });

    it('should derive WebSocket connection from streaming status', () => {
      vi.mocked(useStreamingStore).mockImplementation((selector) => {
        const state = {
          ...defaultStreamingState,
          streamStatus: 'streaming' as const,
        };
        return selector(state);
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.status.connection.websocket).toBe(true);
    });
  });

  describe('Loading and Error States', () => {
    it('should pass through isLoading from useAgentLifecycleState', () => {
      vi.mocked(useAgentLifecycleState).mockReturnValue({
        lifecycleState: defaultLifecycleState,
        isConnected: true,
        error: null,
        status: {
          label: 'Ready',
          color: 'text-emerald-500',
          icon: 'CheckCircle',
          description: 'Agent ready',
        },
        isLoading: true,
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      expect(result.current.isLoading).toBe(true);
    });

    it('should pass through error from useAgentLifecycleState', () => {
      const errorMessage = 'Connection failed';
      vi.mocked(useAgentLifecycleState).mockReturnValue({
        lifecycleState: null,
        isConnected: false,
        error: errorMessage,
        status: {
          label: 'Unknown',
          color: 'text-gray-500',
          icon: 'HelpCircle',
          description: 'Agent state unknown',
        },
        isLoading: false,
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      expect(result.current.error).toBe(errorMessage);
      expect(result.current.status.lifecycle).toBe('uninitialized');
    });
  });

  describe('Agent State Integration', () => {
    it('should include agent state from agentV3 store', () => {
      vi.mocked(useAgentV3Store).mockImplementation((selector) => {
        const state = { ...defaultAgentV3State, agentState: 'acting' as const };
        return selector(state);
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.status.agentState).toBe('acting');
    });

    it('should default to idle when agent state not available', () => {
      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.status.agentState).toBe('idle');
    });

    it('should map agent states correctly', () => {
      const agentStates = ['idle', 'thinking', 'acting', 'observing', 'awaiting_input'] as const;

      for (const agentState of agentStates) {
        vi.mocked(useAgentV3Store).mockImplementation((selector) => {
          const state = { ...defaultAgentV3State, agentState };
          return selector(state);
        });

        const { result } = renderHook(() =>
          useUnifiedAgentStatus({
            projectId: mockProjectId,
            tenantId: mockTenantId,
            enabled: false,
          })
        );

        expect(result.current.status.agentState).toBe(agentState);
      }
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty projectId gracefully', () => {
      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: '', tenantId: mockTenantId, enabled: true })
      );

      expect(result.current.status.lifecycle).toBe('uninitialized');
      expect(result.current.isLoading).toBe(false);
    });

    it('should handle undefined projectId gracefully', () => {
      const { result } = renderHook(() =>
        useUnifiedAgentStatus({
          projectId: undefined as unknown as string,
          tenantId: mockTenantId,
          enabled: true,
        })
      );

      expect(result.current.status.lifecycle).toBe('uninitialized');
    });

    it('should handle missing optional fields in lifecycle state', () => {
      const lifecycleStateWithoutOptionals: LifecycleStateData = {
        lifecycleState: 'ready',
        isInitialized: true,
        isActive: true,
        // Missing optional fields: toolCount, skillCount, subagentCount, etc.
      };

      setupMocks(lifecycleStateWithoutOptionals);

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: true })
      );

      expect(result.current.status.resources.tools).toBe(0);
      expect(result.current.status.resources.skills).toBe(0);
      expect(result.current.status.toolStats.total).toBe(0);
      expect(result.current.status.toolStats.builtin).toBe(0);
      expect(result.current.status.toolStats.mcp).toBe(0);
      expect(result.current.status.skillStats.total).toBe(0);
      expect(result.current.status.skillStats.loaded).toBe(0);
    });
  });

  describe('Streaming Status Integration', () => {
    it('should reflect streaming status from streamingStore', () => {
      vi.mocked(useAgentV3Store).mockImplementation((selector) => {
        const state = {
          ...defaultAgentV3State,
          isStreaming: true,
        };
        return selector(state);
      });

      vi.mocked(useStreamingStore).mockImplementation((selector) => {
        const state = {
          ...defaultStreamingState,
          isStreaming: true,
          streamStatus: 'streaming' as const,
        };
        return selector(state);
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.isStreaming).toBe(true);
    });

    it('should derive agent state from streaming when active', () => {
      vi.mocked(useAgentV3Store).mockImplementation((selector) => {
        const state = {
          ...defaultAgentV3State,
          agentState: 'thinking' as const,
          isStreaming: true,
        };
        return selector(state);
      });

      vi.mocked(useStreamingStore).mockImplementation((selector) => {
        const state = {
          ...defaultStreamingState,
          isStreaming: true,
          streamStatus: 'streaming' as const,
        };
        return selector(state);
      });

      const { result } = renderHook(() =>
        useUnifiedAgentStatus({ projectId: mockProjectId, tenantId: mockTenantId, enabled: false })
      );

      expect(result.current.isStreaming).toBe(true);
      expect(result.current.status.agentState).toBe('thinking');
    });
  });
});
