import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentBindings } from '../../../pages/tenant/AgentBindings';
import { bindingsService } from '../../../services/agent/bindingsService';
import { definitionsService } from '../../../services/agent/definitionsService';
import { useAgentBindingStore } from '../../../stores/agentBindings';
import { useAgentDefinitionStore } from '../../../stores/agentDefinitions';
import { useAuthStore } from '../../../stores/auth';
import { useTenantStore } from '../../../stores/tenant';

import type { AgentBinding, AgentDefinition } from '../../../types/multiAgent';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallbackOrOptions?: string | { defaultValue?: string; count?: number }) => {
      if (typeof fallbackOrOptions === 'string') {
        return fallbackOrOptions;
      }
      const template = fallbackOrOptions?.defaultValue ?? key;
      return typeof fallbackOrOptions?.count === 'number'
        ? template.replace('{{count}}', String(fallbackOrOptions.count))
        : template;
    },
  }),
}));

vi.mock('../../../services/agent/bindingsService', () => ({
  bindingsService: {
    list: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    setEnabled: vi.fn(),
    test: vi.fn(),
  },
}));

vi.mock('../../../services/agent/definitionsService', () => ({
  definitionsService: {
    list: vi.fn(),
  },
}));

vi.mock('../../../components/agent/AgentBindingModal', () => ({
  AgentBindingModal: ({
    isOpen,
    tenantId,
  }: {
    isOpen: boolean;
    tenantId?: string | null;
  }) =>
    isOpen ? <div data-testid="agent-binding-modal" data-tenant-id={tenantId ?? ''} /> : null,
}));

const makeBinding = (): AgentBinding => ({
  id: 'binding-1',
  tenant_id: 'tenant-route-new',
  agent_id: 'agent-1',
  channel_type: 'web',
  channel_id: 'channel-1',
  account_id: null,
  peer_id: null,
  group_id: 'default',
  priority: 10,
  enabled: true,
  created_at: '2026-06-03T05:00:00Z',
  specificity_score: 4,
});

const makeDefinition = (): AgentDefinition =>
  ({
    id: 'agent-1',
    tenant_id: 'tenant-route-new',
    project_id: null,
    name: 'research_agent',
    display_name: 'Research Agent',
    system_prompt: null,
    trigger: null,
    persona_files: [],
    model: null,
    temperature: null,
    max_tokens: null,
    max_iterations: 12,
    allowed_tools: null,
    allowed_skills: null,
    allowed_mcp_servers: null,
    bindings: [],
    workspace_dir: null,
    workspace_config: null,
    can_spawn: false,
    max_spawn_depth: 0,
    agent_to_agent_enabled: false,
    agent_to_agent_allowlist: [],
    spawn_policy: null,
    tool_policy: null,
    session_policy: null,
    delegate_config: null,
    discoverable: true,
    source: 'database',
    enabled: true,
    max_retries: 3,
    fallback_models: [],
    total_invocations: 0,
    avg_execution_time_ms: null,
    success_rate: null,
    created_at: '2026-06-03T05:00:00Z',
    updated_at: '2026-06-03T05:00:00Z',
    metadata: {},
  }) as AgentDefinition;

describe('AgentBindings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentBindingStore.getState().reset();
    useAgentDefinitionStore.getState().reset();
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
    useTenantStore.setState({
      currentTenant: {
        id: 'tenant-store-old',
        name: 'Old Tenant',
        owner_id: 'admin-1',
        plan: 'enterprise',
        max_projects: 100,
        max_users: 100,
        max_storage: 1024,
        created_at: '2026-06-03T05:00:00Z',
      },
    });
    vi.mocked(bindingsService.list).mockResolvedValue([makeBinding()]);
    vi.mocked(definitionsService.list).mockResolvedValue([makeDefinition()]);
  });

  it('uses the route tenant id when the tenant store is still stale', async () => {
    render(
      <MemoryRouter initialEntries={['/tenant/tenant-route-new/agent-bindings']}>
        <Routes>
          <Route path="/tenant/:tenantId/agent-bindings" element={<AgentBindings />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(bindingsService.list).toHaveBeenCalledWith({ tenant_id: 'tenant-route-new' });
    });
    expect(definitionsService.list).toHaveBeenCalledWith({ tenant_id: 'tenant-route-new' });
    expect(await screen.findByText('Research Agent')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Create Binding' }));

    expect(screen.getByTestId('agent-binding-modal')).toHaveAttribute(
      'data-tenant-id',
      'tenant-route-new'
    );
  });
});
