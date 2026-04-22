/**
 * Tests for P2-4 Track D curated skills UI.
 *
 * Focus on the new lifecycle affordances:
 *   - Version dropdown appears when a source_skill_id has multiple curated versions
 *   - Deprecated toggle propagates to the list call
 *   - Admin approve dialog exposes bump selector and previews the effective semver
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import AdminSkillReview from '../../../pages/admin/AdminSkillReview';
import CuratedSkills from '../../../pages/tenant/CuratedSkills';
import { curatedSkillAPI } from '../../../services/curatedSkillService';
import { fireEvent, render, screen, waitFor } from '../../utils';

vi.mock('../../../services/curatedSkillService', () => ({
  curatedSkillAPI: {
    list: vi.fn(),
    fork: vi.fn(),
    listMySubmissions: vi.fn(),
    withdrawSubmission: vi.fn(),
    adminList: vi.fn(),
    adminApprove: vi.fn(),
    adminReject: vi.fn(),
  },
}));

function withQuery(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

function makeCurated(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'c1',
    semver: '0.1.0',
    revision_hash: 'abcdef0123456789abcdef0123456789',
    source_skill_id: 'skill_1',
    source_tenant_id: 't1',
    approved_by: 'admin',
    approved_at: '2024-01-01T00:00:00Z',
    status: 'active',
    payload: { name: 'echo', description: 'Echo skill' },
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('CuratedSkills (tenant)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(curatedSkillAPI.listMySubmissions).mockResolvedValue([]);
  });

  it('renders a version selector when a source has multiple versions', async () => {
    vi.mocked(curatedSkillAPI.list).mockResolvedValue([
      makeCurated({ id: 'c1', semver: '0.1.0', status: 'active' }),
      makeCurated({
        id: 'c2',
        semver: '0.2.0',
        status: 'active',
        revision_hash: '2'.repeat(32),
      }),
    ]);

    render(withQuery(<CuratedSkills />));
    await waitFor(() => {
      expect(screen.getByText('echo')).toBeInTheDocument();
    });
    // Select shows the latest version first (newest-first sort).
    const select = screen.getByRole('combobox');
    expect(select).toBeInTheDocument();
    // "2 个版本" hint tells the user other versions are selectable.
    expect(screen.getByText(/2 个版本/)).toBeInTheDocument();
  });

  it('does not render a version selector when a source has only one version', async () => {
    vi.mocked(curatedSkillAPI.list).mockResolvedValue([
      makeCurated({ id: 'c1', semver: '0.1.0' }),
    ]);
    render(withQuery(<CuratedSkills />));
    await waitFor(() => {
      expect(screen.getByText('echo')).toBeInTheDocument();
    });
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.getByText('v0.1.0')).toBeInTheDocument();
  });

  it('passes include_deprecated=true when the toggle is enabled', async () => {
    vi.mocked(curatedSkillAPI.list).mockResolvedValue([]);
    render(withQuery(<CuratedSkills />));
    // Wait for query settled and the toggle label to render.
    await screen.findByText('包含已弃用版本');
    expect(curatedSkillAPI.list).toHaveBeenCalledWith({ include_deprecated: false });
    const toggle = screen.getByRole('switch');
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(curatedSkillAPI.list).toHaveBeenLastCalledWith({ include_deprecated: true });
    });
  });
});

describe('AdminSkillReview bump selector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(curatedSkillAPI.adminList).mockResolvedValue([
      {
        id: 'sub1',
        submitter_tenant_id: 't1',
        submitter_user_id: 'u1',
        source_skill_id: 'skill_1',
        proposed_semver: '1.2.3',
        submission_note: null,
        status: 'pending',
        reviewer_id: null,
        review_note: null,
        reviewed_at: null,
        created_at: '2024-01-01T00:00:00Z',
        skill_snapshot: { name: 'echo', description: 'Echo skill' },
      },
    ]);
  });

  it('previews the effective semver when a bump is selected and forwards it on approve', async () => {
    vi.mocked(curatedSkillAPI.adminApprove).mockResolvedValue(makeCurated() as never);
    render(withQuery(<AdminSkillReview />));

    const approveBtn = await screen.findByRole('button', { name: /Approve/i });
    fireEvent.click(approveBtn);

    // Dialog open — default "trust submitter" preview shows 1.2.3 near "最终发布版本".
    const previewLabel = await screen.findByText(/最终发布版本/);
    const previewRow = previewLabel.parentElement as HTMLElement;
    await waitFor(() => {
      expect(previewRow.textContent).toContain('v1.2.3');
    });

    // Switch to "minor" bump — preview should flip to 1.3.0.
    fireEvent.click(screen.getByRole('radio', { name: /minor/ }));
    await waitFor(() => {
      expect(previewRow.textContent).toContain('v1.3.0');
    });

    // Dialog Approve button (second Approve in DOM).
    const allApprove = screen.getAllByRole('button', { name: /Approve/i });
    fireEvent.click(allApprove[allApprove.length - 1]!);
    await waitFor(() => {
      expect(curatedSkillAPI.adminApprove).toHaveBeenCalledWith('sub1', {
        review_note: null,
        bump: 'minor',
      });
    });
  });
});
