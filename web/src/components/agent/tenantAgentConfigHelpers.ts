import type { HookCatalogEntry, RuntimeHookConfig, TenantAgentConfig } from '@/types/agent';

export function parseToolList(value: string | undefined): string[] {
  if (!value || !value.trim()) {
    return [];
  }

  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function formatToolList(tools: string[]): string {
  return tools.join(', ');
}

export function hookKey(hook: Pick<RuntimeHookConfig, 'plugin_name' | 'hook_name'>): string {
  return `${hook.plugin_name.trim().toLowerCase()}::${hook.hook_name.trim().toLowerCase()}`;
}

function normalizeValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(normalizeValue);
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .map((key) => [key, normalizeValue((value as Record<string, unknown>)[key])])
    );
  }

  return value;
}

function areSettingsEqual(
  left: Record<string, unknown>,
  right: Record<string, unknown>
): boolean {
  return JSON.stringify(normalizeValue(left)) === JSON.stringify(normalizeValue(right));
}

export function buildRuntimeHooks(
  config: TenantAgentConfig,
  hookCatalog: HookCatalogEntry[]
): RuntimeHookConfig[] {
  const existing = new Map(config.runtime_hooks.map((hook) => [hookKey(hook), hook]));

  return hookCatalog.map((entry) => {
    const current = existing.get(hookKey(entry));
    const allowedSettings = new Set([
      ...Object.keys(entry.default_settings),
      ...Object.keys(getHookSchemaProperties(entry)),
    ]);
    const filteredCurrentSettings = Object.fromEntries(
      Object.entries(current?.settings ?? {}).filter(([key]) => allowedSettings.has(key))
    );
    return {
      plugin_name: entry.plugin_name,
      hook_name: entry.hook_name,
      enabled: current?.enabled ?? entry.default_enabled,
      priority: current ? (current.priority ?? null) : entry.default_priority,
      settings: {
        ...entry.default_settings,
        ...filteredCurrentSettings,
      },
    };
  });
}

export interface HookSettingSchemaProperty {
  title?: string;
  description?: string;
  type?: string;
}

export function getHookSchemaProperties(
  hookCatalogEntry: HookCatalogEntry
): Record<string, HookSettingSchemaProperty> {
  const rawProperties = hookCatalogEntry.settings_schema['properties'];
  if (typeof rawProperties !== 'object' || rawProperties === null) {
    return {};
  }

  return rawProperties as Record<string, HookSettingSchemaProperty>;
}

export function isHookCustomized(
  hook: RuntimeHookConfig,
  entry: HookCatalogEntry
): boolean {
  const effectivePriority = hook.priority ?? entry.default_priority;
  return (
    hook.enabled !== entry.default_enabled ||
    effectivePriority !== entry.default_priority ||
    !areSettingsEqual(hook.settings, entry.default_settings)
  );
}

export function serializeRuntimeHooks(
  runtimeHooks: RuntimeHookConfig[],
  hookCatalog: HookCatalogEntry[]
): RuntimeHookConfig[] {
  const catalogByKey = new Map(hookCatalog.map((entry) => [hookKey(entry), entry]));

  return runtimeHooks
    .filter((hook) => {
      const entry = catalogByKey.get(hookKey(hook));
      if (!entry) {
        return true;
      }

      return isHookCustomized(hook, entry);
    })
    .map((hook) => ({
      plugin_name: hook.plugin_name,
      hook_name: hook.hook_name,
      enabled: hook.enabled,
      priority: hook.priority ?? null,
      settings: hook.settings,
    }));
}
