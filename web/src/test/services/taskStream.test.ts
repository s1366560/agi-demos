import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetchMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock('../../services/client/urlUtils', () => ({
  apiFetch: apiFetchMock,
}));

import { parseTaskSseEvent, streamTaskEvents } from '../../services/taskStream';

describe('parseTaskSseEvent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('parses named SSE events with JSON data', () => {
    expect(parseTaskSseEvent('event: progress\ndata: {"id":"task-1","progress":50}\n\n')).toEqual({
      event: 'progress',
      data: '{"id":"task-1","progress":50}',
    });
  });

  it('ignores keepalive comments and preserves multiline data', () => {
    expect(parseTaskSseEvent(': keepalive\n\n')).toBeNull();
    expect(parseTaskSseEvent('event: progress\ndata: line-1\ndata: line-2\n\n')).toEqual({
      event: 'progress',
      data: 'line-1\nline-2',
    });
  });

  it('streams CRLF-delimited events as separate task updates', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(
          encoder.encode(
            'event: progress\r\n' +
              'data: {"id":"task-1","progress":10}\r\n' +
              '\r\n' +
              'event: completed\r\n' +
              'data: {"id":"task-1","progress":100}\r\n' +
              '\r\n'
          )
        );
        controller.close();
      },
    });
    apiFetchMock.get.mockImplementation(async (...args: any[]) =>
      args[1](
        { body },
        {
          signal: args[2]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );
    const onProgress = vi.fn();
    const onCompleted = vi.fn();

    await streamTaskEvents('task-1', new AbortController().signal, {
      onProgress,
      onCompleted,
    });

    expect(onProgress).toHaveBeenCalledWith({
      event: 'progress',
      data: '{"id":"task-1","progress":10}',
    });
    expect(onCompleted).toHaveBeenCalledWith({
      event: 'completed',
      data: '{"id":"task-1","progress":100}',
    });
  });
});

it('suppresses late SSE chunks after cancellation and releases the reader lock', async () => {
  let streamController!: ReadableStreamDefaultController<Uint8Array>;
  let resolveRead!: () => void;
  const reading = new Promise<void>((resolve) => {
    resolveRead = resolve;
  });
  const cancelled = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      streamController = controller;
    },
    pull() {
      resolveRead();
    },
    cancel: cancelled,
  });
  apiFetchMock.get.mockImplementation(async (_url, consume, options) =>
    consume(
      { body },
      {
        signal: options.signal,
        check() {
          if (options.signal.aborted) throw new DOMException('cancelled', 'AbortError');
        },
      }
    )
  );
  const controller = new AbortController();
  const onProgress = vi.fn();
  const task = streamTaskEvents('task-1', controller.signal, { onProgress });
  const rejection = expect(task).rejects.toMatchObject({ name: 'AbortError' });
  await reading;
  controller.abort();
  streamController.enqueue(new TextEncoder().encode('event: progress\ndata: stale\n\n'));
  await rejection;
  expect(onProgress).not.toHaveBeenCalled();
  expect(cancelled).toHaveBeenCalledOnce();
  expect(body.locked).toBe(false);
});
