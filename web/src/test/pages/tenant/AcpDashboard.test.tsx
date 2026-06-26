import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AcpDashboard } from '@/pages/tenant/AcpDashboard';

import { ACP_SECRET_UNCHANGED_SENTINEL } from '@/types/acp';

import type { TenantACPStatus, TenantACPTestResponse } from '@/types/acp';

const acpServiceMock = vi.hoisted(() => ({
  getStatus: vi.fn(),
  listRunnerPools: vi.fn(),
  updateAgent: vi.fn(),
  testAgent: vi.fn(),
}));

vi.mock('@/services/acpService', () => ({
  acpService: acpServiceMock,
}));

vi.mock('@/stores/tenant', () => ({
  useTenantStore: (selector: (state: { currentTenant: { id: string; name: string } | null }) => unknown) =>
    selector({ currentTenant: null }),
}));

function statusFixture(overrides: Partial<TenantACPStatus> = {}): TenantACPStatus {
  return {
    enabled: true,
    websocketEnabled: true,
    httpBaseUrl: 'http://127.0.0.1:8000',
    externalAgentsConfigPath: null,
    agentCount: 1,
    availableCount: 1,
    missingEnvCount: 0,
    activeSessionCount: 0,
    agents: [
      {
        id: 'agent-row-1',
        agentKey: 'local-acp',
        name: 'Local ACP',
        transport: 'stdio',
        command: 'uv',
        args: ['run', 'python', '-m', 'agent'],
        url: null,
        env: {
          ACP_API_KEY: {
            type: 'secret',
            value: ACP_SECRET_UNCHANGED_SENTINEL,
            has_value: true,
          },
        },
        headers: {},
        enabled: true,
        source: 'tenant',
        available: true,
        missingEnv: [],
        activeSessions: 0,
        totalSessions: 1,
        promptCount: 1,
        updateCount: 2,
        lastLatencyMs: 18,
        lastError: null,
        lastActivity: '2026-06-24T12:00:00Z',
        createdAt: '2026-06-24T11:00:00Z',
        updatedAt: '2026-06-24T12:00:00Z',
      },
    ],
    sessions: [],
    recentEvents: [
      {
        tenant_id: 'tenant-1',
        agent_id: 'local-acp',
        action: 'session/prompt',
        status: 'success',
        timestamp: '2026-06-24T12:00:00Z',
        duration_ms: 18,
        error: null,
      },
    ],
    ...overrides,
  };
}

function renderDashboard(path = '/tenant/tenant-1/acp') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/tenant/:tenantId/acp" element={<AcpDashboard />} />
        <Route path="/acp" element={<AcpDashboard />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('AcpDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    acpServiceMock.getStatus.mockResolvedValue(statusFixture());
    acpServiceMock.listRunnerPools.mockResolvedValue([]);
    acpServiceMock.updateAgent.mockResolvedValue(statusFixture().agents[0]);
    acpServiceMock.testAgent.mockResolvedValue({
      success: true,
      sessionId: 'session-1',
      remoteSessionId: 'remote-session-1',
      assistantText: 'PONG',
      updatesCount: 1,
      durationMs: 42,
      error: null,
    } satisfies TenantACPTestResponse);
  });

  it('loads tenant ACP status and renders configured agents', async () => {
    renderDashboard();

    expect(await screen.findByText('Local ACP')).toBeInTheDocument();
    expect(acpServiceMock.getStatus).toHaveBeenCalledWith('tenant-1');
    expect(screen.getByText('local-acp')).toBeInTheDocument();
    expect(screen.getByText('18 ms')).toBeInTheDocument();
  });

  it('submits sentinel values when editing a stored secret without replacing it', async () => {
    renderDashboard();

    await screen.findByText('Local ACP');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(acpServiceMock.updateAgent).toHaveBeenCalledWith(
        'tenant-1',
        'local-acp',
        expect.objectContaining({
          env: {
            ACP_API_KEY: {
              type: 'secret',
              value: ACP_SECRET_UNCHANGED_SENTINEL,
            },
          },
        })
      );
    });
  });

  it('runs a smoke test and shows the assistant text summary', async () => {
    renderDashboard();

    await screen.findByText('Local ACP');
    fireEvent.click(screen.getByRole('button', { name: 'tenant.acp.actions.test' }));
    fireEvent.click(screen.getByRole('button', { name: 'tenant.acp.actions.runTest' }));

    await waitFor(() => {
      expect(acpServiceMock.testAgent).toHaveBeenCalledWith(
        'tenant-1',
        'local-acp',
        expect.objectContaining({
          cwd: '/tmp',
          prompt: '请只回复 PONG',
          timeoutSeconds: 30,
        })
      );
    });
    expect(await screen.findByText('PONG')).toBeInTheDocument();
  });
});
