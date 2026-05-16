import { beforeEach, describe, expect, it, vi } from 'vitest';

const taskStreamMock = vi.hoisted(() => ({
  subscribeToTaskEvents: vi.fn(),
  cleanup: vi.fn(),
  handlers: undefined as
    | {
        onProgress?: (event: { event: string; data: string }) => void;
        onCompleted?: (event: { event: string; data: string }) => void;
        onFailed?: (event: { event: string; data: string }) => void;
        onError?: (error: Error) => void;
      }
    | undefined,
}));

vi.mock('../../services/taskStream', () => ({
  subscribeToTaskEvents: taskStreamMock.subscribeToTaskEvents,
}));

import { subscribeToTask } from '../../hooks/useTaskSSE';

describe('subscribeToTask', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    taskStreamMock.handlers = undefined;
    taskStreamMock.cleanup = vi.fn();
    taskStreamMock.subscribeToTaskEvents.mockImplementation((_taskId: string, handlers) => {
      taskStreamMock.handlers = handlers;
      return taskStreamMock.cleanup;
    });
  });

  it('subscribes to the requested task through the authenticated task stream', () => {
    subscribeToTask('task-123', {});

    expect(taskStreamMock.subscribeToTaskEvents).toHaveBeenCalledWith(
      'task-123',
      expect.objectContaining({
        onProgress: expect.any(Function),
        onCompleted: expect.any(Function),
        onFailed: expect.any(Function),
      })
    );
  });

  it('maps progress, completion, and failure events to task callbacks', () => {
    const onProgress = vi.fn();
    const onCompleted = vi.fn();
    const onFailed = vi.fn();

    subscribeToTask('task-123', { onProgress, onCompleted, onFailed });

    taskStreamMock.handlers?.onProgress?.({
      event: 'progress',
      data: JSON.stringify({
        id: 'task-123',
        status: 'processing',
        progress: 50,
        message: 'Processing...',
      }),
    });
    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({
        task_id: 'task-123',
        status: 'running',
        progress: 50,
      })
    );

    taskStreamMock.handlers?.onCompleted?.({
      event: 'completed',
      data: JSON.stringify({
        id: 'task-123',
        message: 'Done',
        result: { entities: 5 },
      }),
    });
    expect(onCompleted).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'completed',
        progress: 100,
        result: { entities: 5 },
      })
    );

    taskStreamMock.handlers?.onFailed?.({
      event: 'failed',
      data: JSON.stringify({
        id: 'task-123',
        progress: 30,
        message: 'Processing failed',
        error: 'Network error',
      }),
    });
    expect(onFailed).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'failed',
        error: 'Network error',
      })
    );
  });

  it('returns the underlying cleanup function', () => {
    const cleanup = subscribeToTask('task-123', {});

    cleanup();

    expect(taskStreamMock.cleanup).toHaveBeenCalledTimes(1);
  });
});
