import { beforeEach, describe, expect, it, vi } from 'vitest';

import { acpService } from '@/services/acpService';
import { httpClient } from '@/services/client/httpClient';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('acpService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads tenant ACP status from the tenant API surface', async () => {
    vi.mocked(httpClient.get).mockResolvedValueOnce({
      enabled: true,
      websocketEnabled: true,
      httpBaseUrl: 'http://127.0.0.1:8000',
      agentCount: 0,
      availableCount: 0,
      missingEnvCount: 0,
      activeSessionCount: 0,
      agents: [],
      sessions: [],
      recentEvents: [],
    });

    await acpService.getStatus('tenant-1');

    expect(httpClient.get).toHaveBeenCalledWith('/acp/tenants/tenant-1/status');
  });

  it('creates, updates, tests, and closes external ACP agents with expected paths', async () => {
    vi.mocked(httpClient.post).mockResolvedValue({});
    vi.mocked(httpClient.put).mockResolvedValue({});
    vi.mocked(httpClient.delete).mockResolvedValue({ ok: true });

    await acpService.createAgent('tenant-1', {
      agentKey: 'local',
      name: 'Local',
      transport: 'stdio',
    });
    await acpService.updateAgent('tenant-1', 'local', {
      name: 'Local',
      transport: 'websocket',
      url: 'ws://localhost/acp',
    });
    await acpService.testAgent('tenant-1', 'local', {
      cwd: '/tmp',
      prompt: 'PONG',
    });
    await acpService.closeSession('tenant-1', 'local', 'session-1');

    expect(httpClient.post).toHaveBeenNthCalledWith(
      1,
      '/acp/tenants/tenant-1/external-agents',
      expect.objectContaining({ agentKey: 'local' })
    );
    expect(httpClient.put).toHaveBeenCalledWith(
      '/acp/tenants/tenant-1/external-agents/local',
      expect.objectContaining({ url: 'ws://localhost/acp' })
    );
    expect(httpClient.post).toHaveBeenNthCalledWith(
      2,
      '/acp/tenants/tenant-1/external-agents/local/test',
      expect.objectContaining({ cwd: '/tmp' })
    );
    expect(httpClient.delete).toHaveBeenCalledWith(
      '/acp/tenants/tenant-1/external-agents/local/sessions/session-1'
    );
  });
});
