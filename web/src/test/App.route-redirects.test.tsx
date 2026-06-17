import { readFileSync } from 'node:fs';

import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  GenericTenantProjectRedirect,
  LegacyProjectRedirect,
  LegacyTenantAuditLogsRedirect,
} from '@/App';

const tenantState = {
  currentTenant: { id: 'tenant-1', name: 'Tenant One' },
};

const authState = {
  user: { tenant_id: 'tenant-1', name: 'Test User', email: 'test@example.com' },
};

const projectState = {
  projects: [{ id: 'project-1', name: 'Project One' }],
  getProject: vi.fn(),
};

vi.mock('@/stores/tenant', () => ({
  useTenantStore: (selector: (state: typeof tenantState) => unknown) => selector(tenantState),
}));

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
    authState.user = { tenant_id: 'tenant-1', name: 'Test User', email: 'test@example.com' };
    projectState.projects = [{ id: 'project-1', name: 'Project One' }];
    projectState.getProject.mockResolvedValue({ id: 'project-1', name: 'Project One' });
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

  it('fails closed to /tenant/projects when project ownership cannot be resolved', async () => {
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
      expect(screen.getByTestId('location')).toHaveTextContent('/tenant/projects?source=legacy');
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
