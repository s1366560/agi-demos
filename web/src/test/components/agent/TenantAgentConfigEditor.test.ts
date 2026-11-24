import { describe, expect, it } from 'vitest';

import {
  buildRuntimeHooks,
  createEmptyCustomRuntimeHook,
  hookKey,
  serializeCustomRuntimeHooks,
  serializeRuntimeHooks,
} from '@business/agent/ui/web/configuration/tenantAgentConfigHelpers';

import type { HookCatalogEntry, TenantAgentConfig } from '../../../types/agent';

const hookCatalog: HookCatalogEntry[] = [
  {
    plugin_name: 'builtin_sisyphus',
    hook_name: 'start-work',
    display_name: 'Start work',
    description: 'Reminds the runtime to start with concrete execution.',
    hook_family: 'observational',
    default_priority: 100,
    default_enabled: true,
    default_executor_kind: 'builtin',
    default_source_ref: 'builtin_sisyphus',
    default_entrypoint: null,
    default_settings: {
      reminder: 'Start with the next concrete action.',
      sticky: true,
    },
    settings_schema: {
      type: 'object',
      properties: {
        reminder: { type: 'string' },
        sticky: { type: 'boolean' },
      },
    },
  },
];

const baseConfig: TenantAgentConfig = {
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
  created_at: '2026-04-08T00:00:00Z',
  updated_at: '2026-04-08T00:00:00Z',
};

describe('TenantAgentConfigEditor helpers', () => {
  it('normalizes hook keys the same way as the backend', () => {
    expect(
      hookKey({
        plugin_name: ' Builtin_Sisyphus ',
        hook_name: ' Start-Work ',
        executor_kind: ' builtin ',
        source_ref: ' builtin_sisyphus ',
        entrypoint: ' ',
      })
    ).toBe('builtin_sisyphus::start-work');
  });

  it('merges catalog defaults into editable runtime hooks', () => {
    const config: TenantAgentConfig = {
      ...baseConfig,
      runtime_hooks: [
        {
          plugin_name: 'builtin_sisyphus',
          hook_name: 'start-work',
          hook_family: 'observational',
          executor_kind: 'builtin',
          source_ref: 'builtin_sisyphus',
          entrypoint: null,
          enabled: false,
          priority: 120,
          settings: {
            reminder: 'Use the todo list before replying.',
          },
        },
      ],
    };

    expect(buildRuntimeHooks(config, hookCatalog)).toEqual([
      {
        plugin_name: 'builtin_sisyphus',
        hook_name: 'start-work',
        hook_family: 'observational',
        executor_kind: 'builtin',
        source_ref: 'builtin_sisyphus',
        entrypoint: null,
        enabled: false,
        priority: 120,
        settings: {
          reminder: 'Use the todo list before replying.',
          sticky: true,
        },
      },
    ]);
  });

  it('only serializes hook overrides that diverge from catalog defaults', () => {
    const runtimeHooks = buildRuntimeHooks(baseConfig, hookCatalog);

    expect(serializeRuntimeHooks(runtimeHooks, hookCatalog)).toEqual([]);

    runtimeHooks[0] = {
      ...runtimeHooks[0],
      settings: {
        ...runtimeHooks[0].settings,
        reminder: 'Use the todo list before replying.',
      },
    };

    expect(serializeRuntimeHooks(runtimeHooks, hookCatalog)).toEqual([
      {
        plugin_name: 'builtin_sisyphus',
        hook_name: 'start-work',
        hook_family: 'observational',
        executor_kind: 'builtin',
        source_ref: 'builtin_sisyphus',
        entrypoint: null,
        enabled: true,
        priority: 100,
        settings: {
          reminder: 'Use the todo list before replying.',
          sticky: true,
        },
      },
    ]);
  });

  it('preserves null priority when an inherited hook has other overrides', () => {
    const config: TenantAgentConfig = {
      ...baseConfig,
      runtime_hooks: [
        {
          plugin_name: 'builtin_sisyphus',
          hook_name: 'start-work',
          hook_family: 'observational',
          executor_kind: 'builtin',
          source_ref: 'builtin_sisyphus',
          entrypoint: null,
          enabled: true,
          priority: null,
          settings: {
            reminder: 'Use the todo list before replying.',
          },
        },
      ],
    };

    const runtimeHooks = buildRuntimeHooks(config, hookCatalog);

    expect(runtimeHooks[0]?.priority).toBeNull();
    expect(serializeRuntimeHooks(runtimeHooks, hookCatalog)).toEqual([
      {
        plugin_name: 'builtin_sisyphus',
        hook_name: 'start-work',
        hook_family: 'observational',
        executor_kind: 'builtin',
        source_ref: 'builtin_sisyphus',
        entrypoint: null,
        enabled: true,
        priority: null,
        settings: {
          reminder: 'Use the todo list before replying.',
          sticky: true,
        },
      },
    ]);
  });

  it('drops persisted settings that are no longer supported by the catalog schema', () => {
    const config: TenantAgentConfig = {
      ...baseConfig,
      runtime_hooks: [
        {
          plugin_name: 'builtin_sisyphus',
          hook_name: 'start-work',
          hook_family: 'observational',
          executor_kind: 'builtin',
          source_ref: 'builtin_sisyphus',
          entrypoint: null,
          enabled: true,
          priority: 100,
          settings: {
            reminder: 'Use the todo list before replying.',
            sticky: true,
            legacy_setting: 'remove-me',
          },
        },
      ],
    };

    expect(buildRuntimeHooks(config, hookCatalog)).toEqual([
      {
        plugin_name: 'builtin_sisyphus',
        hook_name: 'start-work',
        hook_family: 'observational',
        executor_kind: 'builtin',
        source_ref: 'builtin_sisyphus',
        entrypoint: null,
        enabled: true,
        priority: 100,
        settings: {
          reminder: 'Use the todo list before replying.',
          sticky: true,
        },
      },
    ]);
  });

  it('serializes custom runtime hooks with explicit executor identity fields', () => {
    const customHook = {
      ...createEmptyCustomRuntimeHook(),
      hook_name: 'before_tool_execution',
      hook_family: 'mutating',
      executor_kind: 'script',
      source_ref: 'plugins/demo_hooks.py',
      entrypoint: 'annotate_tool',
      settings: {
        tag: 'demo',
      },
    };

    expect(serializeCustomRuntimeHooks([customHook])).toEqual([
      {
        hook_name: 'before_tool_execution',
        hook_family: 'mutating',
        executor_kind: 'script',
        source_ref: 'plugins/demo_hooks.py',
        entrypoint: 'annotate_tool',
        enabled: true,
        priority: null,
        settings: {
          tag: 'demo',
        },
      },
    ]);
  });

  it('preserves side_effect hook family for custom runtime hooks', () => {
    const customHook = {
      ...createEmptyCustomRuntimeHook(),
      hook_name: 'after_subagent_complete',
      hook_family: 'side_effect' as const,
      executor_kind: 'plugin' as const,
      source_ref: 'src/infrastructure/agent/plugins/demo_plugin_hook.py',
      entrypoint: 'emit_audit_event',
    };

    expect(serializeCustomRuntimeHooks([customHook])[0]?.hook_family).toBe('side_effect');
  });
});
