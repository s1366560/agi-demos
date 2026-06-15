import { Suspense } from 'react';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SkillList } from '@/pages/tenant/SkillList';

import { fireEvent, render, screen, waitFor } from '../../utils';

import type { SkillResponse, TenantSkillConfigResponse } from '@/types/agent';

const navigateMock = vi.hoisted(() => vi.fn());

const skillStore = vi.hoisted(() => ({
  skills: [] as SkillResponse[],
  tenantConfigs: [] as TenantSkillConfigResponse[],
  listSkills: vi.fn(),
  listTenantConfigs: vi.fn(),
  deleteSkill: vi.fn(),
  updateSkillStatus: vi.fn(),
  disableSystemSkill: vi.fn(),
  enableSystemSkill: vi.fn(),
  clearError: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useLocation: () => ({ pathname: '/tenant/acme/skills' }),
    useNavigate: () => navigateMock,
  };
});

vi.mock('@/stores/skill', () => ({
  useSkillStore: () => skillStore,
  useSkillLoading: () => false,
  useSkillError: () => null,
  useActiveSkillsCount: () => skillStore.skills.filter((skill) => skill.status === 'active').length,
  useSkillTotal: () => skillStore.skills.length,
}));

function systemSkill(overrides: Partial<SkillResponse> = {}): SkillResponse {
  return {
    id: 'system-skill-1',
    tenant_id: 'tenant-1',
    project_id: null,
    name: 'memory-flush',
    description: 'Flush memory extraction',
    tools: [],
    full_content: null,
    status: 'active',
    scope: 'system',
    is_system_skill: true,
    source: 'filesystem',
    created_at: '2026-06-15T00:00:00Z',
    updated_at: '2026-06-15T00:00:00Z',
    metadata: {},
    agent_modes: [],
    spec_version: '1.0',
    current_version: 0,
    version_label: null,
    ...overrides,
  };
}

describe('SkillList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    skillStore.skills = [];
    skillStore.tenantConfigs = [];
    skillStore.listSkills.mockResolvedValue(undefined);
    skillStore.listTenantConfigs.mockResolvedValue(undefined);
  });

  it('routes skill creation to chat instead of the removed manual creation page', async () => {
    render(
      <Suspense fallback={<div>Loading</div>}>
        <SkillList />
      </Suspense>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Create in chat' }));

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith('/tenant/acme/agent-workspace', {
        state: {
          suggestedPrompt: 'Help me create a new skill.',
        },
      });
    });
    expect(navigateMock).not.toHaveBeenCalledWith('new');
  });

  it('shows tenant-level system skill disable controls', async () => {
    skillStore.skills = [systemSkill()];

    render(
      <Suspense fallback={<div>Loading</div>}>
        <SkillList />
      </Suspense>
    );

    await waitFor(() => {
      expect(skillStore.listTenantConfigs).toHaveBeenCalled();
    });
    expect(
      await screen.findByRole('button', { name: 'Disable memory-flush for this tenant' })
    ).toBeInTheDocument();
  });

  it('shows tenant-level system skill restore controls for disabled system skills', async () => {
    skillStore.skills = [systemSkill()];
    skillStore.tenantConfigs = [
      {
        id: 'cfg-1',
        tenant_id: 'tenant-1',
        system_skill_name: 'memory-flush',
        action: 'disable',
        override_skill_id: null,
        created_at: '2026-06-15T00:00:00Z',
        updated_at: '2026-06-15T00:00:00Z',
      },
    ];

    render(
      <Suspense fallback={<div>Loading</div>}>
        <SkillList />
      </Suspense>
    );

    expect(await screen.findByText('Tenant disabled')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Restore memory-flush system default for this tenant' })
    ).toBeInTheDocument();
  });
});
