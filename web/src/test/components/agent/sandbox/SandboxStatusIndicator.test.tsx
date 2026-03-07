import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SandboxStatusIndicator } from '../../../../components/agent/sandbox/SandboxStatusIndicator';
import {
  projectSandboxService,
  type ProjectSandbox,
} from '../../../../services/projectSandboxService';
import {
  sandboxSSEService,
  type BaseSandboxSSEEvent,
  type SandboxEventHandler,
} from '../../../../services/sandboxSSEService';
import type { SandboxStateData } from '../../../../types/agent';

vi.mock('../../../../services/projectSandboxService', () => ({
  projectSandboxService: {
    getProjectSandbox: vi.fn(),
    getStats: vi.fn(),
    ensureSandbox: vi.fn(),
    restartSandbox: vi.fn(),
    terminateSandbox: vi.fn(),
  },
}));

vi.mock('../../../../services/sandboxSSEService', () => ({
  sandboxSSEService: {
    subscribe: vi.fn(),
  },
}));

describe('SandboxStatusIndicator', () => {
  let latestHandler: SandboxEventHandler | null = null;

  const sandboxInfo: ProjectSandbox = {
    sandbox_id: 'sb-1',
    project_id: 'proj-1',
    tenant_id: 'tenant-1',
    status: 'running',
    is_healthy: true,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    latestHandler = null;
    vi.mocked(projectSandboxService.getProjectSandbox).mockResolvedValue(sandboxInfo);
    vi.mocked(projectSandboxService.getStats).mockResolvedValue({
      project_id: 'proj-1',
      sandbox_id: 'sb-1',
      status: 'running',
      cpu_percent: 0,
      memory_usage: 0,
      memory_limit: 1,
      memory_percent: 0,
      pids: 1,
      collected_at: new Date().toISOString(),
    });
    vi.mocked(sandboxSSEService.subscribe).mockImplementation(
      (_projectId: string, handler: SandboxEventHandler) => {
        latestHandler = handler;
        return vi.fn();
      }
    );
  });

  it('does not refetch sandbox for high-frequency terminal/desktop websocket events', async () => {
    render(<SandboxStatusIndicator projectId="proj-1" tenantId="tenant-1" />);

    await waitFor(() => {
      expect(projectSandboxService.getProjectSandbox).toHaveBeenCalledTimes(1);
      expect(sandboxSSEService.subscribe).toHaveBeenCalledTimes(1);
      expect(latestHandler).not.toBeNull();
    });

    act(() => {
      for (let i = 0; i < 20; i += 1) {
        const event: BaseSandboxSSEEvent = {
          type: i % 2 === 0 ? 'terminal_status' : 'desktop_status',
          data: {
            eventType: i % 2 === 0 ? 'terminal_status' : 'desktop_status',
            sandboxId: 'sb-1',
            status: null,
            isHealthy: true,
          } satisfies SandboxStateData,
          timestamp: new Date().toISOString(),
        };
        latestHandler?.onStatusUpdate?.(event);
      }
    });

    await waitFor(() => {
      expect(projectSandboxService.getProjectSandbox).toHaveBeenCalledTimes(1);
    });
  });

  it('fetches the new project immediately and ignores stale in-flight responses', async () => {
    let resolveProj1: ((value: ProjectSandbox | null) => void) | undefined;
    let resolveProj2: ((value: ProjectSandbox | null) => void) | undefined;

    const proj1Promise = new Promise<ProjectSandbox | null>((resolve) => {
      resolveProj1 = resolve;
    });
    const proj2Promise = new Promise<ProjectSandbox | null>((resolve) => {
      resolveProj2 = resolve;
    });

    vi.mocked(projectSandboxService.getProjectSandbox).mockImplementation((projectId: string) => {
      if (projectId === 'proj-1') {
        return proj1Promise;
      }
      if (projectId === 'proj-2') {
        return proj2Promise;
      }
      return Promise.resolve(null);
    });

    const { rerender } = render(<SandboxStatusIndicator projectId="proj-1" tenantId="tenant-1" />);

    await waitFor(() => {
      expect(projectSandboxService.getProjectSandbox).toHaveBeenCalledWith(
        'proj-1',
        expect.any(Object)
      );
    });

    rerender(<SandboxStatusIndicator projectId="proj-2" tenantId="tenant-1" />);

    await waitFor(() => {
      expect(projectSandboxService.getProjectSandbox).toHaveBeenCalledWith(
        'proj-2',
        expect.any(Object)
      );
    });

    await act(async () => {
      resolveProj1?.({
        sandbox_id: 'sb-old',
        project_id: 'proj-1',
        tenant_id: 'tenant-1',
        status: 'running',
        is_healthy: true,
      });
      await Promise.resolve();
    });

    expect(screen.queryByText('运行中')).not.toBeInTheDocument();

    await act(async () => {
      resolveProj2?.({
        sandbox_id: 'sb-new',
        project_id: 'proj-2',
        tenant_id: 'tenant-1',
        status: 'running',
        is_healthy: true,
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText('运行中')).toBeInTheDocument();
    });

    expect(latestHandler).not.toBeNull();
  });

  it('aborts the previous sandbox request when switching project', async () => {
    let resolveProj1: ((value: ProjectSandbox | null) => void) | undefined;
    let resolveProj2: ((value: ProjectSandbox | null) => void) | undefined;
    const capturedSignals = new Map<string, AbortSignal | undefined>();

    const proj1Promise = new Promise<ProjectSandbox | null>((resolve) => {
      resolveProj1 = resolve;
    });
    const proj2Promise = new Promise<ProjectSandbox | null>((resolve) => {
      resolveProj2 = resolve;
    });

    vi.mocked(projectSandboxService.getProjectSandbox).mockImplementation(
      (projectId: string, options?: { signal?: AbortSignal }) => {
        capturedSignals.set(projectId, options?.signal);
        if (projectId === 'proj-1') {
          return proj1Promise;
        }
        if (projectId === 'proj-2') {
          return proj2Promise;
        }
        return Promise.resolve(null);
      }
    );

    const { rerender } = render(<SandboxStatusIndicator projectId="proj-1" tenantId="tenant-1" />);

    await waitFor(() => {
      expect(capturedSignals.get('proj-1')).toBeDefined();
    });
    expect(capturedSignals.get('proj-1')?.aborted).toBe(false);

    rerender(<SandboxStatusIndicator projectId="proj-2" tenantId="tenant-1" />);

    await waitFor(() => {
      expect(capturedSignals.get('proj-2')).toBeDefined();
    });
    await waitFor(() => {
      expect(capturedSignals.get('proj-1')?.aborted).toBe(true);
    });
    expect(capturedSignals.get('proj-2')?.aborted).toBe(false);

    await act(async () => {
      resolveProj1?.(null);
      resolveProj2?.(null);
      await Promise.resolve();
    });
  });

  it('does not refetch sandbox for unknown websocket event types', async () => {
    render(<SandboxStatusIndicator projectId="proj-1" tenantId="tenant-1" />);

    await waitFor(() => {
      expect(projectSandboxService.getProjectSandbox).toHaveBeenCalledTimes(1);
      expect(latestHandler).not.toBeNull();
    });

    act(() => {
      const event: BaseSandboxSSEEvent = {
        type: 'sandbox_status',
        data: {
          eventType: 'sandbox_heartbeat',
          sandboxId: 'sb-1',
          status: null,
          isHealthy: true,
        } satisfies SandboxStateData,
        timestamp: new Date().toISOString(),
      };
      latestHandler?.onStatusUpdate?.(event);
    });

    await waitFor(() => {
      expect(projectSandboxService.getProjectSandbox).toHaveBeenCalledTimes(1);
    });
  });
});
