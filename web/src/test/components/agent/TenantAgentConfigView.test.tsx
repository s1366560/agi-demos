import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TenantAgentConfigView } from '../../../components/agent/TenantAgentConfigView';

const { mockGetConfig, mockGetInfo } = vi.hoisted(() => ({
  mockGetConfig: vi.fn(),
  mockGetInfo: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      if (key === 'common.status.enabled') return 'Enabled';
      if (key === 'common.status.disabled') return 'Disabled';
      if (key === 'tenant.agentConfigView.summary.runtimeModes.auto') return 'Auto';
      if (key === 'tenant.agentConfigView.summary.memoryModes.plugin') return 'Plugin';
      if (key === 'tenant.agentConfigView.summary.agentRuntime') return 'Agent runtime';
      if (key === 'tenant.agentConfigView.summary.memoryRuntime') return 'Memory runtime';
      if (key === 'tenant.agentConfigView.summary.memoryTools') return 'Memory tools';
      if (key === 'tenant.agentConfigView.summary.failurePersistence') {
        return 'Failure persistence';
      }
      if (values && typeof values.count === 'number') {
        return `${key}:${values.count}`;
      }
      return key;
    },
  }),
}));

vi.mock('@business/agent/ui/web/services/agentConfigService', () => ({
  agentConfigService: {
    getConfig: mockGetConfig,
  },
  TenantAgentConfigError: class TenantAgentConfigError extends Error {},
}));

vi.mock('../../../services/systemService', () => ({
  systemService: {
    getInfo: mockGetInfo,
  },
}));

describe('TenantAgentConfigView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetConfig.mockResolvedValue({
      id: 'cfg-1',
      tenant_id: 'tenant-1',
      config_type: 'custom',
      llm_model: 'openai/gpt-5.4',
      llm_temperature: 0.2,
      pattern_learning_enabled: true,
      multi_level_thinking_enabled: true,
      max_work_plan_steps: 8,
      tool_timeout_seconds: 45,
      enabled_tools: [],
      disabled_tools: [],
      runtime_hooks: [],
      multi_agent_enabled: true,
      created_at: '2026-04-22T00:00:00Z',
      updated_at: '2026-04-22T00:00:00Z',
    });
    mockGetInfo.mockResolvedValue({
      edition: 'community',
      features: [],
      agent_runtime: { mode: 'auto' },
      memory_runtime: {
        mode: 'plugin',
        tool_provider_mode: 'plugin',
        failure_persistence_enabled: true,
      },
    });
  });

  it('renders runtime rollout summary from system info', async () => {
    render(<TenantAgentConfigView tenantId="tenant-1" />);

    await waitFor(() => {
      expect(mockGetConfig).toHaveBeenCalledWith('tenant-1');
    });

    expect(await screen.findByText('Agent runtime')).toBeInTheDocument();
    expect(screen.getByText('Memory runtime')).toBeInTheDocument();
    expect(screen.getByText('Memory tools')).toBeInTheDocument();
    expect(screen.getByText('Failure persistence')).toBeInTheDocument();
    expect(screen.getByText('Auto')).toBeInTheDocument();
    expect(screen.getAllByText('Plugin').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Enabled').length).toBeGreaterThan(0);
  });
});
