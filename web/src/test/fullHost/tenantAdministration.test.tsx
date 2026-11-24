import { Suspense } from 'react';
import { Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { tenantAdministrationRoutes } from '../../fullHost/tenantAdministration';
import { registryService } from '../../services/registryService';
import { smtpService } from '../../services/smtpService';
import { useTenantStore } from '../../stores/tenant';
import { render, screen, waitFor } from '../utils';

vi.mock('../../stores/tenant');
vi.mock('../../services/api', () => ({
  tenantAPI: { getStats: vi.fn().mockResolvedValue({}) },
}));

vi.mock('../../services/registryService', () => ({
  registryService: { list: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../../services/smtpService', () => ({
  smtpService: { getConfig: vi.fn().mockResolvedValue(null) },
}));

describe('full tenant administration', () => {
  beforeEach(() => {
    const state = {
      currentTenant: { id: 'org-42', name: 'QA organization', plan: 'basic' },
    } as ReturnType<typeof useTenantStore.getState>;
    vi.mocked(useTenantStore).mockImplementation((selector) => selector(state));
  });

  it.each([
    ['members', 'users'],
    ['audit', 'audit-logs'],
    ['', 'settings'],
  ])('keeps the original %s tab link within the selected tenant', async (tab, destination) => {
    render(
      <Suspense>
        <Routes>{tenantAdministrationRoutes()}</Routes>
      </Suspense>,
      {
        route: '/tenant/org-42/org-settings/' + tab,
      }
    );
    const link = await screen.findByRole('link', {
      name:
        destination === 'users'
          ? /open users|manage members/i
          : destination === 'audit-logs'
            ? /open audit logs/i
            : /edit in tenant settings/i,
    });
    expect(link).toHaveAttribute('href', '/tenant/org-42/' + destination);
  });

  it.each([
    ['registry', registryService.list],
    ['smtp', smtpService.getConfig],
  ] as const)('loads %s settings from the active tenant', async (tab, read) => {
    render(
      <Suspense>
        <Routes>{tenantAdministrationRoutes()}</Routes>
      </Suspense>,
      {
        route: '/tenant/org-42/org-settings/' + tab,
      }
    );
    await waitFor(() => expect(read).toHaveBeenCalledWith('org-42'), { timeout: 10000 });
  });

  it.each(['genes', 'clusters'])('opens compatibility at the original %s bookmark', async (tab) => {
    render(
      <Suspense>
        <Routes>{tenantAdministrationRoutes()}</Routes>
      </Suspense>,
      {
        route: '/tenant/org-42/org-settings/' + tab + '?section=details',
      }
    );
    const link = await screen.findByRole('link', {
      name: /Open in the compatibility workbench|fullHost.compatibility/,
    });
    expect(link.getAttribute('href')).toMatch(
      new RegExp('/tenant/org-42/org-settings/' + tab + '\\?section=details$')
    );
  });
});
