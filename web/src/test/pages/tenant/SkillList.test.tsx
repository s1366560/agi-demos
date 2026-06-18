import { Suspense } from 'react';

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { SkillList } from '@/pages/tenant/SkillList';
import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { fireEvent, render, screen, waitFor } from '../../utils';

import type { SkillResponse, TenantSkillConfigResponse } from '@/types/agent';
import type { Project, Tenant } from '@/types/memory';

const navigateMock = vi.hoisted(() => vi.fn());
const skillApiMock = vi.hoisted(() => ({
  importPackage: vi.fn(),
  importZip: vi.fn(),
  exportPackage: vi.fn(),
  listVersions: vi.fn(),
  rollback: vi.fn(),
}));

const skillStore = vi.hoisted(() => ({
  skills: [] as SkillResponse[],
  tenantConfigs: [] as TenantSkillConfigResponse[],
  total: 0,
  page: 1,
  pageSize: 20,
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
    useNavigate: () => navigateMock,
  };
});

vi.mock('@/stores/skill', () => ({
  useSkillStore: () => skillStore,
  useSkillLoading: () => false,
  useSkillError: () => null,
  useActiveSkillsCount: () => skillStore.skills.filter((skill) => skill.status === 'active').length,
  useSkillTotal: () => skillStore.total,
}));

vi.mock('@/services/skillService', () => ({
  skillAPI: skillApiMock,
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

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'project-1',
    tenant_id: 'tenant-1',
    name: 'Project Alpha',
    owner_id: 'admin-1',
    member_ids: ['admin-1'],
    memory_rules: {
      max_episodes: 100,
      retention_days: 30,
      auto_refresh: true,
      refresh_interval: 3600,
    },
    graph_config: {
      max_nodes: 1000,
      max_edges: 5000,
      similarity_threshold: 0.75,
      community_detection: true,
    },
    is_public: false,
    created_at: '2026-06-15T00:00:00Z',
    ...overrides,
  };
}

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

function renderSkillList(route = '/tenant/tenant-1/skills') {
  return render(
    <Routes>
      <Route
        path="/tenant/:tenantId/skills"
        element={
          <Suspense fallback={<div>Loading</div>}>
            <SkillList />
          </Suspense>
        }
      />
    </Routes>,
    { route }
  );
}

describe('SkillList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    skillStore.skills = [];
    skillStore.tenantConfigs = [];
    skillStore.total = 0;
    skillStore.page = 1;
    skillStore.pageSize = 20;
    skillStore.listSkills.mockResolvedValue(undefined);
    skillStore.listTenantConfigs.mockResolvedValue(undefined);
    skillApiMock.importPackage.mockResolvedValue({
      action: 'created',
      skill: systemSkill({ is_system_skill: false, scope: 'tenant', source: 'database' }),
      message: 'Skill imported',
    });
    skillApiMock.importZip.mockResolvedValue({
      action: 'created',
      skill: systemSkill({ is_system_skill: false, scope: 'tenant', source: 'database' }),
      message: 'Skill imported',
    });
    useTenantStore.setState({
      currentTenant: makeTenant(),
    });
    useProjectStore.setState({
      projects: [],
      currentProject: null,
      isLoading: false,
      error: null,
      total: 0,
      page: 1,
      pageSize: 20,
      listProjects: vi.fn().mockResolvedValue(undefined),
    });
  });

  it('routes skill creation to chat instead of the removed manual creation page', async () => {
    renderSkillList();

    fireEvent.click(await screen.findByRole('button', { name: 'Create in chat' }));

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith('/tenant/tenant-1/agent-workspace', {
        state: {
          suggestedPrompt: 'Help me create a new skill.',
        },
      });
    });
    expect(navigateMock).not.toHaveBeenCalledWith('new');
  });

  it('shows tenant-level system skill disable controls', async () => {
    skillStore.skills = [systemSkill()];

    renderSkillList();

    await waitFor(() => {
      expect(skillStore.listTenantConfigs).toHaveBeenCalled();
    });
    expect(
      await screen.findByRole('button', { name: 'Disable memory-flush for this tenant' })
    ).toBeInTheDocument();
  });

  it('uses the route tenant instead of a stale tenant store value for server requests', async () => {
    useTenantStore.setState({
      currentTenant: makeTenant({ id: 'stale-tenant' }),
    });
    useProjectStore.setState({
      projects: [makeProject({ tenant_id: 'route-tenant' })],
    });

    renderSkillList('/tenant/route-tenant/skills');

    await waitFor(() => {
      expect(skillStore.listSkills).toHaveBeenCalledWith(
        expect.objectContaining({ tenant_id: 'route-tenant' })
      );
      expect(skillStore.listTenantConfigs).toHaveBeenCalledWith({ tenant_id: 'route-tenant' });
      expect(useProjectStore.getState().listProjects).toHaveBeenCalledWith('route-tenant', {
        page_size: 100,
      });
    });
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

    renderSkillList();

    expect(await screen.findByText('Tenant disabled')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Restore memory-flush system default for this tenant' })
    ).toBeInTheDocument();
  });

  it('reloads the full registry when a submitted search is cleared', async () => {
    skillStore.skills = [
      systemSkill({
        id: 'system-skill-1',
        name: 'memory-flush',
        description: 'Flush memory extraction',
      }),
      systemSkill({
        id: 'system-skill-2',
        name: 'pdf-processing',
        description: 'Extract PDF tables',
      }),
    ];

    renderSkillList();

    await waitFor(() => {
      expect(skillStore.listSkills).toHaveBeenCalled();
    });
    skillStore.listSkills.mockClear();

    const searchInput = screen.getByRole('searchbox', { name: 'Search skills...' });
    fireEvent.change(searchInput, { target: { value: 'memory' } });
    fireEvent.keyDown(searchInput, { key: 'Enter', code: 'Enter' });

    await waitFor(() => {
      expect(skillStore.listSkills).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'memory', page: 1, pageSize: 20 })
      );
    });
    skillStore.listSkills.mockClear();

    fireEvent.change(searchInput, { target: { value: '' } });

    await waitFor(() => {
      expect(skillStore.listSkills).toHaveBeenCalledWith(
        expect.objectContaining({ search: undefined, page: 1, pageSize: 20 })
      );
    });
  });

  it('requests server-side filtering by tenant, system, and project scope', async () => {
    useProjectStore.setState({
      projects: [makeProject()],
    });
    skillStore.skills = [
      systemSkill({ id: 'system-skill', name: 'system-skill', scope: 'system' }),
      systemSkill({
        id: 'tenant-skill',
        name: 'tenant-skill',
        is_system_skill: false,
        source: 'database',
        scope: 'tenant',
        project_id: null,
      }),
      systemSkill({
        id: 'project-skill',
        name: 'project-skill',
        is_system_skill: false,
        source: 'database',
        scope: 'project',
        project_id: 'project-1',
      }),
    ];

    renderSkillList();

    expect(await screen.findByRole('button', { name: 'system-skill' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'tenant-skill' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'project-skill' })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Filter skills by scope'), {
      target: { value: 'project:project-1' },
    });

    await waitFor(() => {
      expect(skillStore.listSkills).toHaveBeenCalledWith(
        expect.objectContaining({
          scope: 'project',
          project_id: 'project-1',
          page: 1,
          pageSize: 20,
        })
      );
    });
    expect(screen.getAllByText('Project Alpha').length).toBeGreaterThan(0);
  });

  it('requests the selected page from the server', async () => {
    skillStore.total = 45;
    skillStore.skills = Array.from({ length: 20 }, (_, index) =>
      systemSkill({
        id: `skill-${String(index + 1)}`,
        name: `skill-${String(index + 1)}`,
      })
    );

    renderSkillList();

    const pageTwo = await screen.findByTitle('2');
    fireEvent.click(pageTwo);

    await waitFor(() => {
      expect(skillStore.listSkills).toHaveBeenCalledWith(
        expect.objectContaining({ page: 2, pageSize: 20 })
      );
    });
  });

  it('imports pasted skill packages into the selected project scope', async () => {
    useProjectStore.setState({
      projects: [makeProject()],
    });

    renderSkillList();

    fireEvent.click(await screen.findByRole('button', { name: 'Import' }));
    fireEvent.change(screen.getByLabelText('Import scope'), {
      target: { value: 'project' },
    });
    fireEvent.change(screen.getByLabelText('Project'), {
      target: { value: 'project-1' },
    });
    fireEvent.change(
      screen.getByPlaceholderText('Paste SKILL.md content with YAML frontmatter...'),
      {
        target: {
          value: '---\nname: imported-skill\ndescription: Imported skill\n---\n\n# Imported skill',
        },
      }
    );

    const importButtons = screen.getAllByRole('button', { name: 'Import' });
    fireEvent.click(importButtons[importButtons.length - 1]);

    await waitFor(() => {
      expect(skillApiMock.importPackage).toHaveBeenCalledWith(
        expect.objectContaining({
          scope: 'project',
          project_id: 'project-1',
          overwrite: false,
        }),
        { tenant_id: 'tenant-1' }
      );
    });
  });
});
