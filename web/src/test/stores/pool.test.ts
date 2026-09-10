import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, ApiErrorType } from '@/services/client/ApiError';
import { poolService, type PoolStatus, type PoolAuthorityScope } from '@/services/poolService';
import { usePoolStore } from '@/stores/pool';
import { logger } from '@/utils/logger';

vi.mock('@/utils/logger', () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

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

  it('flags 403 as a stable forbidden verdict without error logging', async () => {
    const forbidden = new ApiError(
      ApiErrorType.AUTHORIZATION,
      'FORBIDDEN',
      'Global administrator role required',
      403
    );
    vi.mocked(poolService.getStatus).mockRejectedValueOnce(forbidden);

    usePoolStore.getState().setScope(tenantScope('tenant-a'));
    await usePoolStore.getState().fetchStatus();

    const state = usePoolStore.getState();
    expect(state.forbidden).toBe(true);
    expect(state.statusError).toBe('Global administrator role required');
    expect(state.isStatusLoading).toBe(false);
    expect(logger.error).not.toHaveBeenCalled();
  });

  it('clears the forbidden flag when the scope changes', async () => {
    const forbidden = new ApiError(
      ApiErrorType.AUTHORIZATION,
      'FORBIDDEN',
      'Global administrator role required',
      403
    );
    vi.mocked(poolService.getStatus).mockRejectedValueOnce(forbidden);

    usePoolStore.getState().setScope(tenantScope('tenant-a'));
    await usePoolStore.getState().fetchStatus();
    expect(usePoolStore.getState().forbidden).toBe(true);

    usePoolStore.getState().setScope(tenantScope('tenant-b'));
    expect(usePoolStore.getState().forbidden).toBe(false);
    expect(usePoolStore.getState().statusError).toBeNull();
  });
});
