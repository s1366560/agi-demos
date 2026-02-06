/**
 * Tests for useTaskSSE hook
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { subscribeToTask } from '../../hooks/useTaskSSE';

// Mock EventSource
class MockEventSource {
  url: string;
  readyState: number = 0;
  onopen: (() => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  private listeners: Map<string, ((e: MessageEvent) => void)[]> = new Map();

  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  constructor(url: string) {
    this.url = url;
    this.readyState = MockEventSource.OPEN;
    // Simulate connection open
    setTimeout(() => {
      this.onopen?.();
    }, 0);
  }

  addEventListener(type: string, callback: (e: MessageEvent) => void) {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, []);
    }
    this.listeners.get(type)!.push(callback);
  }

  removeEventListener(type: string, callback: (e: MessageEvent) => void) {
    const listeners = this.listeners.get(type);
    if (listeners) {
      const index = listeners.indexOf(callback);
      if (index > -1) {
        listeners.splice(index, 1);
      }
    }
  }

  close() {
    this.readyState = MockEventSource.CLOSED;
  }

  // Helper to simulate events
  emit(type: string, data: any) {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    const listeners = this.listeners.get(type);
    if (listeners) {
      listeners.forEach((callback) => callback(event));
    }
  }
}

// Store reference to mock instances for testing
let mockEventSourceInstance: MockEventSource | null = null;

// Factory function to create and track mock EventSource
function createMockEventSourceClass() {
  return class extends MockEventSource {
    constructor(url: string) {
      super(url);
      // Store instance for test assertions - not a true 'this' alias issue
      // eslint-disable-next-line @typescript-eslint/no-this-alias
      mockEventSourceInstance = this;
    }
  };
}

describe('subscribeToTask', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockEventSourceInstance = null;

    // Mock global EventSource
    (global as any).EventSource = createMockEventSourceClass();
  });

  afterEach(() => {
    mockEventSourceInstance = null;
  });

  it('should connect to correct SSE URL', async () => {
    const taskId = 'task-123';

    subscribeToTask(taskId, {});

    // Wait for constructor to complete
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(mockEventSourceInstance).not.toBeNull();
    expect(mockEventSourceInstance!.url).toContain(`/tasks/${taskId}/stream`);
  });

  it('should call onProgress callback on progress events', async () => {
    const taskId = 'task-123';
    const onProgress = vi.fn();

    subscribeToTask(taskId, { onProgress });

    await new Promise((resolve) => setTimeout(resolve, 10));

    // Simulate progress event
    mockEventSourceInstance!.emit('progress', {
      id: taskId,
      status: 'processing',
      progress: 50,
      message: 'Processing...',
    });

    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({
        task_id: taskId,
        status: 'running',
        progress: 50,
        message: 'Processing...',
      })
    );
  });

  it('should normalize status from processing to running', async () => {
    const taskId = 'task-123';
    const onProgress = vi.fn();

    subscribeToTask(taskId, { onProgress });

    await new Promise((resolve) => setTimeout(resolve, 10));

    mockEventSourceInstance!.emit('progress', {
      id: taskId,
      status: 'processing',
      progress: 25,
    });

    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'running',
      })
    );
  });

  it('should call onCompleted callback on completed events', async () => {
    const taskId = 'task-123';
    const onCompleted = vi.fn();

    subscribeToTask(taskId, { onCompleted });

    await new Promise((resolve) => setTimeout(resolve, 10));

    mockEventSourceInstance!.emit('completed', {
      id: taskId,
      status: 'completed',
      progress: 100,
      message: 'Done',
      result: { entities: 5 },
    });

    expect(onCompleted).toHaveBeenCalledWith(
      expect.objectContaining({
        task_id: taskId,
        status: 'completed',
        progress: 100,
        message: 'Done',
        result: { entities: 5 },
      })
    );
  });

  it('should close connection on completion', async () => {
    const taskId = 'task-123';

    subscribeToTask(taskId, {});

    await new Promise((resolve) => setTimeout(resolve, 10));

    mockEventSourceInstance!.emit('completed', {
      id: taskId,
      status: 'completed',
      progress: 100,
    });

    expect(mockEventSourceInstance!.readyState).toBe(MockEventSource.CLOSED);
  });

  it('should call onFailed callback on failed events', async () => {
    const taskId = 'task-123';
    const onFailed = vi.fn();

    subscribeToTask(taskId, { onFailed });

    await new Promise((resolve) => setTimeout(resolve, 10));

    mockEventSourceInstance!.emit('failed', {
      id: taskId,
      status: 'failed',
      progress: 30,
      message: 'Processing failed',
      error: 'Network error',
    });

    expect(onFailed).toHaveBeenCalledWith(
      expect.objectContaining({
        task_id: taskId,
        status: 'failed',
        message: 'Processing failed',
        error: 'Network error',
      })
    );
  });

  it('should return cleanup function that closes connection', async () => {
    const taskId = 'task-123';

    const cleanup = subscribeToTask(taskId, {});

    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(mockEventSourceInstance!.readyState).toBe(MockEventSource.OPEN);

    cleanup();

    expect(mockEventSourceInstance!.readyState).toBe(MockEventSource.CLOSED);
  });

  it('should handle multiple progress events', async () => {
    const taskId = 'task-123';
    const onProgress = vi.fn();

    subscribeToTask(taskId, { onProgress });

    await new Promise((resolve) => setTimeout(resolve, 10));

    // Simulate multiple progress updates
    mockEventSourceInstance!.emit('progress', { id: taskId, status: 'processing', progress: 10 });
    mockEventSourceInstance!.emit('progress', { id: taskId, status: 'processing', progress: 50 });
    mockEventSourceInstance!.emit('progress', { id: taskId, status: 'processing', progress: 75 });

    expect(onProgress).toHaveBeenCalledTimes(3);
    expect(onProgress).toHaveBeenLastCalledWith(expect.objectContaining({ progress: 75 }));
  });
});
