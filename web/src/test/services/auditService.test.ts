import { beforeEach, describe, expect, it, vi } from 'vitest';

import { auditService } from '../../services/auditService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
  },
}));

describe('auditService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('maps generic audit filters onto the filtered endpoint with limit/offset params', async () => {
    const { httpClient } = await import('../../services/client/httpClient');
    vi.mocked(httpClient.get).mockResolvedValueOnce({
      items: [],
      total: 12,
      limit: 20,
      offset: 20,
    });

    const result = await auditService.list('tenant-1', {
      page: 2,
      page_size: 20,
      action: 'tenant.updated',
      resource_type: 'tenant',
      from_date: '2026-04-15',
      to_date: '2026-04-16',
    });

    expect(httpClient.get).toHaveBeenCalledWith('/tenants/tenant-1/audit-logs/filter', {
      params: {
        limit: 20,
        offset: 20,
        action: 'tenant.updated',
        resource_type: 'tenant',
        start_time: '2026-04-15',
        end_time: '2026-04-16',
      },
    });
    expect(result).toEqual({
      items: [],
      total: 12,
      page: 2,
      page_size: 20,
    });
  });

  it('requests runtime hook logs with hook-specific filters and normalized pagination', async () => {
    const { httpClient } = await import('../../services/client/httpClient');
    vi.mocked(httpClient.get).mockResolvedValueOnce({
      items: [],
      total: 3,
      limit: 20,
      offset: 0,
    });

    await auditService.listRuntimeHooks('tenant-1', {
      page: 1,
      page_size: 20,
      hook_name: 'before_response',
      executor_kind: 'script',
      hook_family: 'mutating',
      isolation_mode: 'sandbox',
    });

    expect(httpClient.get).toHaveBeenCalledWith('/tenants/tenant-1/audit-logs/runtime-hooks', {
      params: {
        limit: 20,
        offset: 0,
        hook_name: 'before_response',
        executor_kind: 'script',
        hook_family: 'mutating',
        isolation_mode: 'sandbox',
      },
    });
  });

  it('requests runtime hook summary with summary filters only', async () => {
    const { httpClient } = await import('../../services/client/httpClient');
    vi.mocked(httpClient.get).mockResolvedValueOnce({
      total: 3,
      action_counts: {},
      executor_counts: {},
      family_counts: {},
      isolation_mode_counts: {},
      latest_timestamp: null,
    });

    await auditService.getRuntimeHookSummary('tenant-1', {
      hook_name: 'before_response',
      executor_kind: 'script',
    });

    expect(httpClient.get).toHaveBeenCalledWith(
      '/tenants/tenant-1/audit-logs/runtime-hooks/summary',
      {
        params: {
          hook_name: 'before_response',
          executor_kind: 'script',
        },
      }
    );
  });

  it('exports generic audit logs with generic filters', async () => {
    const { httpClient } = await import('../../services/client/httpClient');
    vi.mocked(httpClient.get).mockResolvedValueOnce(new Blob(['ok']));

    await auditService.exportLogs('tenant-1', 'json', {
      page: 1,
      page_size: 20,
      action: 'tenant.updated',
      resource_type: 'tenant',
      actor: 'system',
      from_date: '2026-04-15',
      to_date: '2026-04-16',
    });

    expect(httpClient.get).toHaveBeenCalledWith(
      '/tenants/tenant-1/audit-logs/export?format=json&action=tenant.updated&resource_type=tenant&actor=system&start_time=2026-04-15&end_time=2026-04-16',
      {
        responseType: 'blob',
      }
    );
  });

  it('exports runtime hook audit logs with hook-specific filters', async () => {
    const { httpClient } = await import('../../services/client/httpClient');
    vi.mocked(httpClient.get).mockResolvedValueOnce(new Blob(['ok']));

    await auditService.exportLogs('tenant-1', 'csv', {
      page: 1,
      page_size: 20,
      action: 'runtime_hook.custom_execution_succeeded',
      hook_name: 'before_response',
      executor_kind: 'script',
      hook_family: 'mutating',
      isolation_mode: 'sandbox',
    });

    expect(httpClient.get).toHaveBeenCalledWith(
      '/tenants/tenant-1/audit-logs/export?format=csv&action=runtime_hook.custom_execution_succeeded&hook_name=before_response&executor_kind=script&hook_family=mutating&isolation_mode=sandbox',
      {
        responseType: 'blob',
      }
    );
  });
});
