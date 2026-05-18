import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  buildDesktopWebSocketProtocols,
  buildDesktopWebSocketUrl,
  getApiHost,
} from '../../services/sandboxWebSocketUtils';

describe('sandboxWebSocketUtils', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    window.history.pushState({}, '', 'http://localhost:3000/');
  });

  it('uses the FastAPI dev server host from the Vite dev server', () => {
    window.history.pushState({}, '', 'http://localhost:3000/tenant/agent-workspace');

    expect(getApiHost()).toBe('localhost:8000');
    expect(buildDesktopWebSocketUrl('project-1')).toBe(
      'ws://localhost:8000/api/v1/projects/project-1/sandbox/desktop/proxy/websockify'
    );
  });

  it('uses an explicit sandbox API host when configured', () => {
    vi.stubEnv('VITE_API_HOST', 'api.example.test');
    window.history.pushState({}, '', 'http://localhost:3000/tenant/agent-workspace');

    expect(getApiHost()).toBe('api.example.test');
    expect(buildDesktopWebSocketUrl('project-1')).toBe(
      'ws://api.example.test/api/v1/projects/project-1/sandbox/desktop/proxy/websockify'
    );
  });

  it('includes binary plus auth protocols for KasmVNC desktop sockets', () => {
    expect(buildDesktopWebSocketProtocols('ms_sk_test')).toEqual([
      'binary',
      'memstack.auth',
      'ms_sk_test',
    ]);
  });
});
