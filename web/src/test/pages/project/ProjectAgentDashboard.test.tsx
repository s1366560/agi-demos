import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProjectAgentDashboard } from '@/pages/project/ProjectAgentDashboard';
import { ProjectAgentLogs } from '@/pages/project/ProjectAgentLogs';
import { ApiError, ApiErrorType } from '@/services/client/ApiError';
import { ProjectAgentContractError } from '@/services/projectAgentService';

const { listRuns, getActiveRunCount } = vi.hoisted(() => ({
  listRuns: vi.fn(),
  getActiveRunCount: vi.fn(),
}));

vi.mock('@/services/projectAgentService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/projectAgentService')>();
  return {
    ...actual,
    projectAgentService: {
      ...actual.projectAgentService,
      listRuns,
      getActiveRunCount,
    },
  };
});

function renderDashboard() {
  return render(
    <MemoryRouter initialEntries={['/tenant/tenant-1/project/project-1/agent']}>
      <Routes>
        <Route
          path="/tenant/:tenantId/project/:projectId/agent"
          element={<ProjectAgentDashboard />}
        />
      </Routes>
    </MemoryRouter>
  );
}

function renderLogs() {
  return render(
    <MemoryRouter initialEntries={['/tenant/tenant-1/project/project-1/agent/logs']}>
      <Routes>
        <Route
          path="/tenant/:tenantId/project/:projectId/agent/logs"
          element={<ProjectAgentLogs />}
        />
      </Routes>
    </MemoryRouter>
  );
}

describe('ProjectAgentDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listRuns.mockResolvedValue({ project_id: 'project-1', runs: [], total: 0 });
    getActiveRunCount.mockResolvedValue({ project_id: 'project-1', active_count: 0 });
  });

  it('renders project-scoped trace metrics and canonical links', async () => {
    getActiveRunCount.mockResolvedValue({ project_id: 'project-1', active_count: 2 });

    const { container } = renderDashboard();

    await waitFor(() => {
      expect(listRuns).toHaveBeenCalledWith('project-1', { limit: 8 });
      expect(getActiveRunCount).toHaveBeenCalledWith('project-1');
    });
    expect(
      container.querySelector('a[href="/tenant/tenant-1/project/project-1/agent/patterns"]')
    ).toBeInTheDocument();
    expect(
      container.querySelector('a[href="/tenant/tenant-1/project/project-1/agent/logs"]')
    ).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('preserves a fail-closed trace contract reason code', async () => {
    listRuns.mockRejectedValue(new ProjectAgentContractError('project_agent_trace_scope_conflict'));

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveAttribute(
        'data-reason-code',
        'project_agent_trace_scope_conflict'
      );
    });
  });

  it('keeps permission failures distinct from unavailable authority', async () => {
    listRuns.mockRejectedValue(
      new ApiError(ApiErrorType.AUTHORIZATION, 'FORBIDDEN', 'Forbidden', 403)
    );

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveAttribute(
        'data-reason-code',
        'project_agent_trace_forbidden'
      );
    });
  });
});

describe('ProjectAgentLogs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listRuns.mockResolvedValue({ project_id: 'project-1', runs: [], total: 0 });
    getActiveRunCount.mockResolvedValue({ project_id: 'project-1', active_count: 0 });
  });

  it('reloads project-scoped runs through the selected status contract', async () => {
    const { container } = renderLogs();

    await waitFor(() => {
      expect(listRuns).toHaveBeenCalledWith('project-1', { limit: 100 });
    });

    const statusSelect = container.querySelector('#run-status-filter');
    expect(statusSelect).toBeInTheDocument();
    fireEvent.change(statusSelect!, { target: { value: 'running' } });

    await waitFor(() => {
      expect(listRuns).toHaveBeenLastCalledWith('project-1', {
        status: 'running',
        limit: 100,
      });
    });
  });
});
