import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clusterService } from '@/services/clusterService';
import { useClusterStore } from '@/stores/cluster';

import type { ClusterHealthResponse, ClusterResponse } from '@/services/clusterService';

vi.mock('@/services/clusterService', () => ({
  clusterService: {
    list: vi.fn(),
    getById: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    getHealth: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

const cluster = (id: string): ClusterResponse => ({
  id,
  name: id,
  tenant_id: 'tenant-1',
  compute_provider: 'kubernetes',
  proxy_endpoint: null,
  provider_config: {},
  credentials_encrypted: null,
  status: 'active',
  health_status: 'healthy',
  last_health_check: '2026-06-18T00:00:00Z',
  created_by: 'user-1',
  created_at: '2026-06-18T00:00:00Z',
  updated_at: null,
});

const health = (status: string): ClusterHealthResponse => ({
  status,
  node_count: 3,
  cpu_usage: 0.4,
  memory_usage: 0.5,
  checked_at: '2026-06-18T00:00:00Z',
});

describe('cluster store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useClusterStore.getState().reset();
  });

  it('ignores list responses that resolve after reset', async () => {
    const request = deferred<Awaited<ReturnType<typeof clusterService.list>>>();
    vi.mocked(clusterService.list).mockReturnValueOnce(request.promise);

    const load = useClusterStore.getState().listClusters();
    useClusterStore.getState().reset();

    request.resolve({
      clusters: [cluster('stale-cluster')],
      total: 1,
      page: 1,
      page_size: 20,
    });
    await load;

    const state = useClusterStore.getState();
    expect(state.clusters).toEqual([]);
    expect(state.total).toBe(0);
    expect(state.isLoading).toBe(false);
  });

  it('ignores detail responses that resolve after reset', async () => {
    const request = deferred<ClusterResponse>();
    vi.mocked(clusterService.getById).mockReturnValueOnce(request.promise);

    const load = useClusterStore.getState().getCluster('stale-cluster');
    useClusterStore.getState().reset();

    request.resolve(cluster('stale-cluster'));
    await load;

    expect(useClusterStore.getState().currentCluster).toBeNull();
    expect(useClusterStore.getState().isLoading).toBe(false);
  });

  it('ignores health responses that resolve after reset', async () => {
    const request = deferred<ClusterHealthResponse>();
    vi.mocked(clusterService.getHealth).mockReturnValueOnce(request.promise);

    const load = useClusterStore.getState().getClusterHealth('stale-cluster');
    useClusterStore.getState().reset();

    request.resolve(health('stale'));
    await load;

    expect(useClusterStore.getState().clusterHealth).toBeNull();
    expect(useClusterStore.getState().isLoading).toBe(false);
  });
});
