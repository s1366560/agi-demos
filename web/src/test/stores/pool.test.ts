import { beforeEach, describe, expect, it, vi } from 'vitest';

import { poolService, type PoolStatus, type PoolAuthorityScope } from '@/services/poolService';
import { usePoolStore } from '@/stores/pool';

vi.mock('@/services/poolService', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/services/poolService')>();
  return {
    ...original,
    poolService: {
      ...original.poolService,
      getStatus: vi.fn(),
    },
  };
});

const tenantScope = (tenantId: string): PoolAuthorityScope => ({
  scope: 'tenant',
  tenant_id: tenantId,
});

const tenantStatus = (tenantId: string): PoolStatus => ({
  enabled: true,
  status: 'running',
  total_instances: 1,
  hot_instances: 1,
  warm_instances: 0,
  cold_instances: 0,
  ready_instances: 1,
  executing_instances: 0,
  unhealthy_instances: 0,
  prewarm_pool: null,
  resource_usage: null,
  resolved_scope: 'tenant',
  tenant_id: tenantId,
  reason_code: 'global_pool_capacity_not_available_in_tenant_scope',
});

describe('pool store scope authority', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usePoolStore.getState().reset();
  });

  it('discards an earlier scope response after switching tenants', async () => {
    let resolveFirst!: (status: PoolStatus) => void;
    vi.mocked(poolService.getStatus).mockReturnValueOnce(
      new Promise<PoolStatus>((resolve) => {
        resolveFirst = resolve;
      })
    );

    usePoolStore.getState().setScope(tenantScope('tenant-a'));
    const pending = usePoolStore.getState().fetchStatus();
    expect(usePoolStore.getState().isStatusLoading).toBe(true);

    usePoolStore.getState().setScope(tenantScope('tenant-b'));
    expect(usePoolStore.getState().isStatusLoading).toBe(false);

    resolveFirst(tenantStatus('tenant-a'));
    await pending;

    expect(usePoolStore.getState().scope).toEqual(tenantScope('tenant-b'));
    expect(usePoolStore.getState().status).toBeNull();
    expect(usePoolStore.getState().statusError).toBeNull();
    expect(usePoolStore.getState().isStatusLoading).toBe(false);
  });
});
