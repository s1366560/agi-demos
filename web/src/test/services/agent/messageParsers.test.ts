import { describe, expect, it } from 'vitest';

import { parseSandboxStateData } from '../../../services/agent/messageParsers';

describe('parseSandboxStateData', () => {
  it('preserves desktop and terminal service fields from sandbox_event payloads', () => {
    const terminalState = parseSandboxStateData({
      type: 'sandbox_event',
      data: {
        type: 'terminal_status',
        data: {
          sandbox_id: 'sandbox-1',
          running: true,
          url: 'ws://localhost:7681',
          port: 7681,
          session_id: 'session-1',
          pid: 42,
        },
      },
    } as any);

    expect(terminalState).toMatchObject({
      eventType: 'terminal_status',
      sandboxId: 'sandbox-1',
      running: true,
      url: 'ws://localhost:7681',
      port: 7681,
      sessionId: 'session-1',
      pid: 42,
    });
  });

  it('maps HTTP preview proxy fields from backend event names', () => {
    const httpState = parseSandboxStateData({
      type: 'sandbox_event',
      data: {
        type: 'http_service_started',
        data: {
          service_id: 'dev-server',
          service_name: 'Dev Server',
          source_type: 'sandbox_internal',
          service_url: 'http://172.17.0.2:5173',
          proxy_url: '/api/v1/projects/project-1/sandbox/http-services/dev-server/proxy/',
          ws_proxy_url: '/api/v1/projects/project-1/sandbox/http-services/dev-server/proxy/ws/',
          auto_open: true,
        },
      },
    } as any);

    expect(httpState).toMatchObject({
      eventType: 'http_service_started',
      serviceId: 'dev-server',
      previewUrl: '/api/v1/projects/project-1/sandbox/http-services/dev-server/proxy/',
      wsPreviewUrl: '/api/v1/projects/project-1/sandbox/http-services/dev-server/proxy/ws/',
      autoOpen: true,
    });
  });
});
