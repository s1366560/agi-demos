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

import {
  TENANT_AGENT_DASHBOARD_CONTRACT_VERSION_V2,
  TENANT_AGENT_DASHBOARD_SERVICE_VERSION_V2,
  tenantAgentDashboardContractErrorV2,
} from './desktopTenantAgentDashboardContractV2';

const READ_ACTIONS_V2 = Object.freeze<TenantAgentDashboardAction[]>([
  'view-config',
  'list-runs',
  'filter-runs',
  'inspect-run',
  'inspect-trace',
  'refresh',
  'retry',
]);

export function projectDesktopTenantAgentDashboardPermissionV2(raw: unknown): boolean {
  return readCanModifyV2(raw);
}

export function projectDesktopTenantAgentDashboardSnapshotV2(
  scope: TenantAgentDashboardScope,
  rawConfig: unknown,
  rawRuns: unknown,
  rawActive: unknown,
  canModify: boolean,
  rawHookCatalog: unknown | null,
  rawRuntimeInfo: unknown | null,
): TenantAgentDashboardSnapshot {
  const hookCatalog = canModify
    ? readHookCatalogV2(rawHookCatalog)
    : Object.freeze<TenantRuntimeHookCatalogEntry[]>([]);
  const runtimeInfo = rawRuntimeInfo === null ? null : readRuntimeInfoV2(rawRuntimeInfo);
  return projectSnapshotV2(
    Object.freeze({ ...scope }),
    rawConfig,
    rawRuns,
    rawActive,
    canModify,
    hookCatalog,
    runtimeInfo,
  );
}

export function projectDesktopTenantAgentDashboardConfigV2(
  raw: unknown,
  scope: TenantAgentDashboardScope,
): TenantAgentConfig {
  return readConfigV2(raw, scope);
}

export function projectDesktopTenantAgentDashboardTraceV2(
  raw: unknown,
  conversationId: string,
  traceId: string,
): TenantAgentTrace {
  return readTraceV2(raw, conversationId, traceId);
}

export function desktopTenantAgentDashboardUpdateBodyV2(
  input: TenantAgentEditableConfig,
): Readonly<Record<string, unknown>> {
  return {
    llm_model: input.llmModel,
    llm_temperature: input.llmTemperature,
    pattern_learning_enabled: input.patternLearningEnabled,
    multi_level_thinking_enabled: input.multiLevelThinkingEnabled,
    max_work_plan_steps: input.maxWorkPlanSteps,
    tool_timeout_seconds: input.toolTimeoutSeconds,
    enabled_tools: [...input.enabledTools],
    disabled_tools: [...input.disabledTools],
    runtime_hooks: input.runtimeHooks.map((hook) => ({
      hook_name: hook.hookName,
      plugin_name: hook.pluginName,
      hook_family: hook.hookFamily,
      executor_kind: hook.executorKind,
      source_ref: hook.sourceRef,
      entrypoint: hook.entrypoint,
      enabled: hook.enabled,
      priority: hook.priority,
      settings: { ...hook.settings },
    })),
  };
}

export function localDesktopTenantAgentDashboardUnavailableV2(
  scope: TenantAgentDashboardScope,
): TenantAgentDashboardSnapshot {
  return Object.freeze({
    scope: Object.freeze({ ...scope }),
    authority: 'local',
    availability: 'unavailable',
    reasonCode: 'local_agent_dashboard_authority_unavailable',
    serviceVersion: TENANT_AGENT_DASHBOARD_SERVICE_VERSION_V2,
    contractVersion: TENANT_AGENT_DASHBOARD_CONTRACT_VERSION_V2,
    allowedActions: Object.freeze([]),
    authorityRevision: null,
    canModify: false,
    config: null,
    hookCatalog: Object.freeze([]),
    runtimeInfo: null,
    runs: Object.freeze([]),
    activeRunCount: 0,
  });
}

function projectSnapshotV2(
  scope: TenantAgentDashboardScope,
  rawConfig: unknown,
  rawRuns: unknown,
  rawActive: unknown,
  canModify: boolean,
  hookCatalog: readonly TenantRuntimeHookCatalogEntry[],
  runtimeInfo: TenantAgentRuntimeInfo | null,
): TenantAgentDashboardSnapshot {
  const config = readConfigV2(rawConfig, scope);
  if (
    !isRecordV2(rawRuns) ||
    rawRuns.tenant_id !== scope.tenantId ||
    !Array.isArray(rawRuns.runs) ||
    !isNonnegativeIntegerV2(rawRuns.total) ||
    !isRecordV2(rawActive) ||
    rawActive.tenant_id !== scope.tenantId ||
    !isNonnegativeIntegerV2(rawActive.active_count)
  ) {
    throw tenantAgentDashboardContractErrorV2('cloud_tenant_agent_dashboard_contract_invalid');
  }
  const runs = Object.freeze(rawRuns.runs.map(readRunV2));
  if (rawRuns.total < runs.length) {
    throw tenantAgentDashboardContractErrorV2('cloud_tenant_agent_dashboard_contract_invalid');
  }
  const privileged: TenantAgentDashboardAction[] = canModify
    ? ['update-config', 'view-hook-catalog']
    : [];
  const allowedActions: TenantAgentDashboardAction[] = [
    'view-config',
    ...privileged,
    ...READ_ACTIONS_V2.slice(1),
  ];
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: TENANT_AGENT_DASHBOARD_SERVICE_VERSION_V2,
    contractVersion: TENANT_AGENT_DASHBOARD_CONTRACT_VERSION_V2,
    allowedActions: Object.freeze(allowedActions),
    authorityRevision: config.authorityRevision,
    canModify,
    config,
    hookCatalog,
    runtimeInfo,
    runs,
    activeRunCount: rawActive.active_count,
  });
}

function readRuntimeInfoV2(raw: unknown): TenantAgentRuntimeInfo {
  if (
    !isRecordV2(raw) ||
    !isNonemptyV2(raw.edition) ||
    !Array.isArray(raw.features) ||
    !raw.features.every(isRecordV2) ||
    !isRecordV2(raw.agent_runtime) ||
    !isNonemptyV2(raw.agent_runtime.mode) ||
    !isRecordV2(raw.memory_runtime) ||
    !isNonemptyV2(raw.memory_runtime.mode) ||
    !isNonemptyV2(raw.memory_runtime.tool_provider_mode) ||
    typeof raw.memory_runtime.failure_persistence_enabled !== 'boolean'
  ) {
    throw tenantAgentDashboardContractErrorV2(
      'cloud_tenant_agent_dashboard_system_info_invalid',
    );
  }
  return Object.freeze({
    edition: raw.edition,
    features: Object.freeze(
      raw.features.map((feature) =>
        cloneJsonRecordV2(feature, 'cloud_tenant_agent_dashboard_system_info_invalid'),
      ),
    ),
    agentRuntimeMode: raw.agent_runtime.mode,
    memoryRuntimeMode: raw.memory_runtime.mode,
    toolProviderMode: raw.memory_runtime.tool_provider_mode,
    failurePersistenceEnabled: raw.memory_runtime.failure_persistence_enabled,
  });
}

function readConfigV2(
  raw: unknown,
  scope: TenantAgentDashboardScope,
): TenantAgentConfig {
  const reason = 'cloud_tenant_agent_dashboard_contract_invalid';
  if (
    !isRecordV2(raw) ||
    !isNonemptyV2(raw.id) ||
    raw.tenant_id !== scope.tenantId ||
    !isNonemptyV2(raw.config_type) ||
    !isNonemptyV2(raw.llm_model) ||
    !isFiniteNumberV2(raw.llm_temperature) ||
    typeof raw.pattern_learning_enabled !== 'boolean' ||
    typeof raw.multi_level_thinking_enabled !== 'boolean' ||
    !isPositiveIntegerV2(raw.max_work_plan_steps) ||
    !isPositiveIntegerV2(raw.tool_timeout_seconds) ||
    !isStringArrayV2(raw.enabled_tools) ||
    !isStringArrayV2(raw.disabled_tools) ||
    !Array.isArray(raw.runtime_hooks) ||
    typeof raw.runtime_hook_settings_redacted !== 'boolean' ||
    typeof raw.multi_agent_enabled !== 'boolean' ||
    !isPositiveIntegerV2(raw.authority_revision) ||
    !isNonemptyV2(raw.created_at) ||
    !isNonemptyV2(raw.updated_at)
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  return Object.freeze({
    id: raw.id,
    tenantId: raw.tenant_id,
    configType: raw.config_type,
    llmModel: raw.llm_model,
    llmTemperature: raw.llm_temperature,
    patternLearningEnabled: raw.pattern_learning_enabled,
    multiLevelThinkingEnabled: raw.multi_level_thinking_enabled,
    maxWorkPlanSteps: raw.max_work_plan_steps,
    toolTimeoutSeconds: raw.tool_timeout_seconds,
    enabledTools: Object.freeze([...raw.enabled_tools]),
    disabledTools: Object.freeze([...raw.disabled_tools]),
    runtimeHooks: Object.freeze(raw.runtime_hooks.map(readRuntimeHookV2)),
    runtimeHookSettingsRedacted: raw.runtime_hook_settings_redacted,
    multiAgentEnabled: raw.multi_agent_enabled,
    authorityRevision: raw.authority_revision,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  });
}

function readRuntimeHookV2(raw: unknown): TenantRuntimeHook {
  if (
    !isRecordV2(raw) ||
    !isNonemptyV2(raw.hook_name) ||
    typeof raw.plugin_name !== 'string' ||
    !isNullableStringV2(raw.hook_family) ||
    !isNonemptyV2(raw.executor_kind) ||
    !isNullableStringV2(raw.source_ref) ||
    !isNullableStringV2(raw.entrypoint) ||
    typeof raw.enabled !== 'boolean' ||
    !isNullableIntegerV2(raw.priority) ||
    !isRecordV2(raw.settings)
  ) {
    throw tenantAgentDashboardContractErrorV2('cloud_tenant_agent_dashboard_contract_invalid');
  }
  return Object.freeze({
    hookName: raw.hook_name,
    pluginName: raw.plugin_name,
    hookFamily: raw.hook_family,
    executorKind: raw.executor_kind,
    sourceRef: raw.source_ref,
    entrypoint: raw.entrypoint,
    enabled: raw.enabled,
    priority: raw.priority,
    settings: cloneJsonRecordV2(
      raw.settings,
      'cloud_tenant_agent_dashboard_contract_invalid',
    ),
  });
}

function readRunV2(raw: unknown): TenantAgentRun {
  const reason = 'cloud_tenant_agent_dashboard_trace_contract_invalid';
  if (
    !isRecordV2(raw) ||
    !isNonemptyV2(raw.run_id) ||
    !isNonemptyV2(raw.conversation_id) ||
    !isNonemptyV2(raw.subagent_name) ||
    typeof raw.task !== 'string' ||
    !isNonemptyV2(raw.status) ||
    !isNonemptyV2(raw.created_at) ||
    !isNullableStringV2(raw.started_at) ||
    !isNullableStringV2(raw.ended_at) ||
    !isNullableStringV2(raw.summary) ||
    !isNullableStringV2(raw.error) ||
    !isNullableNumberV2(raw.execution_time_ms) ||
    !isNullableNumberV2(raw.tokens_used) ||
    !isNullableStringV2(raw.trace_id) ||
    !isNullableStringV2(raw.parent_span_id)
  ) {
    throw tenantAgentDashboardContractErrorV2(reason);
  }
  return Object.freeze({
    runId: raw.run_id,
    conversationId: raw.conversation_id,
    subagentName: raw.subagent_name,
    task: raw.task,
    status: raw.status,
    createdAt: raw.created_at,
    startedAt: raw.started_at,
    endedAt: raw.ended_at,
    summary: raw.summary,
    error: raw.error,
    executionTimeMs: raw.execution_time_ms,
    tokensUsed: raw.tokens_used,
    traceId: raw.trace_id,
    parentSpanId: raw.parent_span_id,
  });
}

function readTraceV2(
  raw: unknown,
  conversationId: string,
  traceId: string,
): TenantAgentTrace {
  if (
    !isRecordV2(raw) ||
    raw.trace_id !== traceId ||
    raw.conversation_id !== conversationId ||
    !Array.isArray(raw.runs) ||
    !isNonnegativeIntegerV2(raw.total)
  ) {
    throw tenantAgentDashboardContractErrorV2(
      'cloud_tenant_agent_dashboard_trace_contract_invalid',
    );
  }
  const runs = Object.freeze(raw.runs.map(readRunV2));
  if (raw.total < runs.length) {
    throw tenantAgentDashboardContractErrorV2(
      'cloud_tenant_agent_dashboard_trace_contract_invalid',
    );
  }
  return Object.freeze({ traceId, conversationId, runs, total: raw.total });
}

function readCanModifyV2(raw: unknown): boolean {
  if (!isRecordV2(raw) || typeof raw.can_modify !== 'boolean') {
    throw tenantAgentDashboardContractErrorV2('cloud_tenant_agent_dashboard_contract_invalid');
  }
  return raw.can_modify;
}

function readHookCatalogV2(raw: unknown): readonly TenantRuntimeHookCatalogEntry[] {
  if (!isRecordV2(raw) || !Array.isArray(raw.hooks)) {
    throw tenantAgentDashboardContractErrorV2(
      'cloud_tenant_agent_dashboard_hook_catalog_invalid',
    );
  }
  return Object.freeze(
    raw.hooks.map((entry) => {
      if (
        !isRecordV2(entry) ||
        typeof entry.plugin_name !== 'string' ||
        !isNonemptyV2(entry.hook_name) ||
        !isNullableStringV2(entry.hook_family) ||
        !isNonemptyV2(entry.display_name) ||
        typeof entry.description !== 'string' ||
        !isNullableIntegerV2(entry.default_priority) ||
        typeof entry.default_enabled !== 'boolean' ||
        !isNonemptyV2(entry.default_executor_kind) ||
        !isNullableStringV2(entry.default_source_ref) ||
        !isNullableStringV2(entry.default_entrypoint) ||
        !isRecordV2(entry.default_settings) ||
        !isRecordV2(entry.settings_schema)
      ) {
        throw tenantAgentDashboardContractErrorV2(
          'cloud_tenant_agent_dashboard_hook_catalog_invalid',
        );
      }
      return Object.freeze({
        key: `${entry.plugin_name}.${entry.hook_name}`,
        hookName: entry.hook_name,
        pluginName: entry.plugin_name,
        hookFamily: entry.hook_family,
        displayName: entry.display_name,
        description: entry.description,
        defaultPriority: entry.default_priority,
        defaultEnabled: entry.default_enabled,
        defaultExecutorKind: entry.default_executor_kind,
        defaultSourceRef: entry.default_source_ref,
        defaultEntrypoint: entry.default_entrypoint,
        defaultSettings: cloneJsonRecordV2(
          entry.default_settings,
          'cloud_tenant_agent_dashboard_hook_catalog_invalid',
        ),
        settingsSchema: cloneJsonRecordV2(
          entry.settings_schema,
          'cloud_tenant_agent_dashboard_hook_catalog_invalid',
        ),
      });
    }),
  );
}

function isJsonRecordV2(value: unknown): value is Record<string, unknown> {
  if (!isRecordV2(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return false;
  return Object.keys(value).every((key) => key !== '__proto__' && key !== 'constructor');
}

function cloneJsonRecordV2(
  value: Record<string, unknown>,
  reason: string,
): Readonly<Record<string, unknown>> {
  const clone = cloneJsonValueV2(value, reason);
  if (!isRecordV2(clone)) throw tenantAgentDashboardContractErrorV2(reason);
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

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonemptyV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isStringArrayV2(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonemptyV2);
}

function isFiniteNumberV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isPositiveIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 1;
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isNullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableIntegerV2(value: unknown): value is number | null {
  return value === null || Number.isSafeInteger(value);
}

function isNullableNumberV2(value: unknown): value is number | null {
  return value === null || isFiniteNumberV2(value);
}
