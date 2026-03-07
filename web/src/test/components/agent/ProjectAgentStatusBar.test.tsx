import React from 'react';

import { render, act, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useUnifiedAgentStatus } from '../../../hooks/useUnifiedAgentStatus';
import { poolService, type PoolStatus } from '../../../services/poolService';
import { useAgentV3Store } from '../../../stores/agentV3';
import { ProjectAgentStatusBar } from '../../../components/agent/ProjectAgentStatusBar';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock('../../../hooks/useUnifiedAgentStatus', () => ({
  useUnifiedAgentStatus: vi.fn(),
}));

vi.mock('../../../stores/agentV3', () => ({
  useAgentV3Store: vi.fn(),
}));

vi.mock('../../../services/poolService', () => ({
  poolService: {
    getStatus: vi.fn(),
    listInstances: vi.fn(),
    terminateInstance: vi.fn(),
    pauseInstance: vi.fn(),
    resumeInstance: vi.fn(),
  },
}));

vi.mock('../../../services/agentService', () => ({
  agentService: {
    stopAgent: vi.fn(),
    restartAgent: vi.fn(),
  },
}));

vi.mock('../../../components/agent/sandbox/SandboxStatusIndicator', () => ({
  SandboxStatusIndicator: () => <div data-testid="sandbox-indicator">sandbox</div>,
}));

vi.mock('../../../components/agent/context/ContextStatusIndicator', () => ({
  ContextStatusIndicator: () => <div data-testid="context-indicator">context</div>,
}));

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const mockedUseUnifiedAgentStatus = vi.mocked(useUnifiedAgentStatus);
const mockedUseAgentV3Store = vi.mocked(useAgentV3Store);
const mockedGetStatus = vi.mocked(poolService.getStatus);
const mockedListInstances = vi.mocked(poolService.listInstances);

describe('ProjectAgentStatusBar polling behavior', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();

    mockedUseUnifiedAgentStatus.mockReturnValue({
      status: {
        lifecycle: 'ready',
        agentState: 'idle',
        planMode: { isActive: false },
        resources: { tools: 0, skills: 0, activeCalls: 0, messages: 0 },
        toolStats: { total: 0, builtin: 0, mcp: 0 },
        skillStats: { total: 0, loaded: 0 },
        connection: { websocket: true, sandbox: true },
      },
      isLoading: false,
      error: null,
      isStreaming: false,
    });

    mockedUseAgentV3Store.mockImplementation(
      (selector: (state: Record<string, unknown>) => unknown) => {
        const state = {
          activeConversationId: 'conv-1',
          conversationStates: new Map([
            [
              'conv-1',
              {
                tasks: [],
                executionPathDecision: null,
                selectionTrace: null,
                policyFiltered: null,
              },
            ],
          ]),
          agentState: 'idle',
          isStreaming: false,
          pendingToolsStack: [],
        };
        return selector(state);
      }
    );
  });

  afterEach(() => {
    cleanup();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('does not start overlapping pool requests when previous poll is still running', async () => {
    const statusDeferred = createDeferred<PoolStatus>();

    mockedGetStatus.mockReturnValue(statusDeferred.promise);
    mockedListInstances.mockResolvedValue({
      instances: [],
      total: 0,
      page: 1,
      page_size: 100,
    });

    render(
      <ProjectAgentStatusBar
        projectId="proj-1"
        tenantId="tenant-1"
        messageCount={0}
        enablePoolManagement
      />
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poolService.getStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });

    // No overlap: still only one call while first request is unresolved
    expect(poolService.getStatus).toHaveBeenCalledTimes(1);

    statusDeferred.resolve({
      enabled: true,
      status: 'ok',
      total_instances: 0,
      hot_instances: 0,
      warm_instances: 0,
      cold_instances: 0,
      ready_instances: 0,
      executing_instances: 0,
      unhealthy_instances: 0,
      prewarm_pool: { l1: 0, l2: 0, l3: 0 },
      resource_usage: {
        total_memory_mb: 0,
        used_memory_mb: 0,
        total_cpu_cores: 0,
        used_cpu_cores: 0,
      },
    });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poolService.listInstances).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });

    await act(async () => {
      await Promise.resolve();
    });
    expect(poolService.getStatus).toHaveBeenCalledTimes(2);
  });

  it('reuses fresh snapshot cache on rapid remount for same project', async () => {
    mockedGetStatus.mockResolvedValue({
      enabled: true,
      status: 'ok',
      total_instances: 0,
      hot_instances: 0,
      warm_instances: 0,
      cold_instances: 0,
      ready_instances: 0,
      executing_instances: 0,
      unhealthy_instances: 0,
      prewarm_pool: { l1: 0, l2: 0, l3: 0 },
      resource_usage: {
        total_memory_mb: 0,
        used_memory_mb: 0,
        total_cpu_cores: 0,
        used_cpu_cores: 0,
      },
    });
    mockedListInstances.mockResolvedValue({
      instances: [],
      total: 0,
      page: 1,
      page_size: 100,
    });

    const firstRender = render(
      <ProjectAgentStatusBar
        projectId="proj-cache-1"
        tenantId="tenant-1"
        messageCount={0}
        enablePoolManagement
      />
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(poolService.getStatus).toHaveBeenCalledTimes(1);

    firstRender.unmount();

    render(
      <ProjectAgentStatusBar
        projectId="proj-cache-1"
        tenantId="tenant-1"
        messageCount={0}
        enablePoolManagement
      />
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    // New mount should use short-lived cache and avoid immediate network refetch.
    expect(poolService.getStatus).toHaveBeenCalledTimes(1);
  });
});
