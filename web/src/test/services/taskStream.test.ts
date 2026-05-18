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
    apiFetchMock.get.mockResolvedValue({ body });
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
