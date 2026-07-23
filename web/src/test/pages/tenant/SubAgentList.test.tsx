/**
 * SubAgentList.test.tsx
 *
 * SubAgentList is now a legacy route shim that redirects to Agent Definitions.
 * These tests verify the redirect targets, with and without a tenant id.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { SubAgentList } from '../../../pages/tenant/SubAgentList';

const LocationProbe = () => {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
};

describe('SubAgentList', () => {
  it('redirects /tenant/subagents to /tenant/agent-definitions', async () => {
    render(
      <MemoryRouter initialEntries={['/tenant/subagents']}>
        <Routes>
          <Route path="/tenant/subagents" element={<SubAgentList />} />
          <Route path="/tenant/agent-definitions" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/tenant/agent-definitions');
    });
  });

  it('preserves the tenant id when redirecting', async () => {
    render(
      <MemoryRouter initialEntries={['/tenant/acme/subagents']}>
        <Routes>
          <Route path="/tenant/:tenantId/subagents" element={<SubAgentList />} />
          <Route path="/tenant/:tenantId/agent-definitions" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/tenant/acme/agent-definitions');
    });
  });
});
