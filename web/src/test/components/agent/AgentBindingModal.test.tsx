import { fireEvent, render, screen, waitFor } from '../../utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentBindingModal } from '@/components/agent/AgentBindingModal';

import type { AgentDefinition } from '@/types/multiAgent';

const mocks = vi.hoisted(() => ({
  createBinding: vi.fn(),
  listDefinitions: vi.fn(),
  definitions: [] as AgentDefinition[],
}));

vi.mock('@/stores/agentBindings', () => ({
  useCreateBinding: () => mocks.createBinding,
  useBindingSubmitting: () => false,
}));

vi.mock('@/stores/agentDefinitions', () => ({
  useDefinitions: () => mocks.definitions,
  useListDefinitions: () => mocks.listDefinitions,
}));

const makeDefinition = (overrides: Partial<AgentDefinition> = {}): AgentDefinition => ({
  id: 'agent-1',
  tenant_id: 'tenant-1',
  project_id: null,
  name: 'tenant_agent',
  display_name: 'Tenant Agent',
  system_prompt: 'Handle tenant channels.',
  trigger: null,
  persona_files: [],
  model: 'inherit',
  temperature: 0.7,
  max_tokens: 4096,
  max_iterations: 10,
  allowed_tools: ['*'],
  allowed_skills: [],
  allowed_mcp_servers: [],
  bindings: [],
  workspace_dir: null,
  workspace_config: null,
  can_spawn: false,
  max_spawn_depth: 2,
  agent_to_agent_enabled: false,
  agent_to_agent_allowlist: null,
  spawn_policy: null,
  tool_policy: null,
  discoverable: true,
  source: 'database',
  enabled: true,
  max_retries: 0,
  fallback_models: [],
  total_invocations: 0,
  avg_execution_time_ms: null,
  success_rate: null,
  created_at: '2026-06-16T00:00:00Z',
  updated_at: null,
  metadata: {},
  ...overrides,
});

describe('AgentBindingModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.createBinding.mockResolvedValue({});
    mocks.listDefinitions.mockResolvedValue(undefined);
    mocks.definitions = [];
  });

  it('only offers tenant-level agents for channel binding creation', async () => {
    mocks.definitions = [
      makeDefinition({ id: 'tenant-agent', display_name: 'Tenant Agent', project_id: null }),
      makeDefinition({ id: 'project-agent', display_name: 'Project Agent', project_id: 'project-1' }),
    ];

    render(<AgentBindingModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);

    await waitFor(() => {
      expect(mocks.listDefinitions).toHaveBeenCalledWith({ enabled_only: true });
    });

    const [agentSelect] = screen.getAllByRole('combobox');
    fireEvent.mouseDown(agentSelect);

    fireEvent.click(await screen.findByText('Tenant Agent'));
    expect(screen.queryByText('Project Agent')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(mocks.createBinding).toHaveBeenCalledWith(
        expect.objectContaining({ agent_id: 'tenant-agent' })
      );
    });
  });

  it('loads definitions and creates bindings with the selected tenant', async () => {
    mocks.definitions = [
      makeDefinition({ id: 'tenant-agent', display_name: 'Tenant Agent', project_id: null }),
    ];

    render(
      <AgentBindingModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        tenantId="tenant-1"
      />
    );

    await waitFor(() => {
      expect(mocks.listDefinitions).toHaveBeenCalledWith({
        enabled_only: true,
        tenant_id: 'tenant-1',
      });
    });

    const [agentSelect] = screen.getAllByRole('combobox');
    fireEvent.mouseDown(agentSelect);
    fireEvent.click(await screen.findByText('Tenant Agent'));
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(mocks.createBinding).toHaveBeenCalledWith(
        expect.objectContaining({ agent_id: 'tenant-agent' }),
        { tenant_id: 'tenant-1' }
      );
    });
  });

  it('disables creation when no tenant-level agents are available', async () => {
    mocks.definitions = [
      makeDefinition({ id: 'project-agent', display_name: 'Project Agent', project_id: 'project-1' }),
    ];

    render(<AgentBindingModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled();

    const [agentSelect] = screen.getAllByRole('combobox');
    fireEvent.mouseDown(agentSelect);

    expect(await screen.findByText('No tenant-level agents available')).toBeInTheDocument();
  });
});
