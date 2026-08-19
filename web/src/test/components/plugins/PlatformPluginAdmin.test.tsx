import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PlatformPluginAdmin } from '@/components/plugins/PlatformPluginAdmin';
import type { CutoverReadiness } from '@/services/admin/platformPluginAdminService';

vi.mock('@/services/admin/platformPluginAdminService', () => ({
  platformPluginAdminService: {
    snapshot: vi.fn(),
    cutoverReadiness: vi.fn(),
    approveCutover: vi.fn(),
    revokeCutover: vi.fn(),
  },
}));

import { platformPluginAdminService } from '@/services/admin/platformPluginAdminService';

const snapshotPayload = {
  version: 7,
  nonce: 'n',
  profile_id: 'memstack-default',
  digest: 'sha256:abc',
  payload: {
    schema_version: 1,
    profile_id: 'memstack-default',
    digest: 'sha256:abc',
    plugins: [
      {
        id: 'workspace-runtime',
        layer_id: 'memstack.kernel-base',
        provides: [{ kind: 'hook', id: 'on_session_start', contract: 'hook:x' }],
      },
    ],
  },
};

const readinessReady: CutoverReadiness = {
  ready: true,
  checked_at: '2026-08-19T00:00:00Z',
  shadow: {
    ready: true,
    checked_at: '2026-08-19T00:00:00Z',
    capabilities: [],
    reasons: [],
  },
  rollback_drill: { ready: true, checked_at: '2026-08-19T00:00:00Z', reasons: [] },
  approval: null,
  operator_approved: false,
  reasons: [],
};

describe('PlatformPluginAdmin', () => {
  beforeEach(() => {
    vi.mocked(platformPluginAdminService.snapshot).mockResolvedValue(
      snapshotPayload as never
    );
    vi.mocked(platformPluginAdminService.cutoverReadiness).mockResolvedValue(readinessReady);
    vi.mocked(platformPluginAdminService.approveCutover).mockResolvedValue({} as never);
    vi.mocked(platformPluginAdminService.revokeCutover).mockResolvedValue({} as never);
  });

  it('renders the cutover gate, profile view, and row view with layer provenance', async () => {
    render(<PlatformPluginAdmin />);
    expect(await screen.findByTestId('cutover-gate-panel')).toBeTruthy();
    expect(await screen.findByTestId('platform-profile-view')).toBeTruthy();
    expect((await screen.findByTestId('platform-profile-view')).textContent).toContain(
      'memstack-default'
    );
    const rows = await screen.findByTestId('platform-row-view');
    expect(rows.textContent).toContain('workspace-runtime');
    expect(rows.textContent).toContain('memstack.kernel-base');
  });

  it('approve button calls the cutover approve endpoint', async () => {
    render(<PlatformPluginAdmin />);
    const approve = await screen.findByRole('button', { name: /approve cutover/i });
    fireEvent.click(approve);
    await waitFor(() =>
      expect(platformPluginAdminService.approveCutover).toHaveBeenCalledTimes(1)
    );
  });

  it('revoke is enabled once operator approved and calls revoke endpoint', async () => {
    vi.mocked(platformPluginAdminService.cutoverReadiness).mockResolvedValue({
      ...readinessReady,
      operator_approved: true,
      approval: {
        capability: 'agent_runtime',
        approved_by: 'admin',
        approved_at: '2026-08-19T00:00:00Z',
        expires_at: '2026-08-26T00:00:00Z',
        evidence: {},
      },
    });
    render(<PlatformPluginAdmin />);
    const revoke = await screen.findByRole('button', { name: /revoke approval/i });
    fireEvent.click(revoke);
    await waitFor(() =>
      expect(platformPluginAdminService.revokeCutover).toHaveBeenCalledTimes(1)
    );
  });
});
