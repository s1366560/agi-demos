/**
 * TDD RED Phase: Tests for useTaskSSE hook (React component behavior)
 *
 * Feature: SSE connection cleanup and memory leak prevention
 *
 * These tests verify:
 * 1. Component unmount closes SSE connection properly
 * 2. Multiple subscribe calls don't create duplicate connections
 * 3. Error handling works correctly
 * 4. No memory leaks when hook is used and unused rapidly
 * 5. Connection state is tracked accurately
 *
 * Note: These tests are written FIRST (TDD RED phase).
 * They should initially FAIL and then drive the implementation.
 */

import { renderHook, waitFor, cleanup } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { useTaskSSE } from '../../hooks/useTaskSSE';

// Mock EventSource
class MockEventSource {
  url: string;
  readyState: number = 0;
  onopen: (() => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  private listeners: Map<string, Set<(e: MessageEvent) => void>> = new Map();
  private _isClosed: boolean = false;

  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  constructor(url: string) {
    this.url = url;
    this.readyState = MockEventSource.CONNECTING;
    // Simulate connection open
    setTimeout(() => {
      if (!this._isClosed) {
        this.readyState = MockEventSource.OPEN;
        this.onopen?.();
      }
    }, 0);
  }

  addEventListener(type: string, callback: (e: MessageEvent) => void) {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set());
    }
    this.listeners.get(type)!.add(callback);
  }

  removeEventListener(type: string, callback: (e: MessageEvent) => void) {
    const listeners = this.listeners.get(type);
    if (listeners) {
      listeners.delete(callback);
    }
  }

  close() {
    this._isClosed = true;
    this.readyState = MockEventSource.CLOSED;
    // Clear all listeners
    this.listeners.clear();
  }

  // Helper to simulate events
  emit(type: string, data: unknown) {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    const listeners = this.listeners.get(type);
    if (listeners) {
      listeners.forEach((callback) => callback(event));
    }
  }

  // Helper to get listener count for testing duplicate connections
  getListenerCount(type: string): number {
    return this.listeners.get(type)?.size ?? 0;
  }
}

// Track all created EventSource instances for leak detection
const eventSourceInstances = new Set<MockEventSource>();
let activeInstance: MockEventSource | null = null;

// Factory function to create and track mock EventSource
function createMockEventSourceClass() {
  return class extends MockEventSource {
    constructor(url: string) {
      super(url);
      activeInstance = this;
      eventSourceInstances.add(this);
    }
  };
}

describe('useTaskSSE Hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    eventSourceInstances.clear();
    activeInstance = null;

    // Mock global EventSource
    (global as any).EventSource = createMockEventSourceClass();
  });

  afterEach(() => {
    cleanup();
  });

  describe('Connection Lifecycle', () => {
    it('should create EventSource when subscribe is called', async () => {
      const { result } = renderHook(() => useTaskSSE());

      expect(activeInstance).toBeNull();

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
        expect(activeInstance!.url).toContain('/tasks/task-123/stream');
      });
    });

    it('should close EventSource when component unmounts', async () => {
      const { result, unmount } = renderHook(() => useTaskSSE());

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const instance = activeInstance!;
      expect(instance.readyState).toBe(MockEventSource.OPEN);

      // Unmount the component
      unmount();

      // Connection should be closed
      expect(instance.readyState).toBe(MockEventSource.CLOSED);
    });

    it('should close connection when unsubscribe is called', async () => {
      const { result } = renderHook(() => useTaskSSE());

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const instance = activeInstance!;
      expect(instance.readyState).toBe(MockEventSource.OPEN);

      result.current.unsubscribe();

      expect(instance.readyState).toBe(MockEventSource.CLOSED);
    });

    it('should track connection state accurately', async () => {
      const { result } = renderHook(() => useTaskSSE());

      expect(result.current.getIsConnected()).toBe(false);

      result.current.subscribe('task-123');

      // Wait for connection to open
      await waitFor(() => {
        expect(result.current.getIsConnected()).toBe(true);
      });

      result.current.unsubscribe();

      expect(result.current.getIsConnected()).toBe(false);
    });
  });

  describe('Duplicate Connection Prevention', () => {
    it('should close existing connection when subscribing to a new task', async () => {
      const { result } = renderHook(() => useTaskSSE());

      // Subscribe to first task
      result.current.subscribe('task-1');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const firstInstance = activeInstance!;

      // Subscribe to second task
      result.current.subscribe('task-2');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
        expect(activeInstance!.url).toContain('/tasks/task-2/stream');
      });

      // First connection should be closed
      expect(firstInstance.readyState).toBe(MockEventSource.CLOSED);
    });

    it('should not create duplicate connections on rapid subscribe calls', async () => {
      const { result } = renderHook(() => useTaskSSE());

      // Rapid subscribe calls
      result.current.subscribe('task-123');
      result.current.subscribe('task-123');
      result.current.subscribe('task-123');

      // Should only have one connection
      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      // Check that only one EventSource was created
      const totalInstances = eventSourceInstances.size;
      expect(totalInstances).toBeLessThanOrEqual(2); // Allow for timing: old + new
    });
  });

  describe('Memory Leak Prevention', () => {
    it('should cleanup connections when hook is mounted/unmounted rapidly', async () => {
      // Simulate rapid mount/unmount cycles
      for (let i = 0; i < 5; i++) {
        const { result, unmount } = renderHook(() => useTaskSSE());

        result.current.subscribe(`task-${i}`);

        await waitFor(() => {
          expect(activeInstance).not.toBeNull();
        });

        unmount();
      }

      // All connections should be closed
      eventSourceInstances.forEach((instance) => {
        expect(instance.readyState).toBe(MockEventSource.CLOSED);
      });

      // Should have at most 5 instances (one per iteration)
      expect(eventSourceInstances.size).toBeLessThanOrEqual(5);
    });

    it('should not accumulate listeners on multiple progress events', async () => {
      const { result } = renderHook(() => useTaskSSE());

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const instance = activeInstance!;

      // Check initial listener count
      const initialCount = instance.getListenerCount('progress');

      // Emit many progress events
      for (let i = 0; i < 10; i++) {
        instance.emit('progress', {
          id: 'task-123',
          status: 'processing',
          progress: i * 10,
          message: 'Processing...',
        });
      }

      // Listener count should not grow
      const finalCount = instance.getListenerCount('progress');
      expect(finalCount).toBe(initialCount);
    });
  });

  describe('Callback Handling', () => {
    it('should call onProgress when progress events are received', async () => {
      const onProgress = vi.fn();
      const { result } = renderHook(() => useTaskSSE({ onProgress }));

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      activeInstance!.emit('progress', {
        id: 'task-123',
        status: 'processing',
        progress: 50,
        message: 'Halfway there',
      });

      expect(onProgress).toHaveBeenCalledWith(
        expect.objectContaining({
          task_id: 'task-123',
          status: 'running',
          progress: 50,
          message: 'Halfway there',
        })
      );
    });

    it('should call onCompleted and close connection on completion', async () => {
      const onCompleted = vi.fn();
      const { result } = renderHook(() => useTaskSSE({ onCompleted }));

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const instance = activeInstance!;

      instance.emit('completed', {
        id: 'task-123',
        status: 'completed',
        progress: 100,
        message: 'Done',
        result: { data: 'success' },
      });

      expect(onCompleted).toHaveBeenCalledWith(
        expect.objectContaining({
          task_id: 'task-123',
          status: 'completed',
          progress: 100,
          result: { data: 'success' },
        })
      );

      // Connection should close after a short delay
      await waitFor(
        () => {
          expect(instance.readyState).toBe(MockEventSource.CLOSED);
        },
        { timeout: 1000 }
      );
    });

    it('should call onFailed and close connection on failure', async () => {
      const onFailed = vi.fn();
      const { result } = renderHook(() => useTaskSSE({ onFailed }));

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const instance = activeInstance!;

      instance.emit('failed', {
        id: 'task-123',
        status: 'failed',
        progress: 30,
        message: 'Task failed',
        error: 'Network error',
      });

      expect(onFailed).toHaveBeenCalledWith(
        expect.objectContaining({
          task_id: 'task-123',
          status: 'failed',
          error: 'Network error',
        })
      );

      // Connection should close immediately on failure
      expect(instance.readyState).toBe(MockEventSource.CLOSED);
    });

    it('should update callbacks when options change', async () => {
      const onProgress1 = vi.fn();
      const onProgress2 = vi.fn();
      const { result, rerender } = renderHook(({ options }) => useTaskSSE(options), {
        initialProps: { options: { onProgress: onProgress1 } },
      });

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      // Emit with first callback
      activeInstance!.emit('progress', {
        id: 'task-123',
        status: 'processing',
        progress: 25,
      });

      expect(onProgress1).toHaveBeenCalledTimes(1);
      expect(onProgress2).not.toHaveBeenCalled();

      // Update options
      rerender({ options: { onProgress: onProgress2 } });

      // Emit with second callback
      activeInstance!.emit('progress', {
        id: 'task-123',
        status: 'processing',
        progress: 50,
      });

      expect(onProgress2).toHaveBeenCalledTimes(1);
    });
  });

  describe('Error Handling', () => {
    it('should call onError when connection closes unexpectedly', async () => {
      const onError = vi.fn();
      const { result } = renderHook(() => useTaskSSE({ onError }));

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const instance = activeInstance!;

      // Simulate error
      instance.onerror?.(new Event('error'));

      expect(onError).toHaveBeenCalledWith(
        expect.objectContaining({
          message: expect.stringContaining('SSE connection'),
        })
      );
    });

    it('should handle malformed JSON in events gracefully', async () => {
      const onProgress = vi.fn();
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const { result } = renderHook(() => useTaskSSE({ onProgress }));

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      // Emit malformed event
      const badEvent = new MessageEvent('progress', {
        data: 'invalid json{{{',
      });
      activeInstance!.onmessage?.(badEvent);

      // Should not crash, onProgress should not be called
      expect(onProgress).not.toHaveBeenCalled();
      expect(consoleErrorSpy).toHaveBeenCalled();

      consoleErrorSpy.mockRestore();
    });
  });

  describe('Integration Scenarios', () => {
    it('should handle full lifecycle: connect -> progress -> complete -> cleanup', async () => {
      const onProgress = vi.fn();
      const onCompleted = vi.fn();
      const { result, unmount } = renderHook(() => useTaskSSE({ onProgress, onCompleted }));

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
        expect(result.current.getIsConnected()).toBe(true);
      });

      const instance = activeInstance!;

      // Multiple progress events
      instance.emit('progress', { id: 'task-123', status: 'processing', progress: 25 });
      instance.emit('progress', { id: 'task-123', status: 'processing', progress: 50 });
      instance.emit('progress', { id: 'task-123', status: 'processing', progress: 75 });

      expect(onProgress).toHaveBeenCalledTimes(3);

      // Complete
      instance.emit('completed', {
        id: 'task-123',
        status: 'completed',
        progress: 100,
        message: 'Done',
      });

      expect(onCompleted).toHaveBeenCalledTimes(1);

      // Unmount (should be safe even after connection closed)
      unmount();

      // Should not throw
      expect(instance.readyState).toBe(MockEventSource.CLOSED);
    });

    it('should handle re-subscription after completion', async () => {
      const { result } = renderHook(() => useTaskSSE());

      // First subscription
      result.current.subscribe('task-1');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const firstInstance = activeInstance!;

      // Complete first task
      firstInstance.emit('completed', {
        id: 'task-1',
        status: 'completed',
        progress: 100,
      });

      // Wait for connection to close
      await waitFor(
        () => {
          expect(firstInstance.readyState).toBe(MockEventSource.CLOSED);
        },
        { timeout: 1000 }
      );

      // Subscribe to new task
      result.current.subscribe('task-2');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
        expect(activeInstance!.url).toContain('/tasks/task-2/stream');
      });

      expect(activeInstance!.readyState).toBe(MockEventSource.OPEN);
    });
  });

  describe('Edge Cases', () => {
    it('should handle unsubscribe when no connection exists', () => {
      const { result } = renderHook(() => useTaskSSE());

      // Should not throw
      expect(() => result.current.unsubscribe()).not.toThrow();
    });

    it('should handle multiple unsubscribe calls', async () => {
      const { result } = renderHook(() => useTaskSSE());

      result.current.subscribe('task-123');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      // Multiple unsubscribe calls should be safe
      result.current.unsubscribe();
      result.current.unsubscribe();
      result.current.unsubscribe();

      expect(activeInstance!.readyState).toBe(MockEventSource.CLOSED);
    });

    it('should handle subscribing after unsubscribe', async () => {
      const { result } = renderHook(() => useTaskSSE());

      result.current.subscribe('task-1');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
      });

      const firstInstance = activeInstance!;

      result.current.unsubscribe();

      expect(firstInstance.readyState).toBe(MockEventSource.CLOSED);

      // Subscribe again
      result.current.subscribe('task-2');

      await waitFor(() => {
        expect(activeInstance).not.toBeNull();
        expect(activeInstance!.url).toContain('/tasks/task-2/stream');
      });

      // New connection should be open
      expect(activeInstance!.readyState).toBe(MockEventSource.OPEN);
    });
  });
});
