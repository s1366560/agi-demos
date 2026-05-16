import { describe, expect, it, vi, beforeEach } from 'vitest';

import { AddAgentModal } from '@/components/workspace/AddAgentModal';
import { useDefinitions, useListDefinitions } from '@/stores/agentDefinitions';
import type { AgentDefinition } from '@/types/multiAgent';

import { render, screen } from '../../utils';

vi.mock('@/stores/agentDefinitions', () => ({
  useDefinitions: vi.fn(),
  useListDefinitions: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: string | { defaultValue?: string }) =>
      typeof options === 'string' ? options : (options?.defaultValue ?? _key),
    i18n: { language: 'en-US', changeLanguage: vi.fn() },
  }),
}));

describe('AddAgentModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const definition: AgentDefinition = {
      id: 'agent-1',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      name: 'planner',
      display_name: 'Planner',
      system_prompt: 'Plan',
      trigger: null,
      persona_files: [],
      model: null,
      temperature: null,
      max_tokens: null,
      max_iterations: 1,
      allowed_tools: null,
      allowed_skills: null,
      allowed_mcp_servers: null,
      bindings: [],
      workspace_dir: null,
      workspace_config: null,
      can_spawn: false,
      max_spawn_depth: 0,
      agent_to_agent_enabled: false,
      agent_to_agent_allowlist: null,
      discoverable: true,
      source: 'database',
      enabled: true,
      max_retries: 0,
      fallback_models: [],
      total_invocations: 0,
      avg_execution_time_ms: null,
      success_rate: null,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
      metadata: {},
    };
    vi.mocked(useDefinitions).mockReturnValue([definition]);
    vi.mocked(useListDefinitions).mockReturnValue(vi.fn().mockResolvedValue(undefined));
  });

  it('renders translated labels, placeholders, and placement hint', async () => {
    render(<AddAgentModal open onClose={vi.fn()} onSubmit={vi.fn()} hexCoords={{ q: 2, r: -1 }} />);

    expect(await screen.findByText('Add Agent to Workspace')).toBeInTheDocument();
    expect(screen.getByText('Agent Definition')).toBeInTheDocument();
    expect(screen.getByText('Display Name')).toBeInTheDocument();
    expect(screen.getByText('Description')).toBeInTheDocument();
    expect(screen.getByText('Will be placed at hex (2, -1)')).toBeInTheDocument();
    expect(screen.getByText('Add')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });
});
