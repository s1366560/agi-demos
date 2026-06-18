import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { SkillDetail } from '@/pages/tenant/SkillDetail';
import { useTenantStore } from '@/stores/tenant';

import { fireEvent, render, screen, waitFor } from '../../utils';

import type { SkillResponse } from '@/types/agent';
import type { Tenant } from '@/types/memory';

const skillApiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  exportPackage: vi.fn(),
  listVersions: vi.fn(),
  getEvolution: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

vi.mock('@/services/skillService', () => ({
  skillAPI: skillApiMocks,
}));

const skill: SkillResponse = {
  id: 'skill-1',
  tenant_id: 'tenant-1',
  project_id: null,
  name: 'report-writer',
  description: 'Create structured reports from source materials.',
  tools: ['Read'],
  full_content: '# Report writer\n\nUse source material carefully.',
  status: 'active',
  scope: 'tenant',
  is_system_skill: false,
  source: 'database',
  file_path: null,
  created_at: '2026-06-05T00:00:00Z',
  updated_at: '2026-06-05T00:00:00Z',
  metadata: {},
  agent_modes: [],
  license: null,
  compatibility: null,
  allowed_tools_raw: 'Read',
  spec_version: '1.0',
  current_version: 1,
  version_label: null,
};

function makeTenant(overrides: Partial<Tenant> = {}): Tenant {
  return {
    id: 'tenant-1',
    name: 'Acme',
    owner_id: 'admin-1',
    plan: 'enterprise',
    max_projects: 100,
    max_users: 100,
    max_storage: 1000,
    created_at: '2026-06-15T00:00:00Z',
    ...overrides,
  };
}

function renderSkillDetail(route = '/tenant/tenant-1/skills/skill-1') {
  return render(
    <Routes>
      <Route path="/tenant/:tenantId/skills/:skillId" element={<SkillDetail />} />
    </Routes>,
    { route }
  );
}

describe('SkillDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTenantStore.setState({ currentTenant: makeTenant() });
    skillApiMocks.get.mockResolvedValue(skill);
    skillApiMocks.exportPackage.mockResolvedValue({
      format: 'agentskill',
      skill,
      skill_md_content: '# Report writer\n\nUse source material carefully.',
      resource_files: {
        'docs/example.md': '# Example\n\nBundled file preview.',
        'schemas/input.json': '{ "type": "object" }',
      },
      version_number: 1,
      version_label: null,
    });
    skillApiMocks.listVersions.mockResolvedValue({ versions: [], total: 0 });
    skillApiMocks.getEvolution.mockResolvedValue({
      skill_id: 'skill-1',
      skill_name: 'report-writer',
      captured_session_count: 0,
      jobs: [],
      route: [],
      trigger: {
        capture_hook: 'conversation_end',
        capture_timing: '',
        scheduled_timing: '',
        min_sessions_per_skill: 3,
        min_avg_score: 0.8,
      },
    });
  });

  it('previews bundled skill files alongside SKILL.md', async () => {
    renderSkillDetail();

    await waitFor(() => {
      expect(screen.getAllByText('SKILL.md').length).toBeGreaterThan(0);
    });
    expect(skillApiMocks.get).toHaveBeenCalledWith('skill-1', { tenant_id: 'tenant-1' });

    expect(screen.getByRole('button', { name: 'docs' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'schemas' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'example.md' })).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'input.json' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'docs' }));
    expect(screen.queryByRole('button', { name: 'example.md' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'docs' }));
    fireEvent.click(screen.getByRole('button', { name: 'example.md' }));

    await waitFor(() => {
      expect(screen.getByText('Bundled file preview.')).toBeInTheDocument();
    });
  });

  it('shows the local assessment report from the detail tabs', async () => {
    renderSkillDetail();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Assessment' })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Assessment' }));

    expect(screen.getByText('Assessment report')).toBeInTheDocument();
    expect(screen.getAllByText('P0 required').length).toBeGreaterThan(0);
    expect(screen.getByText('Hardcoded credentials')).toBeInTheDocument();
    expect(screen.getByText('Package integrity')).toBeInTheDocument();
    expect(
      screen.getByText(
        'This report is a local static check. It does not run an external sandbox security scan or live quality evaluation.'
      )
    ).toBeInTheDocument();
  });

  it('loads skill detail with the route tenant when the store tenant is stale', async () => {
    useTenantStore.setState({ currentTenant: makeTenant({ id: 'stale-tenant' }) });

    renderSkillDetail('/tenant/route-tenant/skills/skill-1');

    await waitFor(() => {
      expect(skillApiMocks.get).toHaveBeenCalledWith('skill-1', { tenant_id: 'route-tenant' });
    });
    expect(skillApiMocks.exportPackage).toHaveBeenCalledWith('skill-1', {
      tenant_id: 'route-tenant',
    });
  });
});
