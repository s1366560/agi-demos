import { apiFetch } from './client/urlUtils';

export interface TaskSseEvent {
  event: string;
  data: string;
}

export interface TaskStreamHandlers {
  onOpen?: (() => void) | undefined;
  onProgress?: ((event: TaskSseEvent) => void) | undefined;
  onCompleted?: ((event: TaskSseEvent) => void) | undefined;
  onFailed?: ((event: TaskSseEvent) => void) | undefined;
  onError?: ((error: Error) => void) | undefined;
}

export function parseTaskSseEvent(rawEvent: string): TaskSseEvent | null {
  let event = 'message';
  const dataLines: string[] = [];

  for (const line of rawEvent.split(/\r?\n/)) {
    if (line.startsWith(':')) {
      continue;
    }
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  return {
    event,
    data: dataLines.join('\n'),
  };
}

function findEventSeparator(buffer: string): { index: number; length: number } | null {
  const lfIndex = buffer.indexOf('\n\n');
  const crlfIndex = buffer.indexOf('\r\n\r\n');

  if (lfIndex === -1 && crlfIndex === -1) {
    return null;
  }
  if (lfIndex === -1) {
    return { index: crlfIndex, length: 4 };
  }
  if (crlfIndex === -1) {
    return { index: lfIndex, length: 2 };
  }
  return crlfIndex < lfIndex ? { index: crlfIndex, length: 4 } : { index: lfIndex, length: 2 };
}

export async function streamTaskEvents(
  taskId: string,
  signal: AbortSignal,
  handlers: TaskStreamHandlers
): Promise<void> {
  const response = await apiFetch.get(`/tasks/${encodeURIComponent(taskId)}/stream`, {
    headers: {
      Accept: 'text/event-stream',
    },
    signal,
  });

  if (!response.body) {
    throw new Error('Task stream response has no body');
  }

  handlers.onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const consumeEvent = async (rawEvent: string): Promise<boolean> => {
    const event = parseTaskSseEvent(rawEvent);
    if (!event) {
      return false;
    }

    if (event.event === 'progress') {
      handlers.onProgress?.(event);
      return false;
    }
    if (event.event === 'completed') {
      handlers.onCompleted?.(event);
      await reader.cancel().catch(() => undefined);
      return true;
    }
    if (event.event === 'failed') {
      handlers.onFailed?.(event);
      await reader.cancel().catch(() => undefined);
      return true;
    }
    if (event.event === 'error') {
      handlers.onError?.(new Error(event.data));
      await reader.cancel().catch(() => undefined);
      return true;
    }

    return false;
  };

  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    let separator = findEventSeparator(buffer);
    while (separator) {
      const rawEvent = buffer.slice(0, separator.index);
      buffer = buffer.slice(separator.index + separator.length);
      if (await consumeEvent(rawEvent)) {
        return;
      }
      separator = findEventSeparator(buffer);
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    await consumeEvent(buffer);
  }
}

export function subscribeToTaskEvents(taskId: string, handlers: TaskStreamHandlers): () => void {
  const controller = new AbortController();

  void streamTaskEvents(taskId, controller.signal, handlers).catch((error: unknown) => {
    if (controller.signal.aborted) {
      return;
    }
    handlers.onError?.(error instanceof Error ? error : new Error(String(error)));
  });

  return () => {
    controller.abort();
  };
}
