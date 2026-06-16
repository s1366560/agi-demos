import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentDefinitionDetail } from '../../../pages/tenant/AgentDefinitionDetail';
import { AgentDefinitions } from '../../../pages/tenant/AgentDefinitions';
import { definitionsService } from '../../../services/agent/definitionsService';
import { useAuthStore } from '../../../stores/auth';
import { useProjectStore } from '../../../stores/project';
import { useTenantStore } from '../../../stores/tenant';

import type { AgentDefinition } from '../../../types/multiAgent';
import type { Project } from '../../../types/memory';

vi.mock('../../../services/agent/definitionsService', () => ({
  definitionsService: {
    list: vi.fn(),
    listPage: vi.fn(),
    getById: vi.fn(),
    setEnabled: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../../../components/agent/AgentDefinitionModal', () => ({
  AgentDefinitionModal: ({
    isOpen,
    initialProjectId,
    tenantId,
    projectOptions = [],
  }: {
    isOpen: boolean;
    initialProjectId?: string | null;
    tenantId?: string | null;
    projectOptions?: Array<{ id: string; name: string }>;
  }) =>
    isOpen ? (
      <div
        data-testid="agent-definition-modal"
        data-initial-project-id={initialProjectId ?? 'tenant'}
        data-tenant-id={tenantId ?? ''}
      >
        {projectOptions.map((project) => (
          <span key={project.id}>{project.name}</span>
        ))}
      </div>
    ) : null,
}));

const makeDefinition = (overrides: Partial<AgentDefinition> = {}): AgentDefinition => ({
  id: 'agent-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  name: 'research_agent',
  display_name: 'Research Agent',
  system_prompt: 'Investigate sources and produce concise findings.',
  trigger: {
    mode: 'hybrid',
    semantic: 'research and source-backed synthesis',
    keywords: ['research', 'sources'],
  },
  persona_files: ['AGENTS.md', 'RESEARCH.md'],
  model: 'gpt-5.5',
  temperature: 0.2,
  max_tokens: 8192,
  max_iterations: 12,
  allowed_tools: ['web_search', 'read_file'],
  allowed_skills: ['researcher'],
  allowed_mcp_servers: ['github'],
  bindings: [
    {
      id: 'binding-1',
      tenant_id: 'tenant-1',
      agent_id: 'agent-1',
      channel_type: 'workspace',
      channel_id: 'workspace-1',
      account_id: null,
      peer_id: null,
      group_id: 'default',
      priority: 10,
      enabled: true,
      created_at: '2026-06-03T06:00:00Z',
      specificity_score: 4,
    },
  ],
  workspace_dir: '/workspace/research',
  workspace_config: {
    type: 'isolated',
    base_dir: '/workspace/research',
    sandbox_scope: 'agent',
  },
  can_spawn: true,
  max_spawn_depth: 2,
  agent_to_agent_enabled: true,
  agent_to_agent_allowlist: ['planner'],
  spawn_policy: {
    max_depth: 2,
    max_active_runs: 4,
    max_children_per_requester: 2,
    allowed_subagents: ['planner'],
  },
  tool_policy: {
    allow: ['web_search'],
    deny: ['bash'],
    precedence: 'deny_first',
  },
  session_policy: {
    dm_scope: 'global',
    max_messages: 20,
    idle_reset_minutes: 30,
    daily_reset_hour: 5,
    session_ttl_hours: 48,
  },
  delegate_config: {
    capability_tier: 'read_write',
    max_delegation_depth: 2,
    allowed_tools: ['read_file'],
    budget_limit_tokens: 12000,
  },
  discoverable: true,
  source: 'database',
  enabled: true,
  max_retries: 3,
  fallback_models: ['gpt-5.3-codex-spark'],
  total_invocations: 42,
  avg_execution_time_ms: 1234,
  success_rate: 0.91,
  created_at: '2026-06-03T05:00:00Z',
  updated_at: '2026-06-03T06:00:00Z',
  metadata: {
    owner: 'platform',
    tier: 'standard',
  },
  ...overrides,
});

const makeDefinitionPage = (definitions: AgentDefinition[]) => ({
  definitions,
  total: definitions.length,
  limit: 20,
  offset: 0,
});

const makeTenant = () => ({
  id: 'tenant-1',
  name: 'Tenant One',
  owner_id: 'admin-1',
  plan: 'enterprise' as const,
  max_projects: 100,
  max_users: 100,
  max_storage: 1024,
  created_at: '2026-06-03T05:00:00Z',
});

describe('AgentDefinitionDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
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

  it('loads one definition and renders structured sections plus raw details', async () => {
    vi.mocked(definitionsService.getById).mockResolvedValue(makeDefinition());

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-definitions/agent-1']}>
        <Routes>
          <Route
            path="/tenant/:tenantId/agent-definitions/:definitionId"
            element={<AgentDefinitionDetail />}
          />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(definitionsService.getById).toHaveBeenCalledWith('agent-1', {
        tenant_id: 'tenant-1',
      });
    });

    expect(await screen.findByRole('heading', { name: 'Research Agent' })).toBeInTheDocument();
    expect(
      screen.getByText('Investigate sources and produce concise findings.')
    ).toBeInTheDocument();
    expect(screen.getByText('research and source-backed synthesis')).toBeInTheDocument();
    expect(screen.getAllByText('web_search').length).toBeGreaterThan(0);
    expect(screen.getByText('bash')).toBeInTheDocument();
    expect(screen.getByText('deny_first')).toBeInTheDocument();
    expect(screen.getByText('Session and delegation')).toBeInTheDocument();
    expect(screen.getByText('global')).toBeInTheDocument();
    expect(screen.getByText('read_write')).toBeInTheDocument();
    expect(screen.getByText('12000')).toBeInTheDocument();
    expect(screen.getByText('binding-1')).toBeInTheDocument();
    expect(screen.getAllByText(/"owner": "platform"/).length).toBeGreaterThan(0);
    expect(screen.getByText(/"fallback_models"/)).toBeInTheDocument();
  });

  it('links definition cards to the detail route', async () => {
    vi.mocked(definitionsService.listPage).mockResolvedValue(
      makeDefinitionPage([makeDefinition()])
    );

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-definitions']}>
        <Routes>
          <Route path="/tenant/:tenantId/agent-definitions" element={<AgentDefinitions />} />
        </Routes>
      </MemoryRouter>
    );

    const link = await screen.findByRole('link', { name: 'Research Agent' });
    expect(link).toHaveAttribute('href', '/tenant/tenant-1/agent-definitions/agent-1');
  });

  it('filters definitions by scope and creates with the selected project scope', async () => {
    useAuthStore.setState({
      user: {
        id: 'admin-1',
        email: 'admin@example.com',
        name: 'Admin',
        roles: ['admin'],
        is_active: true,
        created_at: '2026-06-03T05:00:00Z',
      },
      isAuthenticated: true,
    });
    useProjectStore.setState({
      projects: [
        {
          id: 'project-1',
          tenant_id: 'tenant-1',
          name: 'Project Alpha',
          owner_id: 'admin-1',
          member_ids: ['admin-1'],
          memory_rules: {},
          graph_config: {},
          is_public: false,
          created_at: '2026-06-03T05:00:00Z',
        } as Project,
      ],
    });
    const tenantDefinition = makeDefinition({
      id: 'tenant-agent',
      project_id: null,
      name: 'tenant_agent',
      display_name: 'Tenant Agent',
    });
    const projectDefinition = makeDefinition({
      id: 'project-agent',
      project_id: 'project-1',
      name: 'project_agent',
      display_name: 'Project Agent',
    });
    vi.mocked(definitionsService.listPage).mockImplementation(async (params = {}) => {
      if (params.project_id === 'project-1') {
        return makeDefinitionPage([projectDefinition]);
      }
      return makeDefinitionPage([tenantDefinition, projectDefinition]);
    });

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/agent-definitions']}>
        <Routes>
          <Route path="/tenant/:tenantId/agent-definitions" element={<AgentDefinitions />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByRole('link', { name: 'Tenant Agent' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Project Agent' })).toBeInTheDocument();
    expect(screen.getAllByText('Project Alpha').length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText('Filter by scope'), {
      target: { value: 'project-1' },
    });

    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Tenant Agent' })).not.toBeInTheDocument();
    });
    expect(screen.getByRole('link', { name: 'Project Agent' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Create Agent' }));

    expect(screen.getByTestId('agent-definition-modal')).toHaveAttribute(
      'data-initial-project-id',
      'project-1'
    );
    expect(screen.getByTestId('agent-definition-modal')).toHaveAttribute(
      'data-tenant-id',
      'tenant-1'
    );
  });
});
