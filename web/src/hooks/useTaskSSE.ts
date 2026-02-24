import { useCallback, useRef, useEffect } from 'react';

import { createApiUrl } from '../services/client/urlUtils';

export interface TaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
  result?: unknown | undefined;
  error?: string | undefined;
}

interface UseTaskSSEOptions {
  onProgress?: ((task: TaskStatus) => void) | undefined;
  onCompleted?: ((task: TaskStatus) => void) | undefined;
  onFailed?: ((task: TaskStatus) => void) | undefined;
  onError?: ((error: Error) => void) | undefined;
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
  return statusMap[status?.toLowerCase()] || 'pending';
}

/**
 * Safely parse JSON data from SSE events.
 * Returns null if parsing fails.
 */
function safeParseJSON(data: string): Record<string, unknown> | null {
  try {
    return JSON.parse(data);
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
  const eventSourceRef = useRef<EventSource | null>(null);
  const isConnectedRef = useRef(false);

  // Store callbacks in a ref to avoid recreating subscribe on every options change
  // This prevents infinite loops when options is passed as an inline object
  const optionsRef = useRef(options);

  // Update ref when options change
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const unsubscribe = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      isConnectedRef.current = false;
    }
  }, []);

  const subscribe = useCallback(
    (taskId: string) => {
      // Close existing connection if any
      unsubscribe();

      const streamUrl = createApiUrl(`/tasks/${taskId}/stream`);

      const eventSource = new EventSource(streamUrl);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        isConnectedRef.current = true;
      };

      // Listen for progress events
      eventSource.addEventListener('progress', (e: MessageEvent) => {
        const data = safeParseJSON(e.data);
        if (!data) return;

        const task: TaskStatus = {
          task_id: String(data.id || ''),
          status: normalizeStatus(String(data.status || '')),
          progress: Number(data.progress) || 0,
          message: String(data.message || 'Processing...'),
        };

        optionsRef.current.onProgress?.(task);
      });

      // Listen for completion
      eventSource.addEventListener('completed', (e: MessageEvent) => {
        const data = safeParseJSON(e.data);
        if (!data) return;

        const task: TaskStatus = {
          task_id: String(data.id || ''),
          status: 'completed',
          progress: 100,
          message: String(data.message || 'Completed'),
          result: data.result,
        };

        optionsRef.current.onCompleted?.(task);

        // Auto-close connection on completion
        setTimeout(() => { unsubscribe(); }, 500);
      });

      // Listen for failed event
      eventSource.addEventListener('failed', (e: MessageEvent) => {
        const data = safeParseJSON(e.data);
        if (!data) return;

        console.error('❌ Failed event:', data);

        const task: TaskStatus = {
          task_id: String(data.id || ''),
          status: 'failed',
          progress: Number(data.progress) || 0,
          message: String(data.message || 'Failed'),
          error: String(data.error || data.message || 'Unknown error'),
        };

        optionsRef.current.onFailed?.(task);
        unsubscribe();
      });

      // Error handling
      eventSource.onerror = (e) => {
        console.error('❌ SSE connection error:', e);
        if (eventSource.readyState === EventSource.CLOSED) {
          isConnectedRef.current = false;
          optionsRef.current.onError?.(new Error('SSE connection closed unexpectedly'));
        }
      };

      return () => { unsubscribe(); };
    },
    [unsubscribe]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => { unsubscribe(); };
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
  const streamUrl = createApiUrl(`/tasks/${taskId}/stream`);

  const eventSource = new EventSource(streamUrl);

  eventSource.addEventListener('progress', (e: MessageEvent) => {
    const data = safeParseJSON(e.data);
    if (!data) return;

    callbacks.onProgress?.({
      task_id: String(data.id || ''),
      status: normalizeStatus(String(data.status || '')),
      progress: Number(data.progress) || 0,
      message: String(data.message || 'Processing...'),
    });
  });

  eventSource.addEventListener('completed', (e: MessageEvent) => {
    const data = safeParseJSON(e.data);
    if (!data) return;

    callbacks.onCompleted?.({
      task_id: String(data.id || ''),
      status: 'completed',
      progress: 100,
      message: String(data.message || 'Completed'),
      result: data.result,
    });
    eventSource.close();
  });

  eventSource.addEventListener('failed', (e: MessageEvent) => {
    const data = safeParseJSON(e.data);
    if (!data) return;

    callbacks.onFailed?.({
      task_id: String(data.id || ''),
      status: 'failed',
      progress: Number(data.progress) || 0,
      message: String(data.message || 'Failed'),
      error: String(data.error || data.message || 'Unknown error'),
    });
    eventSource.close();
  });

  eventSource.onerror = () => {
    if (eventSource.readyState === EventSource.CLOSED) {
      callbacks.onError?.(new Error('SSE connection closed unexpectedly'));
    }
  };

  return () => { eventSource.close(); };
}
