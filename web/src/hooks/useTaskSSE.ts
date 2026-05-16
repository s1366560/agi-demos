import { useCallback, useRef, useEffect } from 'react';

import { subscribeToTaskEvents } from '../services/taskStream';

export interface TaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
  result?: unknown;
  error?: string;
}

interface UseTaskSSEOptions {
  onProgress?: ((task: TaskStatus) => void) | undefined;
  onCompleted?: ((task: TaskStatus) => void) | undefined;
  onFailed?: ((task: TaskStatus) => void) | undefined;
  onError?: ((error: Error) => void) | undefined;
}

/**
 * Type guard to check if a value is a string primitive (not an object)
 */
function isStringPrimitive(value: unknown): value is string {
  return typeof value === 'string';
}

/**
 * Safely convert unknown value to string, handling objects safely.
 * Returns empty string for objects to avoid '[object Object]' issues.
 */
function safeStringify(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (isStringPrimitive(value)) {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  // For objects, try JSON.stringify, otherwise return empty string
  try {
    return JSON.stringify(value);
  } catch {
    return '';
  }
}

/**
 * Safely extract number from unknown value
 */
function safeNumber(value: unknown): number {
  if (typeof value === 'number' && !isNaN(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = parseFloat(value);
    return isNaN(parsed) ? 0 : parsed;
  }
  return 0;
}

/**
 * Normalize backend status to standardized status values.
 * Extracted to module level for reuse.
 */
function normalizeStatus(status: string): TaskStatus['status'] {
  const statusMap: Record<string, TaskStatus['status']> = {
    processing: 'running',
    pending: 'pending',
    completed: 'completed',
    failed: 'failed',
  };
  const lowerStatus = status.toLowerCase();
  return statusMap[lowerStatus] ?? 'pending';
}

/**
 * Safely parse JSON data from SSE events.
 * Returns null if parsing fails.
 */
function safeParseJSON(data: unknown): Record<string, unknown> | null {
  if (typeof data !== 'string') {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(data);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return null;
  } catch (error) {
    console.error('Failed to parse SSE event data:', error, 'Raw data:', data);
    return null;
  }
}

/**
 * Hook for subscribing to task status updates via Server-Sent Events (SSE)
 *
 * @example
 * const { subscribe, unsubscribe, isConnected } = useTaskSSE({
 *     onProgress: (task) => setProgress(task.progress),
 *     onCompleted: (task) => handleSuccess(),
 *     onFailed: (task) => setError(task.error),
 * });
 *
 * // Start listening to a task
 * subscribe(taskId);
 *
 * // Stop listening
 * unsubscribe();
 */
export function useTaskSSE(options: UseTaskSSEOptions = {}) {
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const isConnectedRef = useRef(false);

  // Store callbacks in a ref to avoid recreating subscribe on every options change
  // This prevents infinite loops when options is passed as an inline object
  const optionsRef = useRef(options);

  // Update ref when options change
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const unsubscribe = useCallback(() => {
    if (unsubscribeRef.current) {
      unsubscribeRef.current();
      unsubscribeRef.current = null;
      isConnectedRef.current = false;
    }
  }, []);

  const subscribe = useCallback(
    (taskId: string) => {
      // Close existing connection if any
      unsubscribe();

      unsubscribeRef.current = subscribeToTaskEvents(taskId, {
        onOpen: () => {
          isConnectedRef.current = true;
        },
        onProgress: (event) => {
          const data = safeParseJSON(event.data);
          if (!data) return;

          const task: TaskStatus = {
            task_id: safeStringify(data.id),
            status: normalizeStatus(safeStringify(data.status)),
            progress: safeNumber(data.progress),
            message: safeStringify(data.message) || 'Processing...',
          };

          optionsRef.current.onProgress?.(task);
        },
        onCompleted: (event) => {
          const data = safeParseJSON(event.data);
          if (!data) return;

          const task: TaskStatus = {
            task_id: safeStringify(data.id),
            status: 'completed',
            progress: 100,
            message: safeStringify(data.message) || 'Completed',
            result: data.result,
          };

          optionsRef.current.onCompleted?.(task);
          window.setTimeout(() => {
            unsubscribe();
          }, 500);
        },
        onFailed: (event) => {
          const data = safeParseJSON(event.data);
          if (!data) return;

          console.error('Failed event:', data);

          const task: TaskStatus = {
            task_id: safeStringify(data.id),
            status: 'failed',
            progress: safeNumber(data.progress),
            message: safeStringify(data.message) || 'Failed',
            error: safeStringify(data.error || data.message) || 'Unknown error',
          };

          optionsRef.current.onFailed?.(task);
          isConnectedRef.current = false;
          unsubscribe();
        },
        onError: (error) => {
          console.error('SSE connection error:', error);
          isConnectedRef.current = false;
          optionsRef.current.onError?.(error);
        },
      });

      return () => {
        unsubscribe();
      };
    },
    [unsubscribe]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      unsubscribe();
    };
  }, [unsubscribe]);

  return {
    subscribe,
    unsubscribe,
    getIsConnected: () => isConnectedRef.current,
  };
}

/**
 * Utility function to subscribe to a task without using a hook.
 * Useful for one-off subscriptions outside of React components.
 *
 * @param taskId - The task ID to subscribe to
 * @param callbacks - Object containing onProgress, onCompleted, onFailed, onError handlers
 * @returns Cleanup function to close the SSE connection
 */
export function subscribeToTask(taskId: string, callbacks: UseTaskSSEOptions): () => void {
  return subscribeToTaskEvents(taskId, {
    onProgress: (event) => {
      const data = safeParseJSON(event.data);
      if (!data) return;

      callbacks.onProgress?.({
        task_id: safeStringify(data.id),
        status: normalizeStatus(safeStringify(data.status)),
        progress: safeNumber(data.progress),
        message: safeStringify(data.message) || 'Processing...',
      });
    },
    onCompleted: (event) => {
      const data = safeParseJSON(event.data);
      if (!data) return;

      callbacks.onCompleted?.({
        task_id: safeStringify(data.id),
        status: 'completed',
        progress: 100,
        message: safeStringify(data.message) || 'Completed',
        result: data.result,
      });
    },
    onFailed: (event) => {
      const data = safeParseJSON(event.data);
      if (!data) return;

      callbacks.onFailed?.({
        task_id: safeStringify(data.id),
        status: 'failed',
        progress: safeNumber(data.progress),
        message: safeStringify(data.message) || 'Failed',
        error: safeStringify(data.error || data.message) || 'Unknown error',
      });
    },
    onError: callbacks.onError,
  });
}
