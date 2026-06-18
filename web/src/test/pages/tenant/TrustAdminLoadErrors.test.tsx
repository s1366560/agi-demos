import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { DecisionRecords } from '@/pages/tenant/DecisionRecords';
import { TrustPolicies } from '@/pages/tenant/TrustPolicies';
import { useTenantStore } from '@/stores/tenant';
import { useTrustStore } from '@/stores/trust';

import { fireEvent, render, screen, waitFor } from '../../utils';

import type { DecisionRecord, TrustPolicy } from '@/services/trustService';
import type { Tenant } from '@/types/memory';

const trustServiceMocks = vi.hoisted(() => ({
  createPolicy: vi.fn(),
  listDecisions: vi.fn(),
  listPolicies: vi.fn(),
  resolveApproval: vi.fn(),
}));

const lazyMessageMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock('@/services/trustService', () => ({
  trustService: trustServiceMocks,
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyAlert: ({
    action,
    description,
    message,
    title,
  }: {
    action?: React.ReactNode;
    description?: React.ReactNode;
    message?: React.ReactNode;
    title?: React.ReactNode;
  }) => (
    <div role="alert">
      <div>{title ?? message}</div>
      <div>{description}</div>
      {action}
    </div>
  ),
  LazyDrawer: ({ children, open }: { children?: React.ReactNode; open?: boolean }) =>
    open ? <div>{children}</div> : null,
  LazyEmpty: ({ description }: { description?: React.ReactNode }) => <div>{description}</div>,
  LazyModal: ({ children, open }: { children?: React.ReactNode; open?: boolean }) =>
    open ? <div>{children}</div> : null,
  LazySpin: () => <div>Loading</div>,
  useLazyMessage: () => lazyMessageMocks,
}));

function makeTenant(overrides: Partial<Tenant> = {}): Tenant {
  return {
    id: 'tenant-1',
    name: 'Acme',
    owner_id: 'admin-1',
    plan: 'enterprise',
    max_projects: 100,
    max_users: 100,
    max_storage: 1000,
    created_at: '2026-06-17T00:00:00Z',
    ...overrides,
  };
}

function makeDecision(overrides: Partial<DecisionRecord> = {}): DecisionRecord {
  return {
    id: 'decision-1',
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
    created_at: '2026-06-17T00:00:00Z',
    updated_at: null,
    deleted_at: null,
    ...overrides,
  };
}

function makePolicy(overrides: Partial<TrustPolicy> = {}): TrustPolicy {
  return {
    id: 'policy-1',
    tenant_id: 'tenant-1',
    workspace_id: 'workspace-1',
    agent_instance_id: 'agent-1',
    action_type: 'terminal.execute',
    granted_by: 'admin-1',
    grant_type: 'once',
    created_at: '2026-06-17T00:00:00Z',
    deleted_at: null,
    ...overrides,
  };
}

describe('trust admin load errors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTenantStore.setState({ currentTenant: makeTenant() });
    useTrustStore.getState().reset();
    trustServiceMocks.listDecisions.mockResolvedValue({ items: [] });
    trustServiceMocks.listPolicies.mockResolvedValue({ items: [] });
  });

  it('shows a retryable decision-record load error instead of an empty state', async () => {
    trustServiceMocks.listDecisions
      .mockRejectedValueOnce(new Error('decision service unavailable'))
      .mockResolvedValueOnce({ items: [makeDecision()] });

    render(<DecisionRecords />);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to load decision records');
    });
    expect(screen.getByRole('alert')).toHaveTextContent('decision service unavailable');
    expect(screen.queryByText('No decision records found')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(screen.getByText('Terminal execution')).toBeInTheDocument();
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('loads decision records using the route tenant while tenant store is stale', async () => {
    useTenantStore.setState({ currentTenant: makeTenant({ id: 'tenant-store-old' }) });
    trustServiceMocks.listDecisions.mockResolvedValue({ items: [makeDecision()] });

    render(
      <Routes>
        <Route path="/tenant/:tenantId/decision-records" element={<DecisionRecords />} />
      </Routes>,
      { route: '/tenant/tenant-route-new/decision-records' }
    );

    await waitFor(() => {
      expect(trustServiceMocks.listDecisions).toHaveBeenCalledWith(
        'tenant-route-new',
        expect.objectContaining({ workspace_id: 'default' })
      );
    });
    expect(trustServiceMocks.listDecisions).not.toHaveBeenCalledWith(
      'tenant-store-old',
      expect.anything()
    );
  });

  it('shows a retryable trust-policy load error instead of an empty state', async () => {
    trustServiceMocks.listPolicies
      .mockRejectedValueOnce(new Error('policy service unavailable'))
      .mockResolvedValueOnce({ items: [makePolicy()] });

    render(<TrustPolicies />);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to load trust policies');
    });
    expect(screen.getByRole('alert')).toHaveTextContent('policy service unavailable');
    expect(screen.queryByText('No trust policies found')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(screen.getByText('terminal.execute')).toBeInTheDocument();
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('loads trust policies using the route tenant while tenant store is stale', async () => {
    useTenantStore.setState({ currentTenant: makeTenant({ id: 'tenant-store-old' }) });
    trustServiceMocks.listPolicies.mockResolvedValue({ items: [makePolicy()] });

    render(
      <Routes>
        <Route path="/tenant/:tenantId/trust-policies" element={<TrustPolicies />} />
      </Routes>,
      { route: '/tenant/tenant-route-new/trust-policies' }
    );

    await waitFor(() => {
      expect(trustServiceMocks.listPolicies).toHaveBeenCalledWith(
        'tenant-route-new',
        expect.objectContaining({ workspace_id: 'default' })
      );
    });
    expect(trustServiceMocks.listPolicies).not.toHaveBeenCalledWith(
      'tenant-store-old',
      expect.anything()
    );
  });
});
