import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/client/urlUtils', () => ({
  apiFetch: {
    get: vi.fn(),
  },
}));

import { apiFetch } from '@/services/client/urlUtils';

import {
  parseDeployProgressSseEvent,
  streamDeployProgress,
} from '../../../pages/tenant/deployProgressStream';

describe('parseDeployProgressSseEvent', () => {
  beforeEach(() => {
    vi.mocked(apiFetch.get).mockReset();
  });

  it('parses deploy progress SSE data lines', () => {
    expect(
      parseDeployProgressSseEvent(
        'data: {"type":"status","status":"in_progress","deploy_id":"deploy-1"}\n\n'
      )
    ).toEqual({
      type: 'status',
      status: 'in_progress',
      deploy_id: 'deploy-1',
    });
  });

  it('ignores keepalives and malformed data', () => {
    expect(parseDeployProgressSseEvent(': keepalive\n\n')).toBeNull();
    expect(parseDeployProgressSseEvent('data: not-json\n\n')).toBeNull();
    expect(parseDeployProgressSseEvent('data: {"status":"missing-type"}\n\n')).toBeNull();
  });

  it('streams progress through apiFetch so auth and 401 handling stay centralized', async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"status","status":"in_progress","deploy_id":"deploy-1"}\n\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"done","status":"success","deploy_id":"deploy-1"}\n\n'
          )
        );
        controller.close();
      },
    });
    vi.mocked(apiFetch.get).mockResolvedValueOnce(new Response(stream));
    const events: unknown[] = [];

    await streamDeployProgress({
      deployId: 'deploy 1',
      signal: new AbortController().signal,
      onEvent: (event) => events.push(event),
    });

    expect(apiFetch.get).toHaveBeenCalledWith('/deploys/deploy%201/progress', {
      headers: { Accept: 'text/event-stream' },
      signal: expect.any(AbortSignal),
    });
    expect(events).toEqual([
      {
        type: 'status',
        status: 'in_progress',
        deploy_id: 'deploy-1',
      },
      {
        type: 'done',
        status: 'success',
        deploy_id: 'deploy-1',
      },
    ]);
  });

  it('streams CRLF-delimited progress events as separate frames', async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"status","status":"in_progress","deploy_id":"deploy-1"}\r\n\r\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"done","status":"success","deploy_id":"deploy-1"}\r\n\r\n'
          )
        );
        controller.close();
      },
    });
    vi.mocked(apiFetch.get).mockResolvedValueOnce(new Response(stream));
    const events: unknown[] = [];

    await streamDeployProgress({
      deployId: 'deploy-1',
      signal: new AbortController().signal,
      onEvent: (event) => events.push(event),
    });

    expect(events).toEqual([
      {
        type: 'status',
        status: 'in_progress',
        deploy_id: 'deploy-1',
      },
      {
        type: 'done',
        status: 'success',
        deploy_id: 'deploy-1',
      },
    ]);
  });
});
