import type { TaskStreamHandlers } from '../../../../../web/src/services/taskStream';

export function subscribeToTaskEvents(id: string, handlers: TaskStreamHandlers) {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  async function poll() {
    try {
      const task = (await window.memstack.invoke(
        'index-status',
        { id },
        { signal: controller.signal },
      )) as { status: string };
      if (controller.signal.aborted) return;
      const status = task.status.toLowerCase();
      const event = { event: status, data: JSON.stringify(task) };
      if (status === 'completed') handlers.onCompleted?.(event);
      else if (['failed', 'stopped', 'cancelled'].includes(status)) handlers.onFailed?.(event);
      else {
        handlers.onProgress?.(event);
        timer = setTimeout(poll, 1500);
      }
    } catch (cause) {
      if (!controller.signal.aborted)
        handlers.onError?.(cause instanceof Error ? cause : new Error(String(cause)));
    }
  }
  void poll();
  return () => {
    controller.abort();
    clearTimeout(timer);
  };
}
