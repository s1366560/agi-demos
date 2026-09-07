import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { InviteAccept } from '@/pages/InviteAccept';

const mocks = vi.hoisted(() => ({
  verify: vi.fn(),
  authenticated: true,
  availability: { available: false, owner: {} },
  listeners: new Set<() => void>(),
}));
vi.mock('@/stores/auth', () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ isAuthenticated: mocks.authenticated, user: null }),
}));
vi.mock('@/services/invitationService', () => ({
  invitationService: { verify: mocks.verify },
}));
vi.mock('@/plugins/webOperationAdmissionV2', () => ({
  getWebOperationAvailabilityV2: () => mocks.availability,
  subscribeWebOperationAvailabilityV2: (listener: () => void) => {
    mocks.listeners.add(listener);
    return () => mocks.listeners.delete(listener);
  },
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_key: string, fallback: string) => fallback ?? _key }),
}));

function renderInvite() {
  return render(
    <MemoryRouter initialEntries={['/invite/invalid-qa-token']}>
      <Routes>
        <Route path="/invite/:token" element={<InviteAccept />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('InviteAccept generation readiness', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authenticated = true;
    mocks.availability = { available: false, owner: {} };
    mocks.listeners.clear();
    mocks.verify.mockResolvedValue({ valid: false });
  });

  it('waits for deferred authenticated generation then verifies without manual retry', async () => {
    renderInvite();
    await act(async () => {
      await Promise.resolve();
    });
    expect(mocks.verify).not.toHaveBeenCalled();
    await act(async () => {
      mocks.availability = { available: true, owner: {} };
      for (const listener of mocks.listeners) listener();
    });
    expect(await screen.findByText('Invalid Invitation')).toBeInTheDocument();
    expect(mocks.verify).toHaveBeenCalledWith('invalid-qa-token');
  });

  it('verifies an anonymous public invitation without requiring an authenticated generation', async () => {
    mocks.authenticated = false;
    renderInvite();
    expect(await screen.findByText('Invalid Invitation')).toBeInTheDocument();
    expect(mocks.verify).toHaveBeenCalledWith('invalid-qa-token');
  });

  it('does not verify when unmounted before generation becomes available', async () => {
    const view = renderInvite();
    view.unmount();
    await act(async () => {
      mocks.availability = { available: true, owner: {} };
      for (const listener of mocks.listeners) listener();
    });
    await waitFor(() => expect(mocks.verify).not.toHaveBeenCalled());
  });
});
