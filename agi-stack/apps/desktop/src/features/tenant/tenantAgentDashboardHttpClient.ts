import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  TenantAgentConfig,
  TenantAgentDashboardAction,
  TenantAgentDashboardClient,
  TenantAgentDashboardScope,
  TenantAgentDashboardSnapshot,
  TenantAgentEditableConfig,
  TenantAgentRuntimeInfo,
  TenantAgentRun,
  TenantAgentTrace,
  TenantRuntimeHook,
  TenantRuntimeHookCatalogEntry,
} from './tenantAgentDashboardClient';

const CONTRACT_VERSION = '3.0.0';
const READ_ACTIONS = Object.freeze<TenantAgentDashboardAction[]>([
  'view-config',
  'list-runs',
  'filter-runs',
  'inspect-run',
  'inspect-trace',
  'refresh',
  'retry',
]);

export function createTenantAgentDashboardHttpClient(
  config: DesktopRuntimeConfig,
): TenantAgentDashboardClient {
  const runtime = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, signal) {
      requireScope(runtime, scope);
      if (runtime.mode === 'local') return localUnavailable(scope);
      const query = tenantQuery(scope);
      const [rawConfig, rawPermission, rawRuns, rawActive, runtimeInfo] = await Promise.all([
        requestJson(runtime, `/api/v1/agent/config?${query}`, {
          method: 'GET',
          signal,
        }),
        requestJson(runtime, `/api/v1/agent/config/can-modify?${query}`, {
          method: 'GET',
          signal,
        }),
        requestJson(
          runtime,
          `/api/v1/agent/trace/runs/tenant/${encodeURIComponent(scope.tenantId)}?limit=20`,
          { method: 'GET', signal },
        ),
        requestJson(
          runtime,
          `/api/v1/agent/trace/runs/tenant/${encodeURIComponent(scope.tenantId)}/active/count`,
          { method: 'GET', signal },
        ),
        loadOptionalRuntimeInfo(runtime, signal),
      ]);
      const canModify = readCanModify(rawPermission);
      const hookCatalog = canModify
        ? readHookCatalog(
            await requestJson(runtime, `/api/v1/agent/config/hooks/catalog?${query}`, {
              method: 'GET',
              signal,
            }),
          )
        : Object.freeze<TenantRuntimeHookCatalogEntry[]>([]);
      return projectSnapshot(
        scope,
        rawConfig,
        rawRuns,
        rawActive,
        canModify,
        hookCatalog,
        runtimeInfo,
      );
    },
    async updateConfig(scope, input, expectedRevision, signal) {
      requireScope(runtime, scope);
      if (runtime.mode === 'local') {
        throw contractError('local_agent_dashboard_authority_unavailable');
      }
      if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1) {
        throw contractError('tenant_agent_dashboard_revision_invalid');
      }
      const query = new URLSearchParams({
        tenant_id: scope.tenantId,
        expected_revision: String(expectedRevision),
      });
      return readConfig(
        await requestJson(runtime, `/api/v1/agent/config?${query}`, {
          method: 'PUT',
          body: updateBody(input),
          signal,
        }),
        scope,
      );
    },
    async inspectTrace(scope, conversationId, traceId, signal) {
      requireScope(runtime, scope);
      requireId(conversationId, 'tenant_agent_dashboard_conversation_id_invalid');
      requireId(traceId, 'tenant_agent_dashboard_trace_id_invalid');
      if (runtime.mode === 'local') {
        throw contractError('local_agent_dashboard_authority_unavailable');
      }
      const raw = await requestJson(
        runtime,
        `/api/v1/agent/trace/runs/${encodeURIComponent(conversationId)}/trace/${encodeURIComponent(traceId)}`,
        { method: 'GET', signal },
      );
      return readTrace(raw, conversationId, traceId);
    },
  });
}

type RequestOptions = Readonly<{
  method: 'GET' | 'PUT';
  body?: Readonly<Record<string, unknown>>;
  signal?: AbortSignal;
}>;

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: options.method,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(errorMessage(response.status, payload), response.status, payload);
  }
  if (!isJson || payload === null) {
    throw contractError('cloud_tenant_agent_dashboard_contract_invalid');
  }
  return payload;
}

async function loadOptionalRuntimeInfo(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<TenantAgentRuntimeInfo | null> {
  try {
    return readRuntimeInfo(
      await requestJson(config, '/api/v1/system/info', {
        method: 'GET',
        signal,
      }),
    );
  } catch (error) {
    if (signal?.aborted) throw error;
    return null;
  }
}

function projectSnapshot(
  scope: TenantAgentDashboardScope,
  rawConfig: unknown,
  rawRuns: unknown,
  rawActive: unknown,
  canModify: boolean,
  hookCatalog: readonly TenantRuntimeHookCatalogEntry[],
  runtimeInfo: TenantAgentRuntimeInfo | null,
): TenantAgentDashboardSnapshot {
  const config = readConfig(rawConfig, scope);
  if (
    !isRecord(rawRuns) ||
    rawRuns.tenant_id !== scope.tenantId ||
    !Array.isArray(rawRuns.runs) ||
    !isNonnegativeInteger(rawRuns.total) ||
    !isRecord(rawActive) ||
    rawActive.tenant_id !== scope.tenantId ||
    !isNonnegativeInteger(rawActive.active_count)
  ) {
    throw contractError('cloud_tenant_agent_dashboard_contract_invalid');
  }
  const runs = Object.freeze(rawRuns.runs.map(readRun));
  if (rawRuns.total < runs.length) {
    throw contractError('cloud_tenant_agent_dashboard_contract_invalid');
  }
  const privileged: TenantAgentDashboardAction[] = canModify
    ? ['update-config', 'view-hook-catalog']
    : [];
  const allowedActions: TenantAgentDashboardAction[] = [
    'view-config',
    ...privileged,
    ...READ_ACTIONS.slice(1),
  ];
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: CONTRACT_VERSION,
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

function readRuntimeInfo(raw: unknown): TenantAgentRuntimeInfo {
  if (
    !isRecord(raw) ||
    !isNonempty(raw.edition) ||
    !Array.isArray(raw.features) ||
    !raw.features.every(isRecord) ||
    !isRecord(raw.agent_runtime) ||
    !isNonempty(raw.agent_runtime.mode) ||
    !isRecord(raw.memory_runtime) ||
    !isNonempty(raw.memory_runtime.mode) ||
    !isNonempty(raw.memory_runtime.tool_provider_mode) ||
    typeof raw.memory_runtime.failure_persistence_enabled !== 'boolean'
  ) {
    throw contractError('cloud_tenant_agent_dashboard_system_info_invalid');
  }
  return Object.freeze({
    edition: raw.edition,
    features: Object.freeze(raw.features.map((feature) => Object.freeze({ ...feature }))),
    agentRuntimeMode: raw.agent_runtime.mode,
    memoryRuntimeMode: raw.memory_runtime.mode,
    toolProviderMode: raw.memory_runtime.tool_provider_mode,
    failurePersistenceEnabled: raw.memory_runtime.failure_persistence_enabled,
  });
}

function readConfig(raw: unknown, scope: TenantAgentDashboardScope): TenantAgentConfig {
  const reason = 'cloud_tenant_agent_dashboard_contract_invalid';
  if (
    !isRecord(raw) ||
    !isNonempty(raw.id) ||
    raw.tenant_id !== scope.tenantId ||
    !isNonempty(raw.config_type) ||
    !isNonempty(raw.llm_model) ||
    !isFiniteNumber(raw.llm_temperature) ||
    typeof raw.pattern_learning_enabled !== 'boolean' ||
    typeof raw.multi_level_thinking_enabled !== 'boolean' ||
    !isPositiveInteger(raw.max_work_plan_steps) ||
    !isPositiveInteger(raw.tool_timeout_seconds) ||
    !isStringArray(raw.enabled_tools) ||
    !isStringArray(raw.disabled_tools) ||
    !Array.isArray(raw.runtime_hooks) ||
    typeof raw.runtime_hook_settings_redacted !== 'boolean' ||
    typeof raw.multi_agent_enabled !== 'boolean' ||
    !isPositiveInteger(raw.authority_revision) ||
    !isNonempty(raw.created_at) ||
    !isNonempty(raw.updated_at)
  ) {
    throw contractError(reason);
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
    runtimeHooks: Object.freeze(raw.runtime_hooks.map(readRuntimeHook)),
    runtimeHookSettingsRedacted: raw.runtime_hook_settings_redacted,
    multiAgentEnabled: raw.multi_agent_enabled,
    authorityRevision: raw.authority_revision,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  });
}

function readRuntimeHook(raw: unknown): TenantRuntimeHook {
  if (
    !isRecord(raw) ||
    !isNonempty(raw.hook_name) ||
    typeof raw.plugin_name !== 'string' ||
    !isNullableString(raw.hook_family) ||
    !isNonempty(raw.executor_kind) ||
    !isNullableString(raw.source_ref) ||
    !isNullableString(raw.entrypoint) ||
    typeof raw.enabled !== 'boolean' ||
    !isNullableInteger(raw.priority) ||
    !isRecord(raw.settings)
  ) {
    throw contractError('cloud_tenant_agent_dashboard_contract_invalid');
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
    settings: Object.freeze({ ...raw.settings }),
  });
}

function readRun(raw: unknown): TenantAgentRun {
  const reason = 'cloud_tenant_agent_dashboard_trace_contract_invalid';
  if (
    !isRecord(raw) ||
    !isNonempty(raw.run_id) ||
    !isNonempty(raw.conversation_id) ||
    !isNonempty(raw.subagent_name) ||
    typeof raw.task !== 'string' ||
    !isNonempty(raw.status) ||
    !isNonempty(raw.created_at) ||
    !isNullableString(raw.started_at) ||
    !isNullableString(raw.ended_at) ||
    !isNullableString(raw.summary) ||
    !isNullableString(raw.error) ||
    !isNullableNumber(raw.execution_time_ms) ||
    !isNullableNumber(raw.tokens_used) ||
    !isNullableString(raw.trace_id) ||
    !isNullableString(raw.parent_span_id)
  ) {
    throw contractError(reason);
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

function readTrace(raw: unknown, conversationId: string, traceId: string): TenantAgentTrace {
  if (
    !isRecord(raw) ||
    raw.trace_id !== traceId ||
    raw.conversation_id !== conversationId ||
    !Array.isArray(raw.runs) ||
    !isNonnegativeInteger(raw.total)
  ) {
    throw contractError('cloud_tenant_agent_dashboard_trace_contract_invalid');
  }
  const runs = Object.freeze(raw.runs.map(readRun));
  if (raw.total < runs.length) {
    throw contractError('cloud_tenant_agent_dashboard_trace_contract_invalid');
  }
  return Object.freeze({ traceId, conversationId, runs, total: raw.total });
}

function readCanModify(raw: unknown): boolean {
  if (!isRecord(raw) || typeof raw.can_modify !== 'boolean') {
    throw contractError('cloud_tenant_agent_dashboard_contract_invalid');
  }
  return raw.can_modify;
}

function readHookCatalog(raw: unknown): readonly TenantRuntimeHookCatalogEntry[] {
  if (!isRecord(raw) || !Array.isArray(raw.hooks)) {
    throw contractError('cloud_tenant_agent_dashboard_hook_catalog_invalid');
  }
  return Object.freeze(
    raw.hooks.map((entry) => {
      if (
        !isRecord(entry) ||
        typeof entry.plugin_name !== 'string' ||
        !isNonempty(entry.hook_name) ||
        !isNullableString(entry.hook_family) ||
        !isNonempty(entry.display_name) ||
        typeof entry.description !== 'string' ||
        !isNullableInteger(entry.default_priority) ||
        typeof entry.default_enabled !== 'boolean' ||
        !isNonempty(entry.default_executor_kind) ||
        !isNullableString(entry.default_source_ref) ||
        !isNullableString(entry.default_entrypoint) ||
        !isRecord(entry.default_settings) ||
        !isRecord(entry.settings_schema)
      ) {
        throw contractError('cloud_tenant_agent_dashboard_hook_catalog_invalid');
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
        defaultSettings: Object.freeze({ ...entry.default_settings }),
        settingsSchema: Object.freeze({ ...entry.settings_schema }),
      });
    }),
  );
}

function updateBody(input: TenantAgentEditableConfig): Readonly<Record<string, unknown>> {
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

function localUnavailable(scope: TenantAgentDashboardScope): TenantAgentDashboardSnapshot {
  return Object.freeze({
    scope,
    authority: 'local',
    availability: 'unavailable',
    reasonCode: 'local_agent_dashboard_authority_unavailable',
    serviceVersion: '0.1.0',
    contractVersion: CONTRACT_VERSION,
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

function tenantQuery(scope: TenantAgentDashboardScope): string {
  return new URLSearchParams({ tenant_id: scope.tenantId }).toString();
}

function requireScope(config: DesktopRuntimeConfig, scope: TenantAgentDashboardScope): void {
  if (scope.authority !== config.mode || scope.tenantId !== config.tenantId || !scope.tenantId) {
    throw contractError('tenant_agent_dashboard_runtime_scope_mismatch');
  }
}

function requireId(value: string, reason: string): void {
  if (!isNonempty(value) || value !== value.trim()) throw contractError(reason);
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string') return payload.detail;
  const reasonCode = structuredReasonCode(payload);
  if (reasonCode) return reasonCode;
  return `tenant_agent_dashboard_http_${status}`;
}

function structuredReasonCode(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  if (typeof payload.reason_code === 'string') return payload.reason_code;
  return isRecord(payload.detail) && typeof payload.detail.reason_code === 'string'
    ? payload.detail.reason_code
    : null;
}

function contractError(reason: string): DesktopApiError {
  return new DesktopApiError(reason, 0, { reason_code: reason });
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
