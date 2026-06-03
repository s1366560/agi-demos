import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentDefinitionDetail } from '../../../pages/tenant/AgentDefinitionDetail';
import { AgentDefinitions } from '../../../pages/tenant/AgentDefinitions';
import { definitionsService } from '../../../services/agent/definitionsService';

import type { AgentDefinition } from '../../../types/multiAgent';

vi.mock('../../../services/agent/definitionsService', () => ({
  definitionsService: {
    list: vi.fn(),
    getById: vi.fn(),
    setEnabled: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../../../components/agent/AgentDefinitionModal', () => ({
  AgentDefinitionModal: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="agent-definition-modal" /> : null,
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

describe('AgentDefinitionDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
      expect(definitionsService.getById).toHaveBeenCalledWith('agent-1');
    });

    expect(await screen.findByRole('heading', { name: 'Research Agent' })).toBeInTheDocument();
    expect(
      screen.getByText('Investigate sources and produce concise findings.')
    ).toBeInTheDocument();
    expect(screen.getByText('research and source-backed synthesis')).toBeInTheDocument();
    expect(screen.getByText('web_search')).toBeInTheDocument();
    expect(screen.getByText('binding-1')).toBeInTheDocument();
    expect(screen.getAllByText(/"owner": "platform"/).length).toBeGreaterThan(0);
    expect(screen.getByText(/"fallback_models"/)).toBeInTheDocument();
  });

  it('links definition cards to the detail route', async () => {
    vi.mocked(definitionsService.list).mockResolvedValue([makeDefinition()]);

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
});
