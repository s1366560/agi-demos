import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentTeammatesPanel } from '@/components/project/AgentTeammatesPanel';
import { definitionsService } from '@/services/agent/definitionsService';

import type { AgentDefinition } from '@/types/multiAgent';

vi.mock('@/services/agent/definitionsService', () => ({
  definitionsService: {
    list: vi.fn(),
  },
}));

vi.mock('@/services/agentService', () => ({
  agentService: {
    createConversation: vi.fn(),
  },
}));

const renderPanel = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AgentTeammatesPanel projectId="project-1" />
      </MemoryRouter>
    </QueryClientProvider>
  );
};

const makeAgent = (overrides: Partial<AgentDefinition> = {}): AgentDefinition => ({
  id: 'agent-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  name: 'workspace_iteration_reviewer',
  display_name: 'Workspace Iteration Reviewer',
  system_prompt: null,
  trigger: null,
  persona_files: [],
  model: 'inherit',
  temperature: null,
  max_tokens: null,
  max_iterations: 3,
  allowed_tools: null,
  allowed_skills: null,
  allowed_mcp_servers: null,
  bindings: [],
  workspace_dir: null,
  workspace_config: null,
  can_spawn: true,
  max_spawn_depth: 1,
  agent_to_agent_enabled: true,
  agent_to_agent_allowlist: null,
  discoverable: true,
  source: 'database',
  enabled: true,
  max_retries: 1,
  fallback_models: [],
  total_invocations: 0,
  avg_execution_time_ms: null,
  success_rate: 1,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: null,
  metadata: {},
  ...overrides,
});

describe('AgentTeammatesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders responsive custom rows without the cramped AntD meta layout', async () => {
    vi.mocked(definitionsService.list).mockResolvedValueOnce([makeAgent()]);

    const { container } = renderPanel();

    expect(await screen.findByText('Workspace Iteration Reviewer')).toBeInTheDocument();
    expect(container.querySelector('.ant-list-item-meta')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start conversation/i })).toHaveClass('w-full');
  });
});
