import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import type {
  TenantAgentConfig,
  TenantAgentDashboardScope,
  TenantAgentDashboardSnapshot,
  TenantAgentEditableConfig,
  TenantAgentTrace,
} from '../features/tenant/tenantAgentDashboardClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  requireDesktopTenantAgentDashboardConfigV2,
  requireDesktopTenantAgentDashboardSnapshotV2,
  requireDesktopTenantAgentDashboardTraceV2,
  requireDesktopTenantAgentEditableConfigV2,
  tenantAgentDashboardContractErrorV2,
} from './desktopTenantAgentDashboardContractV2';
import {
  desktopTenantAgentDashboardUpdateBodyV2,
  localDesktopTenantAgentDashboardUnavailableV2,
  projectDesktopTenantAgentDashboardConfigV2,
  projectDesktopTenantAgentDashboardPermissionV2,
  projectDesktopTenantAgentDashboardSnapshotV2,
  projectDesktopTenantAgentDashboardTraceV2,
} from './desktopTenantAgentDashboardHttpProjectionV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_TENANT_AGENT_DASHBOARD_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-agent-dashboard-authority';
export const DESKTOP_TENANT_AGENT_DASHBOARD_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-agent-dashboard-authority';
export const DESKTOP_TENANT_AGENT_DASHBOARD_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopTenantAgentDashboardOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantAgentDashboardScope;
  signal?: AbortSignal;
}>;

export type DesktopTenantAgentDashboardUpdateConfigInputV2 =
  DesktopTenantAgentDashboardOperationInputV2 &
    Readonly<{
      input: TenantAgentEditableConfig;
      expectedRevision: number;
    }>;

export type DesktopTenantAgentDashboardInspectTraceInputV2 =
  DesktopTenantAgentDashboardOperationInputV2 &
    Readonly<{
      conversationId: string;
      traceId: string;
    }>;

export interface DesktopTenantAgentDashboardAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<TenantAgentDashboardSnapshot>;
  readonly updateConfig: (
    input: TenantAgentEditableConfig,
    expectedRevision: number,
    signal?: AbortSignal,
  ) => Promise<TenantAgentConfig>;
  readonly inspectTrace: (
    conversationId: string,
    traceId: string,
    signal?: AbortSignal,
  ) => Promise<TenantAgentTrace>;
}

export interface DesktopTenantAgentDashboardAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: TenantAgentDashboardScope,
  ) => DesktopTenantAgentDashboardAuthorityV2;
}

export interface DesktopTenantAgentDashboardOperationsV2 {
  readonly loadTenantAgentDashboard: (
    input: DesktopTenantAgentDashboardOperationInputV2,
  ) => Promise<TenantAgentDashboardSnapshot>;
  readonly updateTenantAgentDashboardConfig: (
    input: DesktopTenantAgentDashboardUpdateConfigInputV2,
  ) => Promise<TenantAgentConfig>;
  readonly inspectTenantAgentDashboardTrace: (
    input: DesktopTenantAgentDashboardInspectTraceInputV2,
  ) => Promise<TenantAgentTrace>;
}

type PreparedOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantAgentDashboardScope;
  signal?: AbortSignal;
}>;

type PreparedUpdateConfigOperationV2 = PreparedOperationV2 &
  Readonly<{
    input: TenantAgentEditableConfig;
    expectedRevision: number;
  }>;

type PreparedInspectTraceOperationV2 = PreparedOperationV2 &
  Readonly<{
    conversationId: string;
    traceId: string;
  }>;

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;

type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;

type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

const LOAD_INPUT_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const UPDATE_INPUT_KEYS_V2 = new Set([
  'config',
  'scope',
  'signal',
  'input',
  'expectedRevision',
]);
const TRACE_INPUT_KEYS_V2 = new Set([
  'config',
  'scope',
  'signal',
  'conversationId',
  'traceId',
]);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId']);
const AUTHORITY_KEYS_V2 = new Set(['load', 'updateConfig', 'inspectTrace']);

export class DesktopTenantAgentDashboardAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantAgentDashboardAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantAgentDashboardAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_agent_dashboard_authority_config_invalid',
      'desktop tenant agent dashboard authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopTenantAgentDashboardAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopTenantAgentDashboardAuthorityV2,
  });
  context.provide(DESKTOP_TENANT_AGENT_DASHBOARD_AUTHORITY_SERVICE_V2, service);
}

export const desktopTenantAgentDashboardAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_AGENT_DASHBOARD_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopTenantAgentDashboardAuthorityV2,
  });

export function createDesktopTenantAgentDashboardOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantAgentDashboardOperationsV2 {
  return Object.freeze({
    loadTenantAgentDashboard(input: DesktopTenantAgentDashboardOperationInputV2) {
      const prepared = prepareOperationV2(input, LOAD_INPUT_KEYS_V2);
      return runDesktopTenantAgentDashboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
    updateTenantAgentDashboardConfig(
      input: DesktopTenantAgentDashboardUpdateConfigInputV2,
    ) {
      const prepared = prepareUpdateConfigOperationV2(input);
      return runDesktopTenantAgentDashboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.updateConfig(
            prepared.input,
            prepared.expectedRevision,
            prepared.signal,
          ),
      );
    },
    inspectTenantAgentDashboardTrace(
      input: DesktopTenantAgentDashboardInspectTraceInputV2,
    ) {
      const prepared = prepareInspectTraceOperationV2(input);
      return runDesktopTenantAgentDashboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.inspectTrace(
            prepared.conversationId,
            prepared.traceId,
            prepared.signal,
          ),
      );
    },
  });
}

export function withDesktopTenantAgentDashboardAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopTenantAgentDashboardOperationInputV2,
  operation: (
    authority: DesktopTenantAgentDashboardAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopTenantAgentDashboardAuthorityOperationV2(
    actions,
    prepareOperationV2(input, LOAD_INPUT_KEYS_V2),
    operation,
  );
}

async function runDesktopTenantAgentDashboardAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedOperationV2,
  operation: (
    authority: DesktopTenantAgentDashboardAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantAgentDashboardAuthorityServiceV2>({
      service: DESKTOP_TENANT_AGENT_DASHBOARD_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_AGENT_DASHBOARD_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'tenant',
        tenant_id: prepared.scope.tenantId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantAgentDashboardAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireTenantAgentDashboardServiceV2(candidate);
      const authority = requireTenantAgentDashboardAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableTenantAgentDashboardAuthorityV2(
          authority,
          prepared.scope,
          () => operationActive,
        ),
      );
    });
  } catch (error) {
    operationFailed = true;
    throw error;
  } finally {
    operationActive = false;
    try {
      await admission.release();
    } catch (releaseError) {
      if (!operationFailed) throw releaseError;
    }
  }
}

function createDesktopTenantAgentDashboardAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: TenantAgentDashboardScope,
): DesktopTenantAgentDashboardAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const operationScope = cloneScopeV2(scope, operationConfig);
  return Object.freeze({
    async load(signal?: AbortSignal) {
      if (operationConfig.mode === 'local') {
        return localDesktopTenantAgentDashboardUnavailableV2(operationScope);
      }
      const query = tenantQueryV2(operationScope);
      const [rawConfig, rawPermission, rawRuns, rawActive, rawRuntimeInfo] =
        await Promise.all([
          requestJsonV2(operationConfig, `/api/v1/agent/config?${query}`, {
            method: 'GET',
            signal,
          }),
          requestJsonV2(
            operationConfig,
            `/api/v1/agent/config/can-modify?${query}`,
            { method: 'GET', signal },
          ),
          requestJsonV2(
            operationConfig,
            `/api/v1/agent/trace/runs/tenant/${encodeURIComponent(operationScope.tenantId)}?limit=20`,
            { method: 'GET', signal },
          ),
          requestJsonV2(
            operationConfig,
            `/api/v1/agent/trace/runs/tenant/${encodeURIComponent(operationScope.tenantId)}/active/count`,
            { method: 'GET', signal },
          ),
          loadOptionalRuntimeInfoV2(operationConfig, signal),
        ]);
      const canModify = projectDesktopTenantAgentDashboardPermissionV2(rawPermission);
      const rawHookCatalog = canModify
        ? await requestJsonV2(
            operationConfig,
            `/api/v1/agent/config/hooks/catalog?${query}`,
            { method: 'GET', signal },
          )
        : null;
      return projectDesktopTenantAgentDashboardSnapshotV2(
        operationScope,
        rawConfig,
        rawRuns,
        rawActive,
        canModify,
        rawHookCatalog,
        rawRuntimeInfo,
      );
    },
    async updateConfig(
      input: TenantAgentEditableConfig,
      expectedRevision: number,
      signal?: AbortSignal,
    ) {
      if (operationConfig.mode === 'local') {
        throw tenantAgentDashboardContractErrorV2(
          'local_agent_dashboard_authority_unavailable',
        );
      }
      const query = new URLSearchParams({
        tenant_id: operationScope.tenantId,
        expected_revision: String(expectedRevision),
      });
      const raw = await requestJsonV2(
        operationConfig,
        `/api/v1/agent/config?${query}`,
        {
          method: 'PUT',
          body: desktopTenantAgentDashboardUpdateBodyV2(input),
          signal,
        },
      );
      return projectDesktopTenantAgentDashboardConfigV2(raw, operationScope);
    },
    async inspectTrace(
      conversationId: string,
      traceId: string,
      signal?: AbortSignal,
    ) {
      if (operationConfig.mode === 'local') {
        throw tenantAgentDashboardContractErrorV2(
          'local_agent_dashboard_authority_unavailable',
        );
      }
      const raw = await requestJsonV2(
        operationConfig,
        `/api/v1/agent/trace/runs/${encodeURIComponent(conversationId)}/trace/${encodeURIComponent(traceId)}`,
        { method: 'GET', signal },
      );
      return projectDesktopTenantAgentDashboardTraceV2(raw, conversationId, traceId);
    },
  });
}

function createRevocableTenantAgentDashboardAuthorityV2(
  authority: DesktopTenantAgentDashboardAuthorityV2,
  scope: TenantAgentDashboardScope,
  isOperationActive: () => boolean,
): DesktopTenantAgentDashboardAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantAgentDashboardSnapshotV2(result, scope);
    },
    async updateConfig(
      input: TenantAgentEditableConfig,
      expectedRevision: number,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.updateConfig(input, expectedRevision, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantAgentDashboardConfigV2(result, scope);
    },
    async inspectTrace(
      conversationId: string,
      traceId: string,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.inspectTrace(conversationId, traceId, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantAgentDashboardTraceV2(result, conversationId, traceId);
    },
  });
}

type RequestOptionsV2 = Readonly<{
  method: 'GET' | 'PUT';
  body?: Readonly<Record<string, unknown>>;
  signal?: AbortSignal;
}>;

async function requestJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptionsV2,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await desktopApiFetch(config, path, {
    method: options.method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(errorMessageV2(response.status, payload), response.status, payload);
  }
  if (!isJson || payload === null) {
    throw tenantAgentDashboardContractErrorV2(
      'cloud_tenant_agent_dashboard_contract_invalid',
    );
  }
  return payload;
}

async function loadOptionalRuntimeInfoV2(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<unknown | null> {
  try {
    return await requestJsonV2(config, '/api/v1/system/info', {
      method: 'GET',
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    return null;
  }
}

function prepareOperationV2(
  input: DesktopTenantAgentDashboardOperationInputV2,
  allowedKeys: ReadonlySet<string>,
): PreparedOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidOperationInputV2();
  }
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const scope = cloneScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function prepareUpdateConfigOperationV2(
  input: DesktopTenantAgentDashboardUpdateConfigInputV2,
): PreparedUpdateConfigOperationV2 {
  const prepared = prepareOperationV2(input, UPDATE_INPUT_KEYS_V2);
  if (
    !Object.hasOwn(input, 'input') ||
    !Object.hasOwn(input, 'expectedRevision') ||
    !Number.isSafeInteger(input.expectedRevision) ||
    input.expectedRevision < 1
  ) {
    throw invalidOperationInputV2();
  }
  let editable: TenantAgentEditableConfig;
  try {
    editable = requireDesktopTenantAgentEditableConfigV2(input.input);
  } catch {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    ...prepared,
    input: editable,
    expectedRevision: input.expectedRevision,
  });
}

function prepareInspectTraceOperationV2(
  input: DesktopTenantAgentDashboardInspectTraceInputV2,
): PreparedInspectTraceOperationV2 {
  const prepared = prepareOperationV2(input, TRACE_INPUT_KEYS_V2);
  if (
    !Object.hasOwn(input, 'conversationId') ||
    !Object.hasOwn(input, 'traceId') ||
    !isCanonicalStringV2(input.conversationId) ||
    !isCanonicalStringV2(input.traceId)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({
    ...prepared,
    conversationId: input.conversationId,
    traceId: input.traceId,
  });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidOperationInputV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalStringV2(copy.tenantId)
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze(copy);
}

function cloneScopeV2(
  scope: TenantAgentDashboardScope,
  config: DesktopRuntimeConfig,
): TenantAgentDashboardScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactOptionalKeysV2(scope, SCOPE_KEYS_V2) ||
    Object.keys(scope).length !== SCOPE_KEYS_V2.size ||
    scope.authority !== config.mode ||
    !isCanonicalStringV2(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  ) {
    throw invalidOperationInputV2();
  }
  return Object.freeze({ authority: scope.authority, tenantId: scope.tenantId });
}

function requireTenantAgentDashboardServiceV2(
  value: unknown,
): DesktopTenantAgentDashboardAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopTenantAgentDashboardAuthorityServiceV2;
}

function requireTenantAgentDashboardAuthorityV2(
  value: unknown,
): DesktopTenantAgentDashboardAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== AUTHORITY_KEYS_V2.size ||
    !Object.keys(value).every((key) => AUTHORITY_KEYS_V2.has(key)) ||
    typeof value.load !== 'function' ||
    typeof value.updateConfig !== 'function' ||
    typeof value.inspectTrace !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopTenantAgentDashboardAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopTenantAgentDashboardAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_tenant_agent_dashboard_operation_released',
    'desktop tenant agent dashboard operation has been released',
  );
}

function invalidOperationInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_agent_dashboard_operation_input_invalid',
    'desktop tenant agent dashboard operation input is invalid',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_agent_dashboard_service_invalid',
    'desktop tenant agent dashboard authority service is invalid',
  );
}

function tenantQueryV2(scope: TenantAgentDashboardScope): string {
  return new URLSearchParams({ tenant_id: scope.tenantId }).toString();
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isPlainRecordV2(payload) && typeof payload.detail === 'string') {
    return payload.detail;
  }
  const reasonCode = structuredReasonCodeV2(payload);
  return reasonCode ?? `tenant_agent_dashboard_http_${status}`;
}

function structuredReasonCodeV2(payload: unknown): string | null {
  if (!isPlainRecordV2(payload)) return null;
  if (typeof payload.reason_code === 'string') return payload.reason_code;
  return isPlainRecordV2(payload.detail) && typeof payload.detail.reason_code === 'string'
    ? payload.detail.reason_code
    : null;
}

function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_TENANT_AGENT_DASHBOARD_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_tenant_agent_dashboard_authority_catalog_missing',
      'desktop tenant agent dashboard authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
