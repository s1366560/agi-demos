import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useMCPStore } from '../../stores/mcp';

import type { MCPServerResponse } from '../../types/agent';

vi.mock('../../services/mcpService', () => ({
  mcpAPI: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    toggleEnabled: vi.fn(),
    sync: vi.fn(),
    test: vi.fn(),
    listAllTools: vi.fn(),
  },
}));

import { mcpAPI } from '../../services/mcpService';

const mockedAPI = vi.mocked(mcpAPI);

/** ApiError-shaped error: statusCode lives on the error itself. */
function makeApiError(statusCode: number, message: string): Error {
  const error = new Error(message) as Error & { statusCode: number };
  error.statusCode = statusCode;
  return error;
}

/** Axios-shaped error: statusCode lives on error.response.status. */
function makeAxiosError(status: number, message: string): Error {
  const error = new Error(message) as Error & {
    response: { status: number; data?: { detail?: string } };
  };
  error.response = { status, data: { detail: message } };
  return error;
}

const makeServer = (id: string): MCPServerResponse =>
  ({
    id,
    name: `server-${id}`,
    server_type: 'stdio',
    enabled: true,
    discovered_tools: [],
  }) as unknown as MCPServerResponse;

describe('useMCPStore errorStatusCode (W-1)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useMCPStore.getState().reset();
  });

  it('initializes errorStatusCode as null', () => {
    expect(useMCPStore.getState().errorStatusCode).toBeNull();
    expect(useMCPStore.getState().error).toBeNull();
  });

  it('captures 403 from an ApiError-shaped error so UI can classify forbidden', async () => {
    mockedAPI.list.mockRejectedValueOnce(makeApiError(403, 'Forbidden'));

    await expect(useMCPStore.getState().listServers()).rejects.toThrow('Forbidden');

    const state = useMCPStore.getState();
    expect(state.error).toBe('Forbidden');
    expect(state.errorStatusCode).toBe(403);
  });

  it('captures 409 from an axios-shaped error so UI can classify conflict', async () => {
    mockedAPI.create.mockRejectedValueOnce(makeAxiosError(409, 'Server name already exists'));

    await expect(
      useMCPStore.getState().createServer({ name: 'dup' } as never)
    ).rejects.toThrow('Server name already exists');

    const state = useMCPStore.getState();
    expect(state.errorStatusCode).toBe(409);
    expect(state.error).toBe('Server name already exists');
  });

  it('captures 500 from sync failures', async () => {
    mockedAPI.sync.mockRejectedValueOnce(makeAxiosError(500, 'Internal error'));

    await expect(useMCPStore.getState().syncServer('srv-1')).rejects.toThrow('Internal error');

    expect(useMCPStore.getState().errorStatusCode).toBe(500);
  });

  it('falls back to null when the error carries no status code', async () => {
    mockedAPI.list.mockRejectedValueOnce(new Error('Network down'));

    await expect(useMCPStore.getState().listServers()).rejects.toThrow('Network down');

    const state = useMCPStore.getState();
    expect(state.error).toBe('Network down');
    expect(state.errorStatusCode).toBeNull();
  });

  it('clearError resets both error and errorStatusCode', async () => {
    mockedAPI.list.mockRejectedValueOnce(makeApiError(403, 'Forbidden'));
    await expect(useMCPStore.getState().listServers()).rejects.toThrow('Forbidden');
    expect(useMCPStore.getState().errorStatusCode).toBe(403);

    useMCPStore.getState().clearError();

    expect(useMCPStore.getState().error).toBeNull();
    expect(useMCPStore.getState().errorStatusCode).toBeNull();
  });

  it('a successful action after an error clears the stale status code', async () => {
    mockedAPI.list.mockRejectedValueOnce(makeApiError(409, 'Conflict'));
    await expect(useMCPStore.getState().listServers()).rejects.toThrow('Conflict');
    expect(useMCPStore.getState().errorStatusCode).toBe(409);

    mockedAPI.list.mockResolvedValueOnce([makeServer('srv-1')]);
    await useMCPStore.getState().listServers();

    const state = useMCPStore.getState();
    expect(state.error).toBeNull();
    expect(state.errorStatusCode).toBeNull();
    expect(state.servers).toHaveLength(1);
  });

  it('drives the McpServerTabV2 error-state classification contract', async () => {
    // Mirrors McpServerTabV2.tsx: errorStatusCode === 403 ? 'forbidden' : 409 ? 'conflict' : 'error'
    const classify = (code: number | null) =>
      code === 403 ? 'forbidden' : code === 409 ? 'conflict' : 'error';

    mockedAPI.list.mockRejectedValueOnce(makeApiError(403, 'nope'));
    await expect(useMCPStore.getState().listServers()).rejects.toThrow('nope');
    expect(classify(useMCPStore.getState().errorStatusCode)).toBe('forbidden');

    useMCPStore.getState().clearError();
    mockedAPI.list.mockRejectedValueOnce(makeApiError(409, 'dup'));
    await expect(useMCPStore.getState().listServers()).rejects.toThrow('dup');
    expect(classify(useMCPStore.getState().errorStatusCode)).toBe('conflict');

    useMCPStore.getState().clearError();
    mockedAPI.list.mockRejectedValueOnce(makeAxiosError(500, 'boom'));
    await expect(useMCPStore.getState().listServers()).rejects.toThrow('boom');
    expect(classify(useMCPStore.getState().errorStatusCode)).toBe('error');
  });
});
