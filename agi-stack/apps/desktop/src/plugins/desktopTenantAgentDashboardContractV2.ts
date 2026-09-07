import { DesktopApiError } from '../api/client';
import type {
  TenantAgentConfig,
  TenantAgentDashboardAction,
  TenantAgentDashboardScope,
  TenantAgentDashboardSnapshot,
  TenantAgentEditableConfig,
  TenantAgentRuntimeInfo,
  TenantAgentRun,
  TenantAgentTrace,
  TenantRuntimeHook,
  TenantRuntimeHookCatalogEntry,
} from '../features/tenant/tenantAgentDashboardClient';

export const TENANT_AGENT_DASHBOARD_SERVICE_VERSION_V2 = '0.1.0';
export const TENANT_AGENT_DASHBOARD_CONTRACT_VERSION_V2 = '3.0.0';
const ACTION_ORDER_V2 = Object.freeze<TenantAgentDashboardAction[]>([
  'view-config',
  'update-config',
  'view-hook-catalog',
  'list-runs',
  'filter-runs',
  'inspect-run',
  'inspect-trace',
  'refresh',
  'retry',
]);
const EDITABLE_CONFIG_KEYS_V2 = new Set([
  'llmModel',
  'llmTemperature',
  'patternLearningEnabled',
  'multiLevelThinkingEnabled',
  'maxWorkPlanSteps',
  'toolTimeoutSeconds',
  'enabledTools',
  'disabledTools',
  'runtimeHooks',
]);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'authority',
  'availability',
  'reasonCode',
  'serviceVersion',
  'contractVersion',
  'allowedActions',
  'authorityRevision',
  'canModify',
  'config',
  'hookCatalog',
  'runtimeInfo',
  'runs',
  'activeRunCount',
]);

export function requireDesktopTenantAgentEditableConfigV2(
  value: unknown,
): TenantAgentEditableConfig {
  const reason = 'desktop_tenant_agent_dashboard_editable_config_invalid';
  if (
    !isRecord(value) ||
    !hasExactKeysV2(value, EDITABLE_CONFIG_KEYS_V2) ||
    !isNonempty(value.llmModel) ||
    !isFiniteNumber(value.llmTemperature) ||
    typeof value.patternLearningEnabled !== 'boolean' ||
    typeof value.multiLevelThinkingEnabled !== 'boolean' ||
    !isPositiveInteger(value.maxWorkPlanSteps) ||
    !isPositiveInteger(value.toolTimeoutSeconds) ||
    !isStringArray(value.enabledTools) ||
    !isStringArray(value.disabledTools) ||
    !Array.isArray(value.runtimeHooks)
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  return Object.freeze({
    llmModel: value.llmModel,
    llmTemperature: value.llmTemperature,
    patternLearningEnabled: value.patternLearningEnabled,
    multiLevelThinkingEnabled: value.multiLevelThinkingEnabled,
    maxWorkPlanSteps: value.maxWorkPlanSteps,
    toolTimeoutSeconds: value.toolTimeoutSeconds,
    enabledTools: Object.freeze([...value.enabledTools]),
    disabledTools: Object.freeze([...value.disabledTools]),
    runtimeHooks: Object.freeze(
      value.runtimeHooks.map((hook) => requireProjectedRuntimeHookV2(hook, reason)),
    ),
  });
}

export function requireDesktopTenantAgentDashboardSnapshotV2(
  value: unknown,
  expectedScope: TenantAgentDashboardScope,
): TenantAgentDashboardSnapshot {
  const reason = 'desktop_tenant_agent_dashboard_service_contract_invalid';
  if (
    !isRecord(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    !isProjectedScopeV2(value.scope, expectedScope) ||
    value.authority !== expectedScope.authority ||
    !isDashboardAvailabilityV2(value.availability) ||
    !isNullableNonemptyV2(value.reasonCode) ||
    !isNonempty(value.serviceVersion) ||
    !isNonempty(value.contractVersion) ||
    !isOrderedActionSubsetV2(value.allowedActions) ||
    !isNullablePositiveIntegerV2(value.authorityRevision) ||
    typeof value.canModify !== 'boolean' ||
    !Array.isArray(value.hookCatalog) ||
    !Array.isArray(value.runs) ||
    !isNonnegativeInteger(value.activeRunCount)
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  const config =
    value.config === null
      ? null
      : requireProjectedAgentConfigV2(value.config, expectedScope, reason);
  const runtimeInfo =
    value.runtimeInfo === null
      ? null
      : requireProjectedRuntimeInfoV2(value.runtimeInfo, reason);
  return Object.freeze({
    scope: Object.freeze({ ...expectedScope }),
    authority: expectedScope.authority,
    availability: value.availability,
    reasonCode: value.reasonCode,
    serviceVersion: value.serviceVersion,
    contractVersion: value.contractVersion,
    allowedActions: Object.freeze([...value.allowedActions]),
    authorityRevision: value.authorityRevision,
    canModify: value.canModify,
    config,
    hookCatalog: Object.freeze(
      value.hookCatalog.map((entry) => requireProjectedHookCatalogEntryV2(entry, reason)),
    ),
    runtimeInfo,
    runs: Object.freeze(value.runs.map((run) => requireProjectedRunV2(run, reason))),
    activeRunCount: value.activeRunCount,
  });
}

export function requireDesktopTenantAgentDashboardConfigV2(
  value: unknown,
  expectedScope: TenantAgentDashboardScope,
): TenantAgentConfig {
  return requireProjectedAgentConfigV2(
    value,
    expectedScope,
    'desktop_tenant_agent_dashboard_service_contract_invalid',
  );
}

export function requireDesktopTenantAgentDashboardTraceV2(
  value: unknown,
  conversationId: string,
  traceId: string,
): TenantAgentTrace {
  const reason = 'desktop_tenant_agent_dashboard_service_contract_invalid';
  if (
    !isRecord(value) ||
    !hasExactKeysV2(value, new Set(['traceId', 'conversationId', 'runs', 'total'])) ||
    value.traceId !== traceId ||
    value.conversationId !== conversationId ||
    !Array.isArray(value.runs) ||
    !isNonnegativeInteger(value.total) ||
    value.total < value.runs.length
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  return Object.freeze({
    traceId,
    conversationId,
    runs: Object.freeze(value.runs.map((run) => requireProjectedRunV2(run, reason))),
    total: value.total,
  });
}

export function tenantAgentDashboardContractErrorV2(reason: string): DesktopApiError {
  return new DesktopApiError(reason, 0, { reason_code: reason });
}

function requireProjectedAgentConfigV2(
  value: unknown,
  expectedScope: TenantAgentDashboardScope,
  reason: string,
): TenantAgentConfig {
  if (
    !isRecord(value) ||
    !hasExactKeysV2(
      value,
      new Set([
        'id',
        'tenantId',
        'configType',
        ...EDITABLE_CONFIG_KEYS_V2,
        'runtimeHookSettingsRedacted',
        'multiAgentEnabled',
        'authorityRevision',
        'createdAt',
        'updatedAt',
      ]),
    ) ||
    !isNonempty(value.id) ||
    value.tenantId !== expectedScope.tenantId ||
    !isNonempty(value.configType) ||
    typeof value.runtimeHookSettingsRedacted !== 'boolean' ||
    typeof value.multiAgentEnabled !== 'boolean' ||
    !isPositiveInteger(value.authorityRevision) ||
    !isNonempty(value.createdAt) ||
    !isNonempty(value.updatedAt)
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  const editable = requireDesktopTenantAgentEditableConfigV2({
    llmModel: value.llmModel,
    llmTemperature: value.llmTemperature,
    patternLearningEnabled: value.patternLearningEnabled,
    multiLevelThinkingEnabled: value.multiLevelThinkingEnabled,
    maxWorkPlanSteps: value.maxWorkPlanSteps,
    toolTimeoutSeconds: value.toolTimeoutSeconds,
    enabledTools: value.enabledTools,
    disabledTools: value.disabledTools,
    runtimeHooks: value.runtimeHooks,
  });
  return Object.freeze({
    ...editable,
    id: value.id,
    tenantId: value.tenantId,
    configType: value.configType,
    runtimeHookSettingsRedacted: value.runtimeHookSettingsRedacted,
    multiAgentEnabled: value.multiAgentEnabled,
    authorityRevision: value.authorityRevision,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  });
}

function requireProjectedRuntimeHookV2(
  value: unknown,
  reason: string,
): TenantRuntimeHook {
  if (
    !isRecord(value) ||
    !hasExactKeysV2(
      value,
      new Set([
        'hookName',
        'pluginName',
        'hookFamily',
        'executorKind',
        'sourceRef',
        'entrypoint',
        'enabled',
        'priority',
        'settings',
      ]),
    ) ||
    !isNonempty(value.hookName) ||
    typeof value.pluginName !== 'string' ||
    !isNullableString(value.hookFamily) ||
    !isNonempty(value.executorKind) ||
    !isNullableString(value.sourceRef) ||
    !isNullableString(value.entrypoint) ||
    typeof value.enabled !== 'boolean' ||
    !isNullableInteger(value.priority) ||
    !isJsonRecordV2(value.settings)
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  return Object.freeze({
    hookName: value.hookName,
    pluginName: value.pluginName,
    hookFamily: value.hookFamily,
    executorKind: value.executorKind,
    sourceRef: value.sourceRef,
    entrypoint: value.entrypoint,
    enabled: value.enabled,
    priority: value.priority,
    settings: cloneJsonRecordV2(value.settings, reason),
  });
}

function requireProjectedHookCatalogEntryV2(
  value: unknown,
  reason: string,
): TenantRuntimeHookCatalogEntry {
  if (
    !isRecord(value) ||
    !hasExactKeysV2(
      value,
      new Set([
        'key',
        'hookName',
        'pluginName',
        'hookFamily',
        'displayName',
        'description',
        'defaultPriority',
        'defaultEnabled',
        'defaultExecutorKind',
        'defaultSourceRef',
        'defaultEntrypoint',
        'defaultSettings',
        'settingsSchema',
      ]),
    ) ||
    !isNonempty(value.key) ||
    !isNonempty(value.hookName) ||
    typeof value.pluginName !== 'string' ||
    value.key !== `${value.pluginName}.${value.hookName}` ||
    !isNullableString(value.hookFamily) ||
    !isNonempty(value.displayName) ||
    typeof value.description !== 'string' ||
    !isNullableInteger(value.defaultPriority) ||
    typeof value.defaultEnabled !== 'boolean' ||
    !isNonempty(value.defaultExecutorKind) ||
    !isNullableString(value.defaultSourceRef) ||
    !isNullableString(value.defaultEntrypoint) ||
    !isJsonRecordV2(value.defaultSettings) ||
    !isJsonRecordV2(value.settingsSchema)
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  return Object.freeze({
    key: value.key,
    hookName: value.hookName,
    pluginName: value.pluginName,
    hookFamily: value.hookFamily,
    displayName: value.displayName,
    description: value.description,
    defaultPriority: value.defaultPriority,
    defaultEnabled: value.defaultEnabled,
    defaultExecutorKind: value.defaultExecutorKind,
    defaultSourceRef: value.defaultSourceRef,
    defaultEntrypoint: value.defaultEntrypoint,
    defaultSettings: cloneJsonRecordV2(value.defaultSettings, reason),
    settingsSchema: cloneJsonRecordV2(value.settingsSchema, reason),
  });
}

function requireProjectedRuntimeInfoV2(
  value: unknown,
  reason: string,
): TenantAgentRuntimeInfo {
  if (
    !isRecord(value) ||
    !hasExactKeysV2(
      value,
      new Set([
        'edition',
        'features',
        'agentRuntimeMode',
        'memoryRuntimeMode',
        'toolProviderMode',
        'failurePersistenceEnabled',
      ]),
    ) ||
    !isNonempty(value.edition) ||
    !Array.isArray(value.features) ||
    !value.features.every(isJsonRecordV2) ||
    !isNonempty(value.agentRuntimeMode) ||
    !isNonempty(value.memoryRuntimeMode) ||
    !isNonempty(value.toolProviderMode) ||
    typeof value.failurePersistenceEnabled !== 'boolean'
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  return Object.freeze({
    edition: value.edition,
    features: Object.freeze(
      value.features.map((feature) => cloneJsonRecordV2(feature, reason)),
    ),
    agentRuntimeMode: value.agentRuntimeMode,
    memoryRuntimeMode: value.memoryRuntimeMode,
    toolProviderMode: value.toolProviderMode,
    failurePersistenceEnabled: value.failurePersistenceEnabled,
  });
}

function requireProjectedRunV2(value: unknown, reason: string): TenantAgentRun {
  if (
    !isRecord(value) ||
    !hasExactKeysV2(
      value,
      new Set([
        'runId',
        'conversationId',
        'subagentName',
        'task',
        'status',
        'createdAt',
        'startedAt',
        'endedAt',
        'summary',
        'error',
        'executionTimeMs',
        'tokensUsed',
        'traceId',
        'parentSpanId',
      ]),
    ) ||
    !isNonempty(value.runId) ||
    !isNonempty(value.conversationId) ||
    !isNonempty(value.subagentName) ||
    typeof value.task !== 'string' ||
    !isNonempty(value.status) ||
    !isNonempty(value.createdAt) ||
    !isNullableString(value.startedAt) ||
    !isNullableString(value.endedAt) ||
    !isNullableString(value.summary) ||
    !isNullableString(value.error) ||
    !isNullableNumber(value.executionTimeMs) ||
    !isNullableNumber(value.tokensUsed) ||
    !isNullableString(value.traceId) ||
    !isNullableString(value.parentSpanId)
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  return Object.freeze({
    runId: value.runId,
    conversationId: value.conversationId,
    subagentName: value.subagentName,
    task: value.task,
    status: value.status,
    createdAt: value.createdAt,
    startedAt: value.startedAt,
    endedAt: value.endedAt,
    summary: value.summary,
    error: value.error,
    executionTimeMs: value.executionTimeMs,
    tokensUsed: value.tokensUsed,
    traceId: value.traceId,
    parentSpanId: value.parentSpanId,
  });
}

function isProjectedScopeV2(
  value: unknown,
  expectedScope: TenantAgentDashboardScope,
): value is TenantAgentDashboardScope {
  return (
    isRecord(value) &&
    hasExactKeysV2(value, new Set(['authority', 'tenantId'])) &&
    value.authority === expectedScope.authority &&
    value.tenantId === expectedScope.tenantId
  );
}

function isOrderedActionSubsetV2(value: unknown): value is TenantAgentDashboardAction[] {
  if (!Array.isArray(value)) return false;
  let lastIndex = -1;
  for (const action of value) {
    const index = ACTION_ORDER_V2.indexOf(action as TenantAgentDashboardAction);
    if (index <= lastIndex) return false;
    lastIndex = index;
  }
  return true;
}

function isDashboardAvailabilityV2(
  value: unknown,
): value is TenantAgentDashboardSnapshot['availability'] {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}

function isNullableNonemptyV2(value: unknown): value is string | null {
  return value === null || isNonempty(value);
}

function isNullablePositiveIntegerV2(value: unknown): value is number | null {
  return value === null || isPositiveInteger(value);
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isJsonRecordV2(value: unknown): value is Record<string, unknown> {
  if (!isRecord(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return false;
  return Object.keys(value).every((key) => key !== '__proto__' && key !== 'constructor');
}

function cloneJsonRecordV2(
  value: Record<string, unknown>,
  reason: string,
): Readonly<Record<string, unknown>> {
  const clone = cloneJsonValueV2(value, reason);
  if (!isRecord(clone)) throw tenantAgentDashboardContractErrorV2(reason);
  return clone;
}

function cloneJsonValueV2(value: unknown, reason: string): unknown {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  ) {
    return value;
  }
  if (Array.isArray(value)) {
    return Object.freeze(value.map((entry) => cloneJsonValueV2(entry, reason)));
  }
  if (isJsonRecordV2(value)) {
    const copy: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value)) {
      copy[key] = cloneJsonValueV2(entry, reason);
    }
    return Object.freeze(copy);
  }
  throw tenantAgentDashboardContractErrorV2(reason);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonempty(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonempty);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 1;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableInteger(value: unknown): value is number | null {
  return value === null || Number.isSafeInteger(value);
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}
