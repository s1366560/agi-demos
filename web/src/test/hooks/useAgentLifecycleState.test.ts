/**
 * Unit tests for useAgentLifecycleState hook.
 *
 * Tests React hook for subscribing to agent lifecycle state changes via WebSocket.
 */

import { renderHook, waitFor, act, cleanup } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock agentService module with inline mocks (vitest hoisting requirement)
vi.mock('../../services/agentService', () => ({
  agentService: {
    isConnected: vi.fn(() => true),
    connect: vi.fn(() => Promise.resolve()),
    onStatusChange: vi.fn(() => vi.fn()),
    subscribeLifecycleState: vi.fn(() => vi.fn()),
    unsubscribeLifecycleState: vi.fn(),
  },
}));

// Import after mock declaration
import { useAgentLifecycleState } from '../../hooks/useAgentLifecycleState';
import { agentService } from '../../services/agentService';

describe('useAgentLifecycleState', () => {
  const mockProjectId = 'proj-123';
  const mockTenantId = 'tenant-456';

  beforeEach(() => {
    vi.clearAllMocks();
    // Reset default mock behavior
    vi.mocked(agentService.isConnected).mockReturnValue(true);
    vi.mocked(agentService.connect).mockResolvedValue(undefined);
    vi.mocked(agentService.onStatusChange).mockReturnValue(vi.fn());
    vi.mocked(agentService.subscribeLifecycleState).mockReturnValue(vi.fn());
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it('should initialize with null state', () => {
    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: false,
      })
    );

    expect(result.current.lifecycleState).toBeNull();
    expect(result.current.isConnected).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('should subscribe to lifecycle state when enabled', async () => {
    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(agentService.subscribeLifecycleState).toHaveBeenCalledWith(
        mockProjectId,
        mockTenantId,
        expect.any(Function)
      );
    });

    expect(result.current.isConnected).toBe(true);
  });

  it('should not collapse subscriptions for different tenants with the same project id', async () => {
    const first = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: 'tenant-one',
        enabled: true,
      })
    );
    const second = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: 'tenant-two',
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(agentService.subscribeLifecycleState).toHaveBeenCalledWith(
        mockProjectId,
        'tenant-one',
        expect.any(Function)
      );
      expect(agentService.subscribeLifecycleState).toHaveBeenCalledWith(
        mockProjectId,
        'tenant-two',
        expect.any(Function)
      );
    });

    first.unmount();
    second.unmount();
  });

  it('should update state when lifecycle change callback is invoked', async () => {
    let capturedCallback: ((state: unknown) => void) | null = null;

    vi.mocked(agentService.subscribeLifecycleState).mockImplementation(
      (_projectId: string, _tenantId: string, callback: (state: unknown) => void) => {
        capturedCallback = callback;
        return vi.fn();
      }
    );

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(capturedCallback).not.toBeNull();
    });

    // Simulate lifecycle state change
    act(() => {
      if (capturedCallback) {
        capturedCallback({
          lifecycleState: 'ready',
          isInitialized: true,
          isActive: true,
          toolCount: 10,
          skillCount: 5,
        });
      }
    });

    expect(result.current.lifecycleState).toEqual({
      lifecycleState: 'ready',
      isInitialized: true,
      isActive: true,
      toolCount: 10,
      skillCount: 5,
    });
  });

  it('should handle initializing state', async () => {
    let capturedCallback: ((state: unknown) => void) | null = null;

    vi.mocked(agentService.subscribeLifecycleState).mockImplementation(
      (_projectId: string, _tenantId: string, callback: (state: unknown) => void) => {
        capturedCallback = callback;
        return vi.fn();
      }
    );

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(capturedCallback).not.toBeNull();
    });

    act(() => {
      if (capturedCallback) {
        capturedCallback({
          lifecycleState: 'initializing',
          isInitialized: false,
          isActive: false,
        });
      }
    });

    expect(result.current.lifecycleState).toEqual({
      lifecycleState: 'initializing',
      isInitialized: false,
      isActive: false,
    });

    // Check derived status
    expect(result.current.status.label).toBe('Initializing');
    expect(result.current.status.icon).toBe('Loader2');
  });

  it('should handle ready state', async () => {
    let capturedCallback: ((state: unknown) => void) | null = null;

    vi.mocked(agentService.subscribeLifecycleState).mockImplementation(
      (_projectId: string, _tenantId: string, callback: (state: unknown) => void) => {
        capturedCallback = callback;
        return vi.fn();
      }
    );

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(capturedCallback).not.toBeNull();
    });

    act(() => {
      if (capturedCallback) {
        capturedCallback({
          lifecycleState: 'ready',
          isInitialized: true,
          isActive: true,
          toolCount: 10,
          skillCount: 5,
        });
      }
    });

    expect(result.current.lifecycleState).toEqual({
      lifecycleState: 'ready',
      isInitialized: true,
      isActive: true,
      toolCount: 10,
      skillCount: 5,
    });

    // Check derived status
    expect(result.current.status.label).toBe('Ready');
    expect(result.current.status.icon).toBe('CheckCircle');
  });

  it('should handle executing state with conversation', async () => {
    let capturedCallback: ((state: unknown) => void) | null = null;

    vi.mocked(agentService.subscribeLifecycleState).mockImplementation(
      (_projectId: string, _tenantId: string, callback: (state: unknown) => void) => {
        capturedCallback = callback;
        return vi.fn();
      }
    );

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(capturedCallback).not.toBeNull();
    });

    act(() => {
      if (capturedCallback) {
        capturedCallback({
          lifecycleState: 'executing',
          conversationId: 'conv-456',
          isInitialized: true,
          isActive: true,
        });
      }
    });

    expect(result.current.lifecycleState).toEqual({
      lifecycleState: 'executing',
      conversationId: 'conv-456',
      isInitialized: true,
      isActive: true,
    });

    expect(result.current.status.label).toBe('Running');
    expect(result.current.status.icon).toBe('Cpu');
  });

  it('should handle paused state', async () => {
    let capturedCallback: ((state: unknown) => void) | null = null;

    vi.mocked(agentService.subscribeLifecycleState).mockImplementation(
      (_projectId: string, _tenantId: string, callback: (state: unknown) => void) => {
        capturedCallback = callback;
        return vi.fn();
      }
    );

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(capturedCallback).not.toBeNull();
    });

    act(() => {
      if (capturedCallback) {
        capturedCallback({
          lifecycleState: 'paused',
          isInitialized: true,
          isActive: false,
        });
      }
    });

    expect(result.current.lifecycleState).toEqual({
      lifecycleState: 'paused',
      isInitialized: true,
      isActive: false,
    });

    expect(result.current.status.label).toBe('Paused');
    expect(result.current.status.icon).toBe('Pause');
  });

  it('should handle shutting_down state', async () => {
    let capturedCallback: ((state: unknown) => void) | null = null;

    vi.mocked(agentService.subscribeLifecycleState).mockImplementation(
      (_projectId: string, _tenantId: string, callback: (state: unknown) => void) => {
        capturedCallback = callback;
        return vi.fn();
      }
    );

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(capturedCallback).not.toBeNull();
    });

    act(() => {
      if (capturedCallback) {
        capturedCallback({
          lifecycleState: 'shutting_down',
          isInitialized: false,
          isActive: false,
        });
      }
    });

    expect(result.current.lifecycleState).toEqual({
      lifecycleState: 'shutting_down',
      isInitialized: false,
      isActive: false,
    });

    expect(result.current.status.label).toBe('Shutting down');
    expect(result.current.status.icon).toBe('Power');
  });

  it('should handle error state', async () => {
    let capturedCallback: ((state: unknown) => void) | null = null;

    vi.mocked(agentService.subscribeLifecycleState).mockImplementation(
      (_projectId: string, _tenantId: string, callback: (state: unknown) => void) => {
        capturedCallback = callback;
        return vi.fn();
      }
    );

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(capturedCallback).not.toBeNull();
    });

    act(() => {
      if (capturedCallback) {
        capturedCallback({
          lifecycleState: 'error',
          errorMessage: 'Connection failed',
          isInitialized: false,
          isActive: false,
        });
      }
    });

    expect(result.current.lifecycleState).toEqual({
      lifecycleState: 'error',
      errorMessage: 'Connection failed',
      isInitialized: false,
      isActive: false,
    });

    expect(result.current.status.label).toBe('Error');
    expect(result.current.status.icon).toBe('AlertCircle');
  });

  it('should unsubscribe on unmount', async () => {
    const { unmount } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(agentService.subscribeLifecycleState).toHaveBeenCalled();
    });

    unmount();

    expect(agentService.unsubscribeLifecycleState).toHaveBeenCalled();
  });

  it('should not subscribe after unmount while websocket connect is pending', async () => {
    let resolveConnect: (() => void) | null = null;
    const statusUnsubscribe = vi.fn();
    vi.mocked(agentService.isConnected).mockReturnValue(false);
    vi.mocked(agentService.connect).mockReturnValue(
      new Promise<void>((resolve) => {
        resolveConnect = resolve;
      })
    );
    vi.mocked(agentService.onStatusChange).mockReturnValue(statusUnsubscribe);

    const { unmount } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(agentService.connect).toHaveBeenCalled();
    });

    unmount();

    await act(async () => {
      resolveConnect?.();
      await Promise.resolve();
    });

    expect(agentService.subscribeLifecycleState).not.toHaveBeenCalled();
    expect(agentService.unsubscribeLifecycleState).not.toHaveBeenCalled();
    expect(statusUnsubscribe).toHaveBeenCalled();
  });

  it('should not subscribe when disabled', () => {
    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: false,
      })
    );

    expect(agentService.subscribeLifecycleState).not.toHaveBeenCalled();
    expect(result.current.lifecycleState).toBeNull();
  });

  it('should handle connection status changes', async () => {
    let statusChangeCallback: ((status: string) => void) | null = null;

    vi.mocked(agentService.onStatusChange).mockImplementation(
      (callback: (status: string) => void) => {
        statusChangeCallback = callback;
        return vi.fn();
      }
    );
    vi.mocked(agentService.isConnected).mockReturnValue(false);

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    expect(result.current.isConnected).toBe(false);

    await waitFor(() => {
      expect(statusChangeCallback).not.toBeNull();
    });

    act(() => {
      if (statusChangeCallback) {
        statusChangeCallback('connected');
      }
    });

    expect(result.current.isConnected).toBe(true);
  });

  it('should update status when tool_count changes', async () => {
    let capturedCallback: ((state: unknown) => void) | null = null;

    vi.mocked(agentService.subscribeLifecycleState).mockImplementation(
      (_projectId: string, _tenantId: string, callback: (state: unknown) => void) => {
        capturedCallback = callback;
        return vi.fn();
      }
    );

    const { result } = renderHook(() =>
      useAgentLifecycleState({
        projectId: mockProjectId,
        tenantId: mockTenantId,
        enabled: true,
      })
    );

    await waitFor(() => {
      expect(capturedCallback).not.toBeNull();
    });

    act(() => {
      if (capturedCallback) {
        capturedCallback({
          lifecycleState: 'ready',
          isInitialized: true,
          isActive: true,
          toolCount: 15,
          skillCount: 3,
        });
      }
    });

    expect(result.current.lifecycleState?.toolCount).toBe(15);
    expect(result.current.lifecycleState?.skillCount).toBe(3);
  });
});
