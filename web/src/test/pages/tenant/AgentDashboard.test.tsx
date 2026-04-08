import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentDashboard } from '../../../pages/tenant/AgentDashboard';

const {
  mockCanModifyConfig,
  mockGetTraceChain,
  mockGetTenantActiveRunCount,
  mockListTenantRuns,
  mockTimelineRun,
} = vi.hoisted(() => ({
    mockCanModifyConfig: vi.fn(),
    mockGetTraceChain: vi.fn(),
    mockGetTenantActiveRunCount: vi.fn(),
    mockListTenantRuns: vi.fn(),
    mockTimelineRun: { current: null as Record<string, unknown> | null },
  }));

vi.mock('../../../services/agentConfigService', () => ({
  agentConfigService: {
    canModifyConfig: mockCanModifyConfig,
  },
}));

vi.mock('../../../stores/tenant', () => ({
  useTenantStore: (selector: (state: { currentTenant: { id: string } | null }) => unknown) =>
    selector({ currentTenant: null }),
}));

vi.mock('../../../services/traceService', () => ({
  traceAPI: {
    listTenantRuns: mockListTenantRuns,
    getTenantActiveRunCount: mockGetTenantActiveRunCount,
    getTraceChain: mockGetTraceChain,
  },
}));

vi.mock('../../../components/agent/TenantAgentConfigView', () => ({
  TenantAgentConfigView: ({
    tenantId,
    canEdit,
    onEdit,
  }: {
    tenantId: string;
    canEdit: boolean;
    onEdit?: () => void;
  }) => (
    <div data-testid="tenant-config-view">
      <span>{tenantId}</span>
      <span>{canEdit ? 'editable' : 'readonly'}</span>
      {onEdit ? <button onClick={onEdit}>Open editor</button> : null}
    </div>
  ),
}));

vi.mock('../../../components/agent/TenantAgentConfigEditor', () => ({
  TenantAgentConfigEditor: ({ open }: { open: boolean }) =>
    open ? <div data-testid="tenant-config-editor">Editor open</div> : null,
}));

vi.mock('../../../components/agent/multiAgent/TraceChainView', () => ({
  TraceChainView: ({ data }: { data: unknown }) => (
    <div data-testid="trace-chain-view">{JSON.stringify(data)}</div>
  ),
}));

vi.mock('../../../components/agent/multiAgent/TraceTimeline', () => ({
  TraceTimeline: ({ onSelectRun }: { onSelectRun?: (run: unknown) => void }) => (
    <div data-testid="trace-timeline">
      TraceTimeline
      <button
        type="button"
        onClick={() => {
          if (mockTimelineRun.current) {
            onSelectRun?.(mockTimelineRun.current);
          }
        }}
      >
        Select trace
      </button>
    </div>
  ),
}));

function DashboardHarness() {
  const navigate = useNavigate();

  return (
    <>
      <button
        type="button"
        onClick={() => {
          navigate('/tenant/tenant-456/agents');
        }}
      >
        Switch tenant
      </button>
      <AgentDashboard />
    </>
  );
}

describe('AgentDashboard', () => {
  const renderDashboard = async (initialPath = '/tenant/tenant-123/agents') => {
    render(
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/tenant/:tenantId/agents" element={<DashboardHarness />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(mockCanModifyConfig).toHaveBeenCalled();
    });
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockTimelineRun.current = null;
    mockCanModifyConfig.mockResolvedValue(true);
    mockListTenantRuns.mockResolvedValue({ tenant_id: 'tenant-123', runs: [], total: 0 });
    mockGetTenantActiveRunCount.mockResolvedValue({ tenant_id: 'tenant-123', active_count: 0 });
    mockGetTraceChain.mockResolvedValue({
      trace_id: 'trace-1',
      conversation_id: 'conv-1',
      runs: [],
      total: 0,
    });
  });

  it('renders the focused configuration page structure', async () => {
    await renderDashboard();

    expect(screen.getByRole('heading', { name: 'Agent Configuration' })).toBeInTheDocument();
    expect(screen.getByText('Tenant runtime policy')).toBeInTheDocument();
    expect(await screen.findByTestId('tenant-config-view')).toBeInTheDocument();
  });

  it('renders related navigation links for real configuration surfaces', async () => {
    await renderDashboard();

    expect(screen.getByText('Agent Workspace').closest('a')).toHaveAttribute(
      'href',
      '/tenant/tenant-123/agent-workspace'
    );
    expect(screen.getByText('Agent Definitions').closest('a')).toHaveAttribute(
      'href',
      '/tenant/tenant-123/agent-definitions'
    );
    expect(screen.getByText('Agent Bindings').closest('a')).toHaveAttribute(
      'href',
      '/tenant/tenant-123/agent-bindings'
    );
  });

  it('opens the configuration editor from the live config surface', async () => {
    await renderDashboard();

    fireEvent.click(await screen.findByRole('button', { name: 'Open editor' }));

    expect(screen.getByTestId('tenant-config-editor')).toBeInTheDocument();
  });

  it('shows an operational empty state when there are no real traces', async () => {
    await renderDashboard();

    expect(mockListTenantRuns).toHaveBeenCalledWith('tenant-123', { limit: 20 });
    expect(screen.getByText('No runtime traces yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Agent Workspace' })).toHaveAttribute(
      'href',
      '/tenant/tenant-123/agent-workspace'
    );
  });

  it('renders the real trace timeline when tenant runs exist on a fresh load', async () => {
    mockListTenantRuns.mockResolvedValue({
      tenant_id: 'tenant-123',
      runs: [{ run_id: 'run-1', conversation_id: 'conv-1', trace_id: 'trace-1' }],
      total: 1,
    });

    await renderDashboard();

    expect(await screen.findByTestId('trace-timeline')).toBeInTheDocument();
    expect(screen.queryByText('No runtime traces yet')).not.toBeInTheDocument();
  });

  it('shows the active run badge when executions are in flight', async () => {
    mockGetTenantActiveRunCount.mockResolvedValue({ tenant_id: 'tenant-123', active_count: 2 });

    await renderDashboard();

    expect(screen.getByText('2 active runs')).toBeInTheDocument();
  });

  it('keeps trace results visible when active run count loading fails', async () => {
    mockListTenantRuns.mockResolvedValue({
      tenant_id: 'tenant-123',
      runs: [{ run_id: 'run-1', conversation_id: 'conv-1', trace_id: 'trace-1' }],
      total: 1,
    });
    mockGetTenantActiveRunCount.mockRejectedValue(new Error('count unavailable'));

    await renderDashboard();

    expect(await screen.findByTestId('trace-timeline')).toBeInTheDocument();
    expect(screen.queryByText('No runtime traces yet')).not.toBeInTheDocument();
    expect(screen.queryByText('Unable to load runtime traces')).not.toBeInTheDocument();
  });

  it('clears trace feedback when navigating to another tenant', async () => {
    mockListTenantRuns.mockImplementation(async (tenantId: string) => {
      if (tenantId === 'tenant-123') {
        return {
          tenant_id: tenantId,
          runs: [{ run_id: 'run-1', conversation_id: 'conv-1', trace_id: 'trace-1' }],
          total: 1,
        };
      }

      return { tenant_id: tenantId, runs: [], total: 0 };
    });
    mockGetTenantActiveRunCount.mockImplementation(async (tenantId: string) => ({
      tenant_id: tenantId,
      active_count: tenantId === 'tenant-123' ? 1 : 0,
    }));

    await renderDashboard();
    expect(await screen.findByTestId('trace-timeline')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Switch tenant' }));

    await waitFor(() => {
      expect(mockListTenantRuns).toHaveBeenCalledWith('tenant-456', { limit: 20 });
    });
    expect(await screen.findByText('No runtime traces yet')).toBeInTheDocument();
    expect(screen.queryByTestId('trace-timeline')).not.toBeInTheDocument();
  });

  it('removes the previous mock dashboard content', async () => {
    await renderDashboard();

    expect(screen.queryByText('Code Architect')).not.toBeInTheDocument();
    expect(screen.queryByText('Standard Skill Registry')).not.toBeInTheDocument();
    expect(screen.queryByText('Auto-Learning Experience Engine')).not.toBeInTheDocument();
  });

  it('shows a single-run fallback when the selected run has no trace id', async () => {
    const run = {
      run_id: 'run-untraced-1',
      conversation_id: 'conv-1',
      subagent_name: 'child-agent',
      task: 'Inspect trace fallback',
      status: 'completed',
      created_at: '2025-01-01T00:00:00Z',
      started_at: '2025-01-01T00:00:01Z',
      ended_at: '2025-01-01T00:00:02Z',
      summary: 'done',
      error: null,
      execution_time_ms: 1000,
      tokens_used: 42,
      metadata: {},
      frozen_result_text: null,
      frozen_at: null,
      trace_id: null,
      parent_span_id: null,
    };
    mockTimelineRun.current = run;
    mockListTenantRuns.mockResolvedValue({
      tenant_id: 'tenant-123',
      runs: [run],
      total: 1,
    });

    await renderDashboard();
    fireEvent.click(screen.getByRole('button', { name: 'Select trace' }));

    await waitFor(() => {
      expect(screen.getByTestId('trace-chain-view')).toBeInTheDocument();
    });
    expect(mockGetTraceChain).not.toHaveBeenCalled();
    expect(screen.getByTestId('trace-chain-view')).toHaveTextContent('run-untraced-1');
  });

  it('shows a retryable error state when trace chain loading fails for a traced run', async () => {
    const run = {
      run_id: 'run-traced-1',
      conversation_id: 'conv-1',
      subagent_name: 'builtin:sisyphus',
      task: 'Reply with trace details',
      status: 'completed',
      created_at: '2025-01-01T00:00:00Z',
      started_at: '2025-01-01T00:00:01Z',
      ended_at: '2025-01-01T00:00:02Z',
      summary: null,
      error: null,
      execution_time_ms: 1000,
      tokens_used: 42,
      metadata: {},
      frozen_result_text: null,
      frozen_at: null,
      trace_id: 'trace-1',
      parent_span_id: null,
    };
    mockTimelineRun.current = run;
    mockListTenantRuns.mockResolvedValue({
      tenant_id: 'tenant-123',
      runs: [run],
      total: 1,
    });
    mockGetTraceChain.mockRejectedValue(new Error('chain unavailable'));

    await renderDashboard();
    fireEvent.click(screen.getByRole('button', { name: 'Select trace' }));

    expect(await screen.findByText('Failed to load trace details')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry loading trace' })).toBeInTheDocument();
    expect(screen.queryByTestId('trace-chain-view')).not.toBeInTheDocument();
  });

  it('keeps the memoized component export available', async () => {
    const module = await import('../../../pages/tenant/AgentDashboard');
    expect(module.AgentDashboard).toBeDefined();
  });

  it('retains heading hierarchy for the operational feedback section', async () => {
    await renderDashboard();

    const heading = screen.getByRole('heading', {
      name: 'Validate policy changes against live runs',
    });
    expect(heading.tagName).toBe('H2');
  });
});
