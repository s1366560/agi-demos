import type {
  HookCatalogEntry,
  HookExecutorKind,
  HookFamily,
  RuntimeHookConfig,
  TenantAgentConfig,
} from '@/types/agent';

const HOOK_FAMILIES = new Set<HookFamily>(['observational', 'mutating', 'policy', 'side_effect']);
const EXECUTOR_KINDS = new Set<HookExecutorKind>(['builtin', 'script', 'plugin']);

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

export function hookKey(
  hook: Pick<
    RuntimeHookConfig,
    'plugin_name' | 'hook_name' | 'executor_kind' | 'source_ref' | 'entrypoint'
  >
): string {
  const namespace =
    hook.plugin_name?.trim().toLowerCase() ?? hook.source_ref?.trim().toLowerCase() ?? '';
  return `${namespace}::${hook.hook_name.trim().toLowerCase()}`;
}

function normalizeOptionalText(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function normalizeOptionalTextOrNull(value: string | null | undefined): string | null {
  return normalizeOptionalText(value) ?? null;
}

function normalizeHookFamily(
  value: RuntimeHookConfig['hook_family']
): RuntimeHookConfig['hook_family'] {
  const trimmed = normalizeOptionalText(value);
  return trimmed && HOOK_FAMILIES.has(trimmed as HookFamily) ? (trimmed as HookFamily) : null;
}

function normalizeExecutorKind(
  value: RuntimeHookConfig['executor_kind']
): RuntimeHookConfig['executor_kind'] {
  const trimmed = normalizeOptionalText(value);
  return trimmed && EXECUTOR_KINDS.has(trimmed as HookExecutorKind)
    ? (trimmed as HookExecutorKind)
    : null;
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

function areSettingsEqual(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
  return JSON.stringify(normalizeValue(left)) === JSON.stringify(normalizeValue(right));
}

function getCatalogDefaultRuntimeHook(entry: HookCatalogEntry): RuntimeHookConfig {
  return {
    plugin_name: normalizeOptionalText(entry.plugin_name),
    hook_name: entry.hook_name,
    hook_family: normalizeHookFamily(entry.hook_family),
    executor_kind: normalizeExecutorKind(entry.default_executor_kind) ?? 'builtin',
    source_ref:
      normalizeOptionalTextOrNull(entry.default_source_ref) ??
      normalizeOptionalTextOrNull(entry.plugin_name),
    entrypoint: normalizeOptionalTextOrNull(entry.default_entrypoint),
    enabled: entry.default_enabled,
    priority: entry.default_priority,
    settings: { ...entry.default_settings },
  };
}

export function normalizeRuntimeHookForSave(hook: RuntimeHookConfig): RuntimeHookConfig {
  return {
    plugin_name: normalizeOptionalText(hook.plugin_name),
    hook_name: hook.hook_name.trim(),
    hook_family: normalizeHookFamily(hook.hook_family),
    executor_kind: normalizeExecutorKind(hook.executor_kind),
    source_ref: normalizeOptionalTextOrNull(hook.source_ref),
    entrypoint: normalizeOptionalTextOrNull(hook.entrypoint),
    enabled: hook.enabled,
    priority: hook.priority ?? null,
    settings: hook.settings,
  };
}

export function serializeCustomRuntimeHooks(
  runtimeHooks: RuntimeHookConfig[]
): RuntimeHookConfig[] {
  return runtimeHooks.map(normalizeRuntimeHookForSave);
}

export function createEmptyCustomRuntimeHook(): RuntimeHookConfig {
  return {
    hook_name: '',
    hook_family: 'observational',
    executor_kind: 'script',
    source_ref: '',
    entrypoint: 'run',
    enabled: true,
    priority: null,
    settings: {},
  };
}

export function buildRuntimeHooks(
  config: TenantAgentConfig,
  hookCatalog: HookCatalogEntry[]
): RuntimeHookConfig[] {
  const existing = new Map(config.runtime_hooks.map((hook) => [hookKey(hook), hook]));

  return hookCatalog.map((entry) => {
    const current = existing.get(hookKey(entry));
    const catalogDefault = getCatalogDefaultRuntimeHook(entry);
    const allowedSettings = new Set([
      ...Object.keys(entry.default_settings),
      ...Object.keys(getHookSchemaProperties(entry)),
    ]);
    const filteredCurrentSettings = Object.fromEntries(
      Object.entries(current?.settings ?? {}).filter(([key]) => allowedSettings.has(key))
    );
    return {
      ...catalogDefault,
      plugin_name: normalizeOptionalText(current?.plugin_name) ?? catalogDefault.plugin_name,
      hook_name: current?.hook_name ?? catalogDefault.hook_name,
      hook_family: normalizeHookFamily(current?.hook_family) ?? catalogDefault.hook_family ?? null,
      executor_kind: normalizeExecutorKind(current?.executor_kind) ?? catalogDefault.executor_kind,
      source_ref:
        normalizeOptionalTextOrNull(current?.source_ref) ?? catalogDefault.source_ref ?? null,
      entrypoint:
        normalizeOptionalTextOrNull(current?.entrypoint) ?? catalogDefault.entrypoint ?? null,
      enabled: current?.enabled ?? catalogDefault.enabled,
      priority: current ? (current.priority ?? null) : catalogDefault.priority,
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

export function isHookCustomized(hook: RuntimeHookConfig, entry: HookCatalogEntry): boolean {
  const catalogDefault = getCatalogDefaultRuntimeHook(entry);
  const effectivePriority = hook.priority ?? catalogDefault.priority ?? entry.default_priority;
  return (
    hook.enabled !== catalogDefault.enabled ||
    effectivePriority !== catalogDefault.priority ||
    normalizeOptionalTextOrNull(hook.plugin_name) !==
      normalizeOptionalTextOrNull(entry.plugin_name) ||
    normalizeHookFamily(hook.hook_family) !== catalogDefault.hook_family ||
    (normalizeExecutorKind(hook.executor_kind) ?? 'builtin') !== catalogDefault.executor_kind ||
    normalizeOptionalTextOrNull(hook.source_ref) !== catalogDefault.source_ref ||
    normalizeOptionalTextOrNull(hook.entrypoint) !== catalogDefault.entrypoint ||
    !areSettingsEqual(hook.settings, catalogDefault.settings)
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
      ...normalizeRuntimeHookForSave(hook),
    }));
}
