import { beforeEach, describe, expect, it, vi } from 'vitest';

import { auditService } from '../../services/auditService';
import { useAuditStore } from '../../stores/audit';

vi.mock('../../services/auditService', () => ({
  auditService: {
    list: vi.fn(),
    listRuntimeHooks: vi.fn(),
    getRuntimeHookSummary: vi.fn(),
    exportLogs: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe('useAuditStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuditStore.getState().reset();
  });

  it('stores runtime hook logs from the dedicated query surface', async () => {
    vi.mocked(auditService.listRuntimeHooks).mockResolvedValueOnce({
      items: [
        {
          id: 'runtime-1',
          timestamp: '2026-04-15T09:00:00Z',
          actor: 'system',
          actor_name: null,
          action: 'runtime_hook.custom_execution_succeeded',
          resource_type: 'runtime_hook',
          resource_id: 'script:demo',
          tenant_id: 'tenant-1',
          details: { hook_name: 'before_response' },
          ip_address: null,
          user_agent: null,
        },
      ],
      total: 3,
      page: 1,
      page_size: 20,
    });

    await useAuditStore.getState().fetchRuntimeHookLogs('tenant-1', {
      hook_name: 'before_response',
      page: 1,
      page_size: 20,
    });

    expect(auditService.listRuntimeHooks).toHaveBeenCalledWith(
      'tenant-1',
      expect.objectContaining({ hook_name: 'before_response' })
    );
    expect(useAuditStore.getState().logs).toHaveLength(1);
    expect(useAuditStore.getState().total).toBe(3);
  });

  it('stores runtime hook summary data for the observability panel', async () => {
    vi.mocked(auditService.getRuntimeHookSummary).mockResolvedValueOnce({
      total: 3,
      action_counts: { 'runtime_hook.custom_execution_succeeded': 2 },
      executor_counts: { script: 3 },
      family_counts: { mutating: 2 },
      isolation_mode_counts: { sandbox: 2, host: 1 },
      latest_timestamp: '2026-04-15T09:00:00Z',
    });

    await useAuditStore.getState().fetchRuntimeHookSummary('tenant-1', {
      hook_name: 'before_response',
      executor_kind: 'script',
    });

    expect(auditService.getRuntimeHookSummary).toHaveBeenCalledWith('tenant-1', {
      hook_name: 'before_response',
      executor_kind: 'script',
    });
    expect(useAuditStore.getState().runtimeHookSummary?.executor_counts.script).toBe(3);
    expect(useAuditStore.getState().isRuntimeHookSummaryLoading).toBe(false);
  });

  it('keeps the latest runtime hook log response when requests finish out of order', async () => {
    let resolveFirst:
      | ((value: Awaited<ReturnType<typeof auditService.listRuntimeHooks>>) => void)
      | null = null;

    vi.mocked(auditService.listRuntimeHooks)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          })
      )
      .mockResolvedValueOnce({
        items: [
          {
            id: 'runtime-2',
            timestamp: '2026-04-15T09:01:00Z',
            actor: 'system',
            actor_name: null,
            action: 'runtime_hook.custom_execution_failed',
            resource_type: 'runtime_hook',
            resource_id: 'script:demo',
            tenant_id: 'tenant-1',
            details: { hook_name: 'after_tool_execution' },
            ip_address: null,
            user_agent: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      });

    const firstRequest = useAuditStore.getState().fetchRuntimeHookLogs('tenant-1', {
      hook_name: 'before_response',
      page: 2,
      page_size: 20,
    });
    const secondRequest = useAuditStore.getState().fetchRuntimeHookLogs('tenant-1', {
      hook_name: 'after_tool_execution',
      page: 1,
      page_size: 20,
    });

    await secondRequest;
    resolveFirst?.({
      items: [
        {
          id: 'runtime-1',
          timestamp: '2026-04-15T09:00:00Z',
          actor: 'system',
          actor_name: null,
          action: 'runtime_hook.custom_execution_succeeded',
          resource_type: 'runtime_hook',
          resource_id: 'script:demo',
          tenant_id: 'tenant-1',
          details: { hook_name: 'before_response' },
          ip_address: null,
          user_agent: null,
        },
      ],
      total: 2,
      page: 2,
      page_size: 20,
    });
    await firstRequest;

    expect(useAuditStore.getState().logs[0]?.details?.hook_name).toBe('after_tool_execution');
    expect(useAuditStore.getState().page).toBe(1);
  });

  it('ignores list responses that resolve after reset', async () => {
    const staleRequest = deferred<Awaited<ReturnType<typeof auditService.list>>>();

    vi.mocked(auditService.list)
      .mockReturnValueOnce(staleRequest.promise)
      .mockResolvedValueOnce({
        items: [
          {
            id: 'audit-fresh',
            timestamp: '2026-04-15T09:05:00Z',
            actor: 'system',
            actor_name: null,
            action: 'tenant.updated',
            resource_type: 'tenant',
            resource_id: 'tenant-1',
            tenant_id: 'tenant-1',
            details: { source: 'fresh' },
            ip_address: null,
            user_agent: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      });

    const staleFetch = useAuditStore.getState().fetchLogs('tenant-1', { page: 2, page_size: 20 });
    useAuditStore.getState().reset();
    await useAuditStore.getState().fetchLogs('tenant-1', { page: 1, page_size: 20 });

    expect(useAuditStore.getState().logs[0]?.id).toBe('audit-fresh');

    staleRequest.resolve({
      items: [
        {
          id: 'audit-stale',
          timestamp: '2026-04-15T09:00:00Z',
          actor: 'system',
          actor_name: null,
          action: 'tenant.deleted',
          resource_type: 'tenant',
          resource_id: 'tenant-1',
          tenant_id: 'tenant-1',
          details: { source: 'stale' },
          ip_address: null,
          user_agent: null,
        },
      ],
      total: 1,
      page: 2,
      page_size: 20,
    });
    await staleFetch;

    expect(useAuditStore.getState().logs[0]?.id).toBe('audit-fresh');
    expect(useAuditStore.getState().page).toBe(1);
  });

  it('keeps the latest runtime hook summary response when requests finish out of order', async () => {
    let resolveFirst:
      | ((value: Awaited<ReturnType<typeof auditService.getRuntimeHookSummary>>) => void)
      | null = null;

    vi.mocked(auditService.getRuntimeHookSummary)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          })
      )
      .mockResolvedValueOnce({
        total: 1,
        action_counts: { 'runtime_hook.custom_execution_failed': 1 },
        executor_counts: { script: 1 },
        family_counts: { side_effect: 1 },
        isolation_mode_counts: { host: 1 },
        latest_timestamp: '2026-04-15T09:05:00Z',
      });

    const firstRequest = useAuditStore.getState().fetchRuntimeHookSummary('tenant-1', {
      hook_name: 'before_response',
    });
    const secondRequest = useAuditStore.getState().fetchRuntimeHookSummary('tenant-1', {
      hook_name: 'after_tool_execution',
    });

    await secondRequest;
    resolveFirst?.({
      total: 3,
      action_counts: { 'runtime_hook.custom_execution_succeeded': 3 },
      executor_counts: { script: 3 },
      family_counts: { mutating: 3 },
      isolation_mode_counts: { sandbox: 3 },
      latest_timestamp: '2026-04-15T09:00:00Z',
    });
    await firstRequest;

    expect(useAuditStore.getState().runtimeHookSummary?.action_counts).toEqual({
      'runtime_hook.custom_execution_failed': 1,
    });
    expect(useAuditStore.getState().runtimeHookSummary?.latest_timestamp).toBe(
      '2026-04-15T09:05:00Z'
    );
  });

  it('ignores summary responses that resolve after reset', async () => {
    const staleRequest = deferred<Awaited<ReturnType<typeof auditService.getRuntimeHookSummary>>>();

    vi.mocked(auditService.getRuntimeHookSummary)
      .mockReturnValueOnce(staleRequest.promise)
      .mockResolvedValueOnce({
        total: 1,
        action_counts: { 'runtime_hook.custom_execution_failed': 1 },
        executor_counts: { script: 1 },
        family_counts: { side_effect: 1 },
        isolation_mode_counts: { host: 1 },
        latest_timestamp: '2026-04-15T09:05:00Z',
      });

    const staleFetch = useAuditStore.getState().fetchRuntimeHookSummary('tenant-1', {
      hook_name: 'before_response',
    });
    useAuditStore.getState().reset();
    await useAuditStore.getState().fetchRuntimeHookSummary('tenant-1', {
      hook_name: 'after_tool_execution',
    });

    expect(useAuditStore.getState().runtimeHookSummary?.action_counts).toEqual({
      'runtime_hook.custom_execution_failed': 1,
    });

    staleRequest.resolve({
      total: 3,
      action_counts: { 'runtime_hook.custom_execution_succeeded': 3 },
      executor_counts: { script: 3 },
      family_counts: { mutating: 3 },
      isolation_mode_counts: { sandbox: 3 },
      latest_timestamp: '2026-04-15T09:00:00Z',
    });
    await staleFetch;

    expect(useAuditStore.getState().runtimeHookSummary?.action_counts).toEqual({
      'runtime_hook.custom_execution_failed': 1,
    });
    expect(useAuditStore.getState().runtimeHookSummary?.latest_timestamp).toBe(
      '2026-04-15T09:05:00Z'
    );
  });
});
