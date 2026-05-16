import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { UnifiedRuntimes } from '../../../pages/tenant/UnifiedRuntimes';
import { poolService } from '../../../services/poolService';
import { projectSandboxService } from '../../../services/projectSandboxService';
import { render, screen, waitFor } from '../../utils';

import type { PoolInstance, PoolStatus } from '../../../services/poolService';
import type { ProjectSandbox, SandboxStats } from '../../../services/projectSandboxService';

vi.mock('../../../services/poolService', () => ({
  poolService: {
    getStatus: vi.fn(),
    listInstances: vi.fn(),
  },
}));

vi.mock('../../../services/projectSandboxService', () => ({
  projectSandboxService: {
    getStats: vi.fn(),
    listProjectSandboxes: vi.fn(),
  },
}));

function renderUnifiedRuntimes() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <Routes>
        <Route path="/tenant/:tenantId/runtimes" element={<UnifiedRuntimes />} />
      </Routes>
    </QueryClientProvider>,
    { route: '/tenant/tenant-1/runtimes' }
  );
}

describe('UnifiedRuntimes', () => {
  const poolStatus: PoolStatus = {
    enabled: true,
    status: 'ready',
    total_instances: 1,
    hot_instances: 1,
    warm_instances: 0,
    cold_instances: 0,
    ready_instances: 1,
    executing_instances: 0,
    unhealthy_instances: 0,
    prewarm_pool: { l1: 0, l2: 0, l3: 0 },
    resource_usage: {
      total_cpu_cores: 8,
      total_memory_mb: 4096,
      used_cpu_cores: 1,
      used_memory_mb: 512,
    },
  };

  const poolInstance: PoolInstance = {
    active_requests: 2,
    agent_mode: 'chat',
    created_at: '2026-01-01T00:00:00Z',
    health_status: 'healthy',
    instance_key: 'tenant-1:project-1:chat',
    last_request_at: '2026-01-02T00:00:00Z',
    memory_used_mb: 128,
    project_id: 'project-1',
    status: 'ready',
    tenant_id: 'tenant-1',
    tier: 'hot',
    total_requests: 10,
  };

  const sandbox: ProjectSandbox = {
    sandbox_id: 'sandbox-1',
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    status: 'running',
    is_healthy: true,
    created_at: '2026-01-01T00:00:00Z',
    last_accessed_at: '2026-01-02T00:00:00Z',
  };

  const sandboxStats: SandboxStats = {
    collected_at: '2026-01-02T00:00:01Z',
    cpu_percent: 1,
    memory_limit: 1024 * 1024 * 1024,
    memory_percent: 25,
    memory_usage: 256 * 1024 * 1024,
    pids: 3,
    project_id: 'project-1',
    sandbox_id: 'sandbox-1',
    status: 'running',
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(poolService.getStatus).mockResolvedValue(poolStatus);
    vi.mocked(poolService.listInstances).mockResolvedValue({
      instances: [poolInstance],
      page: 1,
      page_size: 200,
      total: 1,
    });
    vi.mocked(projectSandboxService.listProjectSandboxes).mockResolvedValue({
      sandboxes: [sandbox],
      total: 1,
    });
    vi.mocked(projectSandboxService.getStats).mockResolvedValue(sandboxStats);
  });

  it('renders pool actors and real project sandbox rows together', async () => {
    renderUnifiedRuntimes();

    expect(await screen.findByText('tenant-1:project-1:chat')).toBeInTheDocument();
    expect(await screen.findByText('sandbox-1')).toBeInTheDocument();
    expect(screen.getByText('2 req · 128 MB')).toBeInTheDocument();
    expect(screen.getByText('3 pids · 256 MB')).toBeInTheDocument();
    expect(screen.queryByText(/Sandbox rows coming soon/i)).not.toBeInTheDocument();
    expect(document.querySelector('.ant-table-content')).toHaveStyle({ overflowX: 'auto' });

    await waitFor(() => {
      expect(poolService.listInstances).toHaveBeenCalledWith({ page: 1, page_size: 100 });
      expect(projectSandboxService.listProjectSandboxes).toHaveBeenCalledWith({ limit: 100 });
      expect(projectSandboxService.getStats).toHaveBeenCalledWith('project-1');
    });
  });
});
