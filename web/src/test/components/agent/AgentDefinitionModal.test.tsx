import { fireEvent, render, screen, waitFor, within } from '../../utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentDefinitionModal } from '@/components/agent/AgentDefinitionModal';
import {
  buildDelegateConfig,
  buildSessionPolicy,
  buildSpawnPolicy,
  buildToolPolicy,
} from '@/components/agent/agentDefinitionPolicyForm';

import type { AgentDefinition } from '@/types/multiAgent';

const mocks = vi.hoisted(() => ({
  createDefinition: vi.fn(),
  updateDefinition: vi.fn(),
  listTools: vi.fn(),
  listSkills: vi.fn(),
  listMcpServers: vi.fn(),
}));

vi.mock('@/stores/agentDefinitions', () => ({
  useCreateDefinition: () => mocks.createDefinition,
  useUpdateDefinition: () => mocks.updateDefinition,
  useDefinitionSubmitting: () => false,
}));

vi.mock('@/services/agentService', () => ({
  agentService: {
    listTools: mocks.listTools,
  },
}));

vi.mock('@/services/skillService', () => ({
  skillAPI: {
    list: mocks.listSkills,
  },
}));

vi.mock('@/services/mcpService', () => ({
  mcpAPI: {
    list: mocks.listMcpServers,
  },
}));

const makeDefinition = (overrides: Partial<AgentDefinition> = {}): AgentDefinition => ({
  id: 'agent-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  name: 'research_agent',
  display_name: 'Research Agent',
  system_prompt: 'Research carefully.',
  trigger: null,
  persona_files: [],
  model: 'gpt-4',
  temperature: 0.2,
  max_tokens: 4096,
  max_iterations: 12,
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
  max_retries: 1,
  fallback_models: [],
  total_invocations: 0,
  avg_execution_time_ms: 0,
  success_rate: 1,
  created_at: '2026-06-16T00:00:00Z',
  updated_at: null,
  metadata: {},
  ...overrides,
});

async function findComboboxByFormLabel(label: string): Promise<HTMLElement> {
  const labelNode = await screen.findByText(label);
  const formItem = labelNode.closest('.ant-form-item');
  expect(formItem).not.toBeNull();
  return within(formItem as HTMLElement).getByRole('combobox');
}

describe('AgentDefinitionModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.createDefinition.mockResolvedValue(makeDefinition());
    mocks.updateDefinition.mockResolvedValue(makeDefinition({ model: 'inherit' }));
    mocks.listTools.mockResolvedValue({ tools: [] });
    mocks.listSkills.mockResolvedValue({ skills: [] });
    mocks.listMcpServers.mockResolvedValue([]);
  });

  it('sends inherit when an existing explicit model is reset to tenant config', async () => {
    render(
      <AgentDefinitionModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        definition={makeDefinition({ model: 'gpt-4' })}
      />
    );

    const modelSelect = await findComboboxByFormLabel('Model');
    fireEvent.mouseDown(modelSelect);
    fireEvent.click(await screen.findByText('Inherit from Tenant Config'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mocks.updateDefinition).toHaveBeenCalledWith(
        'agent-1',
        expect.objectContaining({ model: 'inherit' })
      );
    });
  });

  it('submits existing fallback models on update', async () => {
    render(
      <AgentDefinitionModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        definition={makeDefinition({ fallback_models: ['claude-3-5-sonnet', 'deepseek-chat'] })}
      />
    );

    expect(await screen.findByText('Claude 3.5 Sonnet')).toBeInTheDocument();
    expect(screen.getByText('Deepseek Chat')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mocks.updateDefinition).toHaveBeenCalledWith(
        'agent-1',
        expect.objectContaining({ fallback_models: ['claude-3-5-sonnet', 'deepseek-chat'] })
      );
    });
  });

  it('submits an empty fallback model list when existing fallback models are cleared', async () => {
    render(
      <AgentDefinitionModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        definition={makeDefinition({ fallback_models: ['claude-3-5-sonnet'] })}
      />
    );

    expect(await screen.findByText('Claude 3.5 Sonnet')).toBeInTheDocument();

    const fallbackSelect = await findComboboxByFormLabel('Fallback Models');
    fireEvent.mouseDown(fallbackSelect);
    fireEvent.keyDown(fallbackSelect, { key: 'Backspace', code: 'Backspace' });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mocks.updateDefinition).toHaveBeenCalledWith(
        'agent-1',
        expect.objectContaining({ fallback_models: [] })
      );
    });
  });

  it('round-trips session and delegate policies on update', async () => {
    render(
      <AgentDefinitionModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        definition={makeDefinition({
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
        })}
      />
    );

    fireEvent.click(await screen.findByText('Sandbox & Isolation'));

    expect(await screen.findByText('Session Policy')).toBeInTheDocument();
    expect(screen.getByText('Global')).toBeInTheDocument();
    expect(screen.getByText('Delegate Config')).toBeInTheDocument();
    expect(screen.getByText('Read/write')).toBeInTheDocument();
    expect(screen.getByText('read_file')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mocks.updateDefinition).toHaveBeenCalledWith(
        'agent-1',
        expect.objectContaining({
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
        })
      );
    });
  });

  it('loads tenant-scoped resources and submits updates with the selected tenant', async () => {
    render(
      <AgentDefinitionModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        definition={makeDefinition()}
        tenantId="tenant-1"
      />
    );

    await waitFor(() => {
      expect(mocks.listSkills).toHaveBeenCalledWith({ limit: 100, tenant_id: 'tenant-1' });
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mocks.updateDefinition).toHaveBeenCalledWith(
        'agent-1',
        expect.objectContaining({ name: 'research_agent' }),
        { tenant_id: 'tenant-1' }
      );
    });
  });

  it('builds null clear payloads when existing policy groups are emptied', () => {
    expect(buildSpawnPolicy({ can_spawn: false }, true)).toBeNull();
    expect(buildToolPolicy({ tool_policy_precedence: 'deny_first' }, true)).toBeNull();
    expect(buildSessionPolicy({}, true)).toBeNull();
    expect(buildDelegateConfig({}, true)).toBeNull();
  });

  it('keeps omitted policy groups out of create payloads', () => {
    expect(buildSpawnPolicy({ can_spawn: false })).toBeUndefined();
    expect(buildToolPolicy({ tool_policy_precedence: 'deny_first' })).toBeUndefined();
    expect(buildSessionPolicy({})).toBeUndefined();
    expect(buildDelegateConfig({})).toBeUndefined();
  });

  it('only offers backend-supported model enum values', async () => {
    render(
      <AgentDefinitionModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        definition={makeDefinition({ model: 'inherit' })}
      />
    );

    const modelSelect = await findComboboxByFormLabel('Model');
    fireEvent.mouseDown(modelSelect);

    expect(await screen.findByText('GPT-4o')).toBeInTheDocument();
    expect(screen.getByText('Claude 3.5 Sonnet')).toBeInTheDocument();
    expect(screen.queryByText('Qwen Turbo')).not.toBeInTheDocument();
    expect(screen.queryByText('GPT-4 Turbo')).not.toBeInTheDocument();
    expect(screen.queryByText('GPT-3.5 Turbo')).not.toBeInTheDocument();
    expect(screen.queryByText('Claude 3 Opus')).not.toBeInTheDocument();
    expect(screen.queryByText('Claude 3 Sonnet')).not.toBeInTheDocument();
  });
});
