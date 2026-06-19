import { readFileSync } from 'node:fs';

import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  GenericTenantProjectRedirect,
  LegacyProjectRedirect,
  LegacyTenantAuditLogsRedirect,
  LegacyTenantSingleSegmentRedirect,
} from '@/App';

const tenantState = {
  currentTenant: { id: 'tenant-1', name: 'Tenant One' },
  tenants: [{ id: 'tenant-1', name: 'Tenant One' }],
  listTenants: vi.fn(),
};

const authState = {
  user: { tenant_id: 'tenant-1', name: 'Test User', email: 'test@example.com' },
};

const projectState = {
  projects: [{ id: 'project-1', tenant_id: 'tenant-1', name: 'Project One' }],
  getProject: vi.fn(),
};

vi.mock('@/stores/tenant', () => {
  const useTenantStore = (selector: (state: typeof tenantState) => unknown) =>
    selector(tenantState);
  useTenantStore.getState = () => tenantState;
  return { useTenantStore };
});

vi.mock('@/stores/auth', () => ({
  useAuthStore: (selector: (state: typeof authState) => unknown) => selector(authState),
}));

vi.mock('@/stores/project', () => ({
  useProjectStore: (selector: (state: typeof projectState) => unknown) => selector(projectState),
}));

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

describe('App route redirects', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tenantState.currentTenant = { id: 'tenant-1', name: 'Tenant One' };
    tenantState.tenants = [{ id: 'tenant-1', name: 'Tenant One' }];
    tenantState.listTenants.mockResolvedValue(undefined);
    authState.user = { tenant_id: 'tenant-1', name: 'Test User', email: 'test@example.com' };
    projectState.projects = [{ id: 'project-1', tenant_id: 'tenant-1', name: 'Project One' }];
    projectState.getProject.mockResolvedValue({
      id: 'project-1',
      tenant_id: 'tenant-1',
      name: 'Project One',
    });
  });

  it('redirects generic tenant project routes to the canonical tenant-scoped project path', async () => {
    render(
      <MemoryRouter initialEntries={['/tenant/project/project-1/cron-jobs?from=legacy']}>
        <Routes>
          <Route path="/tenant/project/:projectId/*" element={<GenericTenantProjectRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/tenant/tenant-1/project/project-1/cron-jobs?from=legacy'
      );
    });
  });

  it('does not trust stale cached projects from another tenant', async () => {
    projectState.projects = [
      { id: 'project-stale', tenant_id: 'tenant-old', name: 'Stale Tenant Project' },
    ];
    projectState.getProject.mockRejectedValueOnce(new Error('not in current tenant'));

    render(
      <MemoryRouter initialEntries={['/project/project-stale/memories?source=legacy']}>
        <Routes>
          <Route path="/project/:projectId/*" element={<LegacyProjectRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(projectState.getProject).toHaveBeenCalledWith('tenant-1', 'project-stale');
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/tenant/tenant-1/projects?source=legacy'
      );
    });
  });

  it('resolves legacy project redirects from the accessible tenant list', async () => {
    tenantState.currentTenant = null;
    tenantState.tenants = [{ id: 'tenant-2', name: 'Tenant Two' }];
    authState.user = { tenant_id: '', name: 'Test User', email: 'test@example.com' };
    projectState.projects = [];
    projectState.getProject.mockResolvedValueOnce({
      id: 'project-2',
      tenant_id: 'tenant-2',
      name: 'Tenant Two Project',
    });

    render(
      <MemoryRouter initialEntries={['/project/project-2/blackboard']}>
        <Routes>
          <Route path="/project/:projectId/*" element={<LegacyProjectRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(projectState.getProject).toHaveBeenCalledWith('tenant-2', 'project-2');
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/tenant/tenant-2/project/project-2/blackboard'
      );
    });
  });

  it('loads tenants before using the fallback projects route', async () => {
    tenantState.currentTenant = null;
    tenantState.tenants = [];
    tenantState.listTenants.mockImplementation(async () => {
      tenantState.tenants = [{ id: 'tenant-loaded', name: 'Loaded Tenant' }];
    });
    authState.user = { tenant_id: '', name: 'Test User', email: 'test@example.com' };
    projectState.projects = [];
    projectState.getProject.mockRejectedValue(new Error('not found'));

    render(
      <MemoryRouter initialEntries={['/project/project-missing/memories?source=legacy']}>
        <Routes>
          <Route path="/project/:projectId/*" element={<LegacyProjectRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(tenantState.listTenants).toHaveBeenCalledTimes(1);
      expect(projectState.getProject).toHaveBeenCalledWith('tenant-loaded', 'project-missing');
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/tenant/tenant-loaded/projects?source=legacy'
      );
    });
  });

  it('fails closed to the canonical tenant projects route when ownership cannot be resolved', async () => {
    tenantState.currentTenant = null;
    authState.user = { tenant_id: 'tenant-1', name: 'Test User', email: 'test@example.com' };
    projectState.projects = [];
    projectState.getProject.mockRejectedValue(new Error('not found'));

    render(
      <MemoryRouter initialEntries={['/project/project-unknown/memories?source=legacy']}>
        <Routes>
          <Route path="/project/:projectId/*" element={<LegacyProjectRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/tenant/tenant-1/projects?source=legacy'
      );
    });
  });

  it('redirects legacy /audit-logs to the canonical tenant audit log route', async () => {
    render(
      <MemoryRouter initialEntries={['/audit-logs']}>
        <Routes>
          <Route path="/audit-logs" element={<LegacyTenantAuditLogsRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/tenant/tenant-1/audit-logs');
    });
  });

  it('redirects a single tenant segment to the tenant overview without stale project scope', async () => {
    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1?projectId=project-1&workspaceId=ws-1']}>
        <Routes>
          <Route path="/tenant/:segment" element={<LegacyTenantSingleSegmentRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/tenant/tenant-1/overview');
    });
  });

  it('redirects UUID-shaped tenant segments before legacy conversation fallback', async () => {
    const tenantId = '8582ddb4-5fa0-4c5d-8c14-0082a43c1dfc';
    tenantState.currentTenant = null;
    tenantState.tenants = [];

    render(
      <MemoryRouter initialEntries={[`/tenant/${tenantId}`]}>
        <Routes>
          <Route path="/tenant/:segment" element={<LegacyTenantSingleSegmentRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(`/tenant/${tenantId}/overview`);
    });
  });

  it('redirects legacy single-segment conversations to canonical agent workspace URLs', async () => {
    render(
      <MemoryRouter initialEntries={['/tenant/legacy-conversation?workspaceId=ws-1']}>
        <Routes>
          <Route path="/tenant/:segment" element={<LegacyTenantSingleSegmentRedirect />} />
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/tenant/agent-workspace/legacy-conversation?workspaceId=ws-1'
      );
    });
  });

  it('declares tenant static pages before the legacy conversation catch-all route', () => {
    const appSource = readFileSync('src/App.tsx', 'utf8');
    const legacyConversationIndex = appSource.indexOf('path=":tenantId/:conversation"');

    expect(appSource.indexOf('path=":tenantId/subagents"')).toBeGreaterThan(-1);
    expect(appSource.indexOf('path=":tenantId/agent-definitions"')).toBeGreaterThan(-1);
    expect(appSource.indexOf('path=":tenantId/dead-letter-queue"')).toBeGreaterThan(-1);
    expect(legacyConversationIndex).toBeGreaterThan(-1);
    expect(appSource.indexOf('path=":tenantId/subagents"')).toBeLessThan(legacyConversationIndex);
    expect(appSource.indexOf('path=":tenantId/agent-definitions"')).toBeLessThan(
      legacyConversationIndex
    );
    expect(appSource.indexOf('path=":tenantId/dead-letter-queue"')).toBeLessThan(
      legacyConversationIndex
    );
  });
});
