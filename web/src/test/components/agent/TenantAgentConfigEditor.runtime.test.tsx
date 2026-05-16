import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TenantAgentConfigEditor } from '../../../components/agent/TenantAgentConfigEditor';

const { mockGetConfig, mockGetHookCatalog, mockGetInfo } = vi.hoisted(() => ({
  mockGetConfig: vi.fn(),
  mockGetHookCatalog: vi.fn(),
  mockGetInfo: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const labels: Record<string, string> = {
        'tenant.agentConfigEditor.eyebrow': 'Tenant runtime policy',
        'tenant.agentConfigEditor.title': 'Edit configuration',
        'tenant.agentConfigEditor.description': 'Edit tenant runtime policy.',
        'tenant.agentConfigEditor.runtimeStatus.title': 'Runtime rollout status',
        'tenant.agentConfigEditor.runtimeStatus.memoryDisabled':
          'Memory runtime is globally disabled.',
        'tenant.agentConfigEditor.runtimeStatus.memoryToolsDisabled':
          'Memory tools are globally disabled.',
        'tenant.agentConfigEditor.runtimeHooks.catalogUnavailableDescription':
          'Hook catalog unavailable.',
        'tenant.agentConfigEditor.sections.modelReasoning.title': 'Model & reasoning',
        'tenant.agentConfigEditor.sections.modelReasoning.description': 'desc',
        'tenant.agentConfigEditor.sections.modelReasoning.modelIdentifier': 'Model identifier',
        'tenant.agentConfigEditor.sections.modelReasoning.modelIdentifierHint': 'hint',
        'tenant.agentConfigEditor.sections.modelReasoning.modelIdentifierRequired': 'required',
        'tenant.agentConfigEditor.sections.modelReasoning.modelIdentifierPlaceholder':
          'openai/gpt-5.4',
        'tenant.agentConfigEditor.sections.modelReasoning.temperature': 'Temperature',
        'tenant.agentConfigEditor.sections.modelReasoning.temperatureHint': 'hint',
        'tenant.agentConfigEditor.sections.modelReasoning.temperatureRequired': 'required',
        'tenant.agentConfigEditor.sections.modelReasoning.temperatureRange': 'range',
        'tenant.agentConfigEditor.sections.modelReasoning.patternLearning': 'Pattern learning',
        'tenant.agentConfigEditor.sections.modelReasoning.patternLearningDescription': 'desc',
        'tenant.agentConfigEditor.sections.modelReasoning.patternLearningToggle':
          'Toggle pattern learning',
        'tenant.agentConfigEditor.sections.modelReasoning.multiLevelThinking':
          'Multi-level thinking',
        'tenant.agentConfigEditor.sections.modelReasoning.multiLevelThinkingDescription': 'desc',
        'tenant.agentConfigEditor.sections.modelReasoning.multiLevelThinkingToggle':
          'Toggle multi-level thinking',
        'tenant.agentConfigEditor.sections.executionGuardrails.title': 'Execution guardrails',
        'tenant.agentConfigEditor.sections.executionGuardrails.description': 'desc',
        'tenant.agentConfigEditor.sections.executionGuardrails.maxWorkPlanSteps':
          'Max work plan steps',
        'tenant.agentConfigEditor.sections.executionGuardrails.maxWorkPlanStepsHint': 'hint',
        'tenant.agentConfigEditor.sections.executionGuardrails.maxWorkPlanStepsRequired':
          'required',
        'tenant.agentConfigEditor.sections.executionGuardrails.minValue': 'min',
        'tenant.agentConfigEditor.sections.executionGuardrails.toolTimeout':
          'Tool timeout (seconds)',
        'tenant.agentConfigEditor.sections.executionGuardrails.toolTimeoutHint': 'hint',
        'tenant.agentConfigEditor.sections.executionGuardrails.toolTimeoutRequired': 'required',
        'tenant.agentConfigEditor.sections.executionGuardrails.toolTimeoutMin': 'min',
        'tenant.agentConfigEditor.sections.executionGuardrails.multiAgentRouting':
          'Multi-agent routing',
        'tenant.agentConfigEditor.sections.executionGuardrails.multiAgentRoutingDescription':
          'controlled globally',
        'tenant.agentConfigEditor.sections.toolPolicy.title': 'Tool policy',
        'tenant.agentConfigEditor.sections.toolPolicy.description': 'desc',
        'tenant.agentConfigEditor.sections.toolPolicy.enabledTools': 'Enabled tools',
        'tenant.agentConfigEditor.sections.toolPolicy.enabledToolsHint': 'hint',
        'tenant.agentConfigEditor.sections.toolPolicy.disabledTools': 'Disabled tools',
        'tenant.agentConfigEditor.sections.toolPolicy.disabledToolsHint': 'hint',
        'tenant.agentConfigEditor.sections.toolPolicy.toolPlaceholder': 'tool_name',
        'tenant.agentConfigEditor.runtimeHooks.title': 'Runtime hooks',
        'tenant.agentConfigEditor.runtimeHooks.description': 'desc',
        'tenant.agentConfigEditor.runtimeHooks.empty': 'No runtime hooks',
        'tenant.agentConfigEditor.actions.save': 'Save configuration',
        'tenant.agentConfigEditor.actions.close': 'Close',
      };
      return labels[key] ?? key;
    },
  }),
}));

vi.mock('../../../services/agentConfigService', () => ({
  agentConfigService: {
    getConfig: mockGetConfig,
    getHookCatalog: mockGetHookCatalog,
    updateConfig: vi.fn(),
  },
  TenantAgentConfigError: class TenantAgentConfigError extends Error {},
}));

vi.mock('../../../services/systemService', () => ({
  systemService: {
    getInfo: mockGetInfo,
  },
}));

describe('TenantAgentConfigEditor runtime rollout', () => {
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
    mockGetHookCatalog.mockResolvedValue([]);
    mockGetInfo.mockResolvedValue({
      edition: 'community',
      features: [],
      agent_runtime: { mode: 'auto' },
      memory_runtime: {
        mode: 'disabled',
        tool_provider_mode: 'plugin',
        failure_persistence_enabled: true,
      },
    });
  });

  it('shows runtime rollout warning when memory runtime is globally disabled', async () => {
    render(<TenantAgentConfigEditor tenantId="tenant-1" open onClose={vi.fn()} />);

    await waitFor(() => {
      expect(mockGetConfig).toHaveBeenCalledWith('tenant-1');
    });

    expect(await screen.findByText('Runtime rollout status')).toBeInTheDocument();
    expect(screen.getByText('Memory runtime is globally disabled.')).toBeInTheDocument();
  });

  it('shows runtime rollout warning when memory tools are globally disabled', async () => {
    mockGetInfo.mockResolvedValue({
      edition: 'community',
      features: [],
      agent_runtime: { mode: 'auto' },
      memory_runtime: {
        mode: 'plugin',
        tool_provider_mode: 'disabled',
        failure_persistence_enabled: true,
      },
    });

    render(<TenantAgentConfigEditor tenantId="tenant-1" open onClose={vi.fn()} />);

    await waitFor(() => {
      expect(mockGetConfig).toHaveBeenCalledWith('tenant-1');
    });

    expect(await screen.findByText('Runtime rollout status')).toBeInTheDocument();
    expect(screen.getByText('Memory tools are globally disabled.')).toBeInTheDocument();
  });
});
