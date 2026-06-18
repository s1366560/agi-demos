import { beforeEach, describe, expect, it, vi } from 'vitest';

import { trustService } from '@/services/trustService';
import { useTrustStore } from '@/stores/trust';

import type { DecisionRecord, TrustPolicy } from '@/services/trustService';

vi.mock('@/services/trustService', () => ({
  trustService: {
    listPolicies: vi.fn(),
    createPolicy: vi.fn(),
    listDecisions: vi.fn(),
    resolveApproval: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

const policy = (id: string): TrustPolicy => ({
  id,
  tenant_id: 'tenant-1',
  workspace_id: 'workspace-1',
  agent_instance_id: 'agent-1',
  action_type: 'terminal.execute',
  granted_by: 'admin-1',
  grant_type: 'once',
  created_at: '2026-06-18T00:00:00Z',
  deleted_at: null,
});

const decision = (id: string): DecisionRecord => ({
  id,
  tenant_id: 'tenant-1',
  workspace_id: 'workspace-1',
  agent_instance_id: 'agent-1',
  decision_type: 'permission',
  context_summary: 'Terminal execution',
  proposal: {},
  outcome: 'approved',
  reviewer_id: null,
  review_type: null,
  review_comment: null,
  resolved_at: null,
  created_at: '2026-06-18T00:00:00Z',
  updated_at: null,
  deleted_at: null,
});

describe('trust store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTrustStore.getState().reset();
  });

  it('ignores policy responses that resolve after reset', async () => {
    const request = deferred<Awaited<ReturnType<typeof trustService.listPolicies>>>();
    vi.mocked(trustService.listPolicies).mockReturnValueOnce(request.promise);

    const load = useTrustStore
      .getState()
      .fetchPolicies('tenant-1', { workspace_id: 'workspace-1' });
    useTrustStore.getState().reset();

    request.resolve({ items: [policy('stale-policy')] });
    await load;

    expect(useTrustStore.getState().policies).toEqual([]);
    expect(useTrustStore.getState().isLoading).toBe(false);
  });

  it('ignores decision responses that resolve after reset', async () => {
    const request = deferred<Awaited<ReturnType<typeof trustService.listDecisions>>>();
    vi.mocked(trustService.listDecisions).mockReturnValueOnce(request.promise);

    const load = useTrustStore
      .getState()
      .fetchDecisions('tenant-1', { workspace_id: 'workspace-1' });
    useTrustStore.getState().reset();

    request.resolve({ items: [decision('stale-decision')] });
    await load;

    expect(useTrustStore.getState().decisions).toEqual([]);
    expect(useTrustStore.getState().isLoading).toBe(false);
  });
});
