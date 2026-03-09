import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { sandboxSSEService } from '../../services/sandboxSSEService';
import { agentService } from '../../services/agentService';

import type { SandboxStateData } from '../../types/agent';

vi.mock('../../utils/logger', () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

let sandboxStateCallback: ((state: SandboxStateData) => void) | null = null;

vi.mock('../../services/agentService', () => ({
  agentService: {
    isConnected: vi.fn(),
    connect: vi.fn(),
    subscribeSandboxState: vi.fn(
      (_projectId: string, _tenantId: string, callback: (state: SandboxStateData) => void) => {
        sandboxStateCallback = callback;
      }
    ),
    unsubscribeSandboxState: vi.fn(),
  },
}));

describe('sandboxSSEService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sandboxStateCallback = null;
    vi.mocked(agentService.isConnected).mockReturnValue(false);
    vi.mocked(agentService.connect).mockResolvedValue(undefined);

    // Reset singleton internal state
    (sandboxSSEService as any).status = 'disconnected';
    (sandboxSSEService as any).projectId = null;
    (sandboxSSEService as any).handlers.clear();
    (sandboxSSEService as any).unsubscribeFn = null;
  });

  afterEach(() => {
    (sandboxSSEService as any).disconnect();
  });

  it('connects and subscribes through agentService', async () => {
    sandboxSSEService.subscribe('proj-1', { onStatusUpdate: vi.fn() });

    await vi.waitFor(() => {
      expect(agentService.connect).toHaveBeenCalledTimes(1);
      expect(agentService.subscribeSandboxState).toHaveBeenCalledWith(
        'proj-1',
        '',
        expect.any(Function)
      );
      expect(sandboxSSEService.getStatus()).toBe('connected');
    });
  });

  it('reuses existing websocket connection if already connected', async () => {
    vi.mocked(agentService.isConnected).mockReturnValue(true);

    sandboxSSEService.subscribe('proj-1', { onStatusUpdate: vi.fn() });

    await vi.waitFor(() => {
      expect(agentService.connect).not.toHaveBeenCalled();
      expect(agentService.subscribeSandboxState).toHaveBeenCalledTimes(1);
    });
  });

  it('routes desktop_started to onDesktopStarted handler', async () => {
    const onDesktopStarted = vi.fn();
    sandboxSSEService.subscribe('proj-1', { onDesktopStarted });

    await vi.waitFor(() => {
      expect(sandboxStateCallback).not.toBeNull();
    });

    sandboxStateCallback?.({
      eventType: 'desktop_started',
      sandboxId: 'sb-1',
      status: 'running',
      isHealthy: true,
      desktopUrl: 'http://localhost:6080/vnc.html',
    });

    expect(onDesktopStarted).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'desktop_started',
      })
    );
  });

  it('routes http_service_started to onHttpServiceStarted handler', async () => {
    const onHttpServiceStarted = vi.fn();
    sandboxSSEService.subscribe('proj-1', { onHttpServiceStarted });

    await vi.waitFor(() => {
      expect(sandboxStateCallback).not.toBeNull();
    });

    sandboxStateCallback?.({
      eventType: 'http_service_started',
      sandboxId: 'sb-1',
      status: 'running',
      isHealthy: true,
      serviceId: 'svc-1',
      serviceName: 'vite-dev',
      sourceType: 'sandbox_internal',
      serviceUrl: 'http://172.17.0.2:5173',
      previewUrl: '/api/v1/projects/proj-1/sandbox/http-services/svc-1/proxy/',
      wsPreviewUrl: '/api/v1/projects/proj-1/sandbox/http-services/svc-1/proxy/ws/',
      autoOpen: true,
      restartToken: 'restart-1',
      updatedAt: new Date().toISOString(),
    });

    expect(onHttpServiceStarted).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'http_service_started',
      })
    );
  });

  it('routes http_service_updated to onHttpServiceUpdated handler', async () => {
    const onHttpServiceUpdated = vi.fn();
    sandboxSSEService.subscribe('proj-1', { onHttpServiceUpdated });

    await vi.waitFor(() => {
      expect(sandboxStateCallback).not.toBeNull();
    });

    sandboxStateCallback?.({
      eventType: 'http_service_updated',
      sandboxId: 'sb-1',
      status: 'running',
      isHealthy: true,
      serviceId: 'svc-1',
      serviceName: 'vite-dev',
      sourceType: 'sandbox_internal',
      serviceUrl: 'http://172.17.0.2:5173',
      previewUrl: '/api/v1/projects/proj-1/sandbox/http-services/svc-1/proxy/',
      autoOpen: true,
      restartToken: 'restart-2',
      updatedAt: new Date().toISOString(),
    });

    expect(onHttpServiceUpdated).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'http_service_updated',
      })
    );
  });

  it('disconnects and unsubscribes when the last subscriber is removed', async () => {
    const unsubscribe = sandboxSSEService.subscribe('proj-1', { onStatusUpdate: vi.fn() });

    await vi.waitFor(() => {
      expect(sandboxSSEService.getStatus()).toBe('connected');
    });

    unsubscribe();

    expect(agentService.unsubscribeSandboxState).toHaveBeenCalledTimes(1);
    expect(sandboxSSEService.getStatus()).toBe('disconnected');
  });

  it('notifies onError when connect fails', async () => {
    const onError = vi.fn();
    vi.mocked(agentService.connect).mockRejectedValue(new Error('connect failed'));

    sandboxSSEService.subscribe('proj-1', { onError });

    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalledTimes(1);
      expect(sandboxSSEService.getStatus()).toBe('error');
    });
  });
});
