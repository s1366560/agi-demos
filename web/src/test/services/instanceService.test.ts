import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { instanceService } from '../../services/instanceService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('instanceService', () => {
  const mockHttpClient = httpClient as unknown as {
    post: ReturnType<typeof vi.fn>;
    put: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates instances with the backend schema fields', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'inst-1' });

    await instanceService.create({
      name: 'Agent Runtime',
      slug: 'agent-runtime',
      tenant_id: 'tenant-1',
      description: 'Runs production agents',
      quota_cpu: '2',
      quota_memory: '4Gi',
      quota_max_pods: 5,
      storage_class: 'fast',
      storage_size: '20Gi',
      compute_provider: 'kubernetes',
      runtime: 'docker',
      workspace_id: 'workspace-1',
      hex_position_q: 2,
      hex_position_r: -1,
      agent_display_name: 'Runtime Agent',
      agent_label: 'prod',
      theme_color: '#0070f3',
    });

    expect(mockHttpClient.post).toHaveBeenCalledWith('/instances/', {
      name: 'Agent Runtime',
      slug: 'agent-runtime',
      tenant_id: 'tenant-1',
      description: 'Runs production agents',
      quota_cpu: '2',
      quota_memory: '4Gi',
      quota_max_pods: 5,
      storage_class: 'fast',
      storage_size: '20Gi',
      compute_provider: 'kubernetes',
      runtime: 'docker',
      workspace_id: 'workspace-1',
      hex_position_q: 2,
      hex_position_r: -1,
      agent_display_name: 'Runtime Agent',
      agent_label: 'prod',
      theme_color: '#0070f3',
    });
  });

  it('updates instances with mutable deployment fields', async () => {
    mockHttpClient.put.mockResolvedValue({ id: 'inst-1' });

    await instanceService.update('inst-1', {
      description: 'Updated runtime description',
      slug: 'renamed-runtime',
      cluster_id: 'cluster-2',
      namespace: 'runtime',
      quota_cpu: '4',
      quota_memory: '8Gi',
      quota_max_pods: 10,
      storage_class: 'standard',
      storage_size: '50Gi',
      compute_provider: 'local',
      runtime: 'kubernetes',
      workspace_id: 'workspace-2',
      hex_position_q: 4,
      hex_position_r: 3,
    });

    expect(mockHttpClient.put).toHaveBeenCalledWith('/instances/inst-1', {
      description: 'Updated runtime description',
      slug: 'renamed-runtime',
      cluster_id: 'cluster-2',
      namespace: 'runtime',
      quota_cpu: '4',
      quota_memory: '8Gi',
      quota_max_pods: 10,
      storage_class: 'standard',
      storage_size: '50Gi',
      compute_provider: 'local',
      runtime: 'kubernetes',
      workspace_id: 'workspace-2',
      hex_position_q: 4,
      hex_position_r: 3,
    });
  });
});
