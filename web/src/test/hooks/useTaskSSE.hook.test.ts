import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const taskStreamMock = vi.hoisted(() => ({
  subscribeToTaskEvents: vi.fn(),
  cleanup: vi.fn(),
  handlers: undefined as
    | {
        onOpen?: () => void;
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

import { useTaskSSE } from '../../hooks/useTaskSSE';

describe('useTaskSSE Hook', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    taskStreamMock.handlers = undefined;
    taskStreamMock.cleanup = vi.fn();
    taskStreamMock.subscribeToTaskEvents.mockImplementation((_taskId: string, handlers) => {
      taskStreamMock.handlers = handlers;
      return taskStreamMock.cleanup;
    });
  });

  it('subscribes, tracks open state, and cleans up on unsubscribe', () => {
    const { result } = renderHook(() => useTaskSSE());

    act(() => {
      result.current.subscribe('task-123');
      taskStreamMock.handlers?.onOpen?.();
    });

    expect(taskStreamMock.subscribeToTaskEvents).toHaveBeenCalledWith(
      'task-123',
      expect.objectContaining({ onOpen: expect.any(Function) })
    );
    expect(result.current.getIsConnected()).toBe(true);

    act(() => {
      result.current.unsubscribe();
    });

    expect(taskStreamMock.cleanup).toHaveBeenCalledTimes(1);
    expect(result.current.getIsConnected()).toBe(false);
  });

  it('closes an existing subscription before opening a new one', () => {
    const firstCleanup = vi.fn();
    const secondCleanup = vi.fn();
    taskStreamMock.subscribeToTaskEvents
      .mockImplementationOnce((_taskId: string, handlers) => {
        taskStreamMock.handlers = handlers;
        return firstCleanup;
      })
      .mockImplementationOnce((_taskId: string, handlers) => {
        taskStreamMock.handlers = handlers;
        return secondCleanup;
      });

    const { result } = renderHook(() => useTaskSSE());

    act(() => {
      result.current.subscribe('task-1');
      result.current.subscribe('task-2');
    });

    expect(firstCleanup).toHaveBeenCalledTimes(1);
    expect(taskStreamMock.subscribeToTaskEvents).toHaveBeenLastCalledWith(
      'task-2',
      expect.any(Object)
    );
  });

  it('maps progress, completion, failure, and stream errors to current callbacks', () => {
    vi.useFakeTimers();
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const onProgress = vi.fn();
    const onCompleted = vi.fn();
    const onFailed = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() => useTaskSSE({ onProgress, onCompleted, onFailed, onError }));

    act(() => {
      result.current.subscribe('task-123');
      taskStreamMock.handlers?.onOpen?.();
      taskStreamMock.handlers?.onProgress?.({
        event: 'progress',
        data: JSON.stringify({ id: 'task-123', status: 'processing', progress: 40 }),
      });
      taskStreamMock.handlers?.onCompleted?.({
        event: 'completed',
        data: JSON.stringify({ id: 'task-123', result: { ok: true } }),
      });
    });

    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ task_id: 'task-123', status: 'running', progress: 40 })
    );
    expect(onCompleted).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'completed', result: { ok: true } })
    );

    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(taskStreamMock.cleanup).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.subscribe('task-456');
      taskStreamMock.handlers?.onFailed?.({
        event: 'failed',
        data: JSON.stringify({ id: 'task-456', error: 'failed' }),
      });
    });
    expect(onFailed).toHaveBeenCalledWith(expect.objectContaining({ error: 'failed' }));

    act(() => {
      result.current.subscribe('task-789');
      taskStreamMock.handlers?.onError?.(new Error('stream closed'));
    });
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'stream closed' }));
    expect(result.current.getIsConnected()).toBe(false);
    consoleErrorSpy.mockRestore();
  });

  it('uses the latest callbacks after rerender', () => {
    const onProgress1 = vi.fn();
    const onProgress2 = vi.fn();
    const { result, rerender } = renderHook(({ onProgress }) => useTaskSSE({ onProgress }), {
      initialProps: { onProgress: onProgress1 },
    });

    act(() => {
      result.current.subscribe('task-123');
    });

    rerender({ onProgress: onProgress2 });

    act(() => {
      taskStreamMock.handlers?.onProgress?.({
        event: 'progress',
        data: JSON.stringify({ id: 'task-123', status: 'processing', progress: 25 }),
      });
    });

    expect(onProgress1).not.toHaveBeenCalled();
    expect(onProgress2).toHaveBeenCalledTimes(1);
  });

  it('cleans up on unmount and tolerates repeated unsubscribe calls', () => {
    const { result, unmount } = renderHook(() => useTaskSSE());

    act(() => {
      result.current.subscribe('task-123');
      result.current.unsubscribe();
      result.current.unsubscribe();
    });

    expect(taskStreamMock.cleanup).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.subscribe('task-456');
    });
    unmount();

    expect(taskStreamMock.cleanup).toHaveBeenCalledTimes(2);
  });
});
