import type {
  TenantRuntimeHook,
  TenantRuntimeHookCatalogEntry,
} from './tenantAgentDashboardClient';

const HOOK_FAMILIES = new Set(['observational', 'mutating', 'policy', 'side_effect']);
const EXECUTOR_KINDS = new Set(['builtin', 'script', 'plugin']);

export type EditableRuntimeHooks = Readonly<{
  managed: readonly TenantRuntimeHook[];
  custom: readonly TenantRuntimeHook[];
}>;

export type RuntimeHookSettingsParseResult = Readonly<{
  settings: Readonly<Record<string, unknown>>;
  reasonCode: string | null;
}>;

export function buildEditableRuntimeHooks(
  configured: readonly TenantRuntimeHook[],
  catalog: readonly TenantRuntimeHookCatalogEntry[],
): EditableRuntimeHooks {
  const configuredByKey = new Map(configured.map((hook) => [hookKey(hook), hook]));
  const catalogKeys = new Set(catalog.map((entry) => catalogKey(entry)));
  const managed = catalog.map((entry) => {
    const current = configuredByKey.get(catalogKey(entry));
    return current
      ? normalizeHook({
          ...catalogDefault(entry),
          ...current,
          settings: allowedSettings(current.settings, entry),
        })
      : catalogDefault(entry);
  });
  const custom = configured.filter((hook) => !catalogKeys.has(hookKey(hook))).map(freezeHook);
  return Object.freeze({
    managed: Object.freeze(managed),
    custom: Object.freeze(custom),
  });
}

export function createCustomRuntimeHook(): TenantRuntimeHook {
  return freezeHook({
    hookName: '',
    pluginName: '',
    hookFamily: 'observational',
    executorKind: 'script',
    sourceRef: '',
    entrypoint: 'run',
    enabled: true,
    priority: null,
    settings: {},
  });
}

export function parseRuntimeHookSettings(draft: string): RuntimeHookSettingsParseResult {
  if (!draft.trim()) {
    return Object.freeze({ settings: Object.freeze({}), reasonCode: null });
  }
  try {
    const parsed: unknown = JSON.parse(draft);
    if (!isRecord(parsed)) {
      return Object.freeze({
        settings: Object.freeze({}),
        reasonCode: 'tenant_agent_dashboard_hook_settings_object_required',
      });
    }
    return Object.freeze({
      settings: Object.freeze({ ...parsed }),
      reasonCode: null,
    });
  } catch {
    return Object.freeze({
      settings: Object.freeze({}),
      reasonCode: 'tenant_agent_dashboard_hook_settings_json_invalid',
    });
  }
}

export function validateRuntimeHook(hook: TenantRuntimeHook): readonly string[] {
  const reasons: string[] = [];
  if (!hook.hookName.trim()) {
    reasons.push('tenant_agent_dashboard_hook_name_required');
  }
  if (hook.hookFamily !== null && !HOOK_FAMILIES.has(hook.hookFamily.trim())) {
    reasons.push('tenant_agent_dashboard_hook_family_invalid');
  }
  if (!EXECUTOR_KINDS.has(hook.executorKind.trim())) {
    reasons.push('tenant_agent_dashboard_hook_executor_invalid');
  }
  if (!hook.sourceRef?.trim()) {
    reasons.push('tenant_agent_dashboard_hook_source_required');
  }
  if (hook.executorKind !== 'builtin' && !hook.entrypoint?.trim()) {
    reasons.push('tenant_agent_dashboard_hook_entrypoint_required');
  }
  if (
    hook.priority !== null &&
    (!Number.isSafeInteger(hook.priority) || Math.abs(hook.priority) > 100_000)
  ) {
    reasons.push('tenant_agent_dashboard_hook_priority_invalid');
  }
  return Object.freeze(reasons);
}

export function serializeRuntimeHooks(
  managed: readonly TenantRuntimeHook[],
  custom: readonly TenantRuntimeHook[],
  catalog: readonly TenantRuntimeHookCatalogEntry[],
): readonly TenantRuntimeHook[] {
  const catalogByKey = new Map(catalog.map((entry) => [catalogKey(entry), entry]));
  const changedManaged = managed.filter((hook) => {
    const entry = catalogByKey.get(hookKey(hook));
    return entry === undefined || !hooksEqual(hook, catalogDefault(entry));
  });
  return Object.freeze([...changedManaged, ...custom].map((hook) => normalizeHook(hook)));
}

function catalogDefault(entry: TenantRuntimeHookCatalogEntry): TenantRuntimeHook {
  return freezeHook({
    hookName: entry.hookName,
    pluginName: entry.pluginName.trim(),
    hookFamily: normalizedFamily(entry.hookFamily),
    executorKind: normalizedExecutor(entry.defaultExecutorKind),
    sourceRef: normalizedOptional(entry.defaultSourceRef) || normalizedOptional(entry.pluginName),
    entrypoint: normalizedOptional(entry.defaultEntrypoint),
    enabled: entry.defaultEnabled,
    priority: entry.defaultPriority,
    settings: entry.defaultSettings,
  });
}

function allowedSettings(
  current: Readonly<Record<string, unknown>>,
  entry: TenantRuntimeHookCatalogEntry,
): Readonly<Record<string, unknown>> {
  const properties = isRecord(entry.settingsSchema.properties)
    ? entry.settingsSchema.properties
    : {};
  const allowed = new Set([...Object.keys(entry.defaultSettings), ...Object.keys(properties)]);
  return Object.freeze({
    ...entry.defaultSettings,
    ...Object.fromEntries(Object.entries(current).filter(([key]) => allowed.has(key))),
  });
}

function normalizeHook(hook: TenantRuntimeHook): TenantRuntimeHook {
  return freezeHook({
    hookName: hook.hookName.trim(),
    pluginName: hook.pluginName.trim(),
    hookFamily: normalizedFamily(hook.hookFamily),
    executorKind: normalizedExecutor(hook.executorKind),
    sourceRef: normalizedOptional(hook.sourceRef),
    entrypoint: normalizedOptional(hook.entrypoint),
    enabled: hook.enabled,
    priority: hook.priority,
    settings: hook.settings,
  });
}

function normalizedOptional(value: string | null): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function normalizedFamily(value: string | null): string | null {
  const normalized = normalizedOptional(value);
  return normalized !== null && HOOK_FAMILIES.has(normalized) ? normalized : null;
}

function normalizedExecutor(value: string): string {
  const normalized = value.trim();
  return EXECUTOR_KINDS.has(normalized) ? normalized : 'builtin';
}

function hookKey(hook: Pick<TenantRuntimeHook, 'pluginName' | 'hookName' | 'sourceRef'>): string {
  const namespace = (hook.pluginName || hook.sourceRef || '').trim().toLowerCase();
  return `${namespace}::${hook.hookName.trim().toLowerCase()}`;
}

function catalogKey(entry: TenantRuntimeHookCatalogEntry): string {
  return hookKey({
    pluginName: entry.pluginName,
    hookName: entry.hookName,
    sourceRef: entry.defaultSourceRef,
  });
}

function hooksEqual(left: TenantRuntimeHook, right: TenantRuntimeHook): boolean {
  return (
    JSON.stringify(stableValue(normalizeHook(left))) ===
    JSON.stringify(stableValue(normalizeHook(right)))
  );
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, stableValue(value[key])]),
  );
}

function freezeHook(hook: TenantRuntimeHook): TenantRuntimeHook {
  return Object.freeze({
    ...hook,
    settings: Object.freeze({ ...hook.settings }),
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
