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
  CreateTenantAgentBindingInput,
  TenantAgentBinding,
  TenantAgentBindingTestResult,
  TenantAgentBindingsClient,
  TenantAgentBindingsListQuery,
  TenantAgentBindingsScope,
  TenantAgentBindingsSnapshot,
  TestTenantAgentBindingInput,
} from '../features/tenant/tenantAgentBindingsClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  requireDesktopTenantAgentBindingTestResultV2,
  requireDesktopTenantAgentBindingV2,
  requireDesktopTenantAgentBindingsSnapshotV2,
  tenantAgentBindingsContractErrorV2,
} from './desktopTenantAgentBindingsContractV2';
import {
  desktopTenantAgentBindingCreateBodyV2,
  desktopTenantAgentBindingTestBodyV2,
  projectDesktopTenantAgentBindingTestResultV2,
  projectDesktopTenantAgentBindingV2,
  projectDesktopTenantAgentBindingsCloudSnapshotV2,
  projectDesktopTenantAgentBindingsLocalSnapshotV2,
} from './desktopTenantAgentBindingsHttpProjectionV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  cloneDesktopTenantAgentBindingsRuntimeConfigV2,
  cloneDesktopTenantAgentBindingsScopeV2,
  prepareTenantAgentBindingCreateOperationV2,
  prepareTenantAgentBindingDeleteOperationV2,
  prepareTenantAgentBindingSetEnabledOperationV2,
  prepareTenantAgentBindingTestOperationV2,
  prepareTenantAgentBindingsBaseOperationV2,
  prepareTenantAgentBindingsListOperationV2,
  type DesktopTenantAgentBindingCreateInputV2,
  type DesktopTenantAgentBindingDeleteInputV2,
  type DesktopTenantAgentBindingSetEnabledInputV2,
  type DesktopTenantAgentBindingTestInputV2,
  type DesktopTenantAgentBindingsListInputV2,
  type DesktopTenantAgentBindingsOperationInputV2,
  type PreparedTenantAgentBindingsOperationV2,
} from './desktopTenantAgentBindingsOperationContractV2';

export type {
  DesktopTenantAgentBindingCreateInputV2,
  DesktopTenantAgentBindingDeleteInputV2,
  DesktopTenantAgentBindingSetEnabledInputV2,
  DesktopTenantAgentBindingTestInputV2,
  DesktopTenantAgentBindingsListInputV2,
  DesktopTenantAgentBindingsOperationInputV2,
} from './desktopTenantAgentBindingsOperationContractV2';

export const DESKTOP_TENANT_AGENT_BINDINGS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-agent-bindings-authority';
export const DESKTOP_TENANT_AGENT_BINDINGS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-agent-bindings-authority';
export const DESKTOP_TENANT_AGENT_BINDINGS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantAgentBindingsAuthorityV2 {
  readonly list: (
    query?: TenantAgentBindingsListQuery,
    signal?: AbortSignal,
  ) => Promise<TenantAgentBindingsSnapshot>;
  readonly create: (
    input: CreateTenantAgentBindingInput,
    idempotencyKey?: string,
    signal?: AbortSignal,
  ) => Promise<TenantAgentBinding>;
  readonly delete: (
    bindingId: string,
    idempotencyKey?: string,
    signal?: AbortSignal,
  ) => Promise<void>;
  readonly setEnabled: (
    bindingId: string,
    enabled: boolean,
    idempotencyKey?: string,
    signal?: AbortSignal,
  ) => Promise<TenantAgentBinding>;
  readonly test: (
    input: TestTenantAgentBindingInput,
    idempotencyKey?: string,
    signal?: AbortSignal,
  ) => Promise<TenantAgentBindingTestResult>;
}

export interface DesktopTenantAgentBindingsAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: TenantAgentBindingsScope,
  ) => DesktopTenantAgentBindingsAuthorityV2;
}

export interface DesktopTenantAgentBindingsOperationsV2 {
  readonly listTenantAgentBindings: (
    input: DesktopTenantAgentBindingsListInputV2,
  ) => Promise<TenantAgentBindingsSnapshot>;
  readonly createTenantAgentBinding: (
    input: DesktopTenantAgentBindingCreateInputV2,
  ) => Promise<TenantAgentBinding>;
  readonly deleteTenantAgentBinding: (
    input: DesktopTenantAgentBindingDeleteInputV2,
  ) => Promise<void>;
  readonly setTenantAgentBindingEnabled: (
    input: DesktopTenantAgentBindingSetEnabledInputV2,
  ) => Promise<TenantAgentBinding>;
  readonly testTenantAgentBinding: (
    input: DesktopTenantAgentBindingTestInputV2,
  ) => Promise<TenantAgentBindingTestResult>;
}

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

const AUTHORITY_KEYS_V2 = new Set(['list', 'create', 'delete', 'setEnabled', 'test']);

export class DesktopTenantAgentBindingsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantAgentBindingsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantAgentBindingsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_agent_bindings_authority_config_invalid',
      'desktop tenant agent bindings authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopTenantAgentBindingsAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopTenantAgentBindingsAuthorityV2,
  });
  context.provide(DESKTOP_TENANT_AGENT_BINDINGS_AUTHORITY_SERVICE_V2, service);
}

export const desktopTenantAgentBindingsAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_AGENT_BINDINGS_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopTenantAgentBindingsAuthorityV2,
  });

export function createDesktopTenantAgentBindingsOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantAgentBindingsOperationsV2 {
  return Object.freeze({
    listTenantAgentBindings(input: DesktopTenantAgentBindingsListInputV2) {
      const prepared = prepareTenantAgentBindingsListOperationV2(input);
      return runDesktopTenantAgentBindingsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.list(prepared.query, prepared.signal),
      );
    },
    createTenantAgentBinding(input: DesktopTenantAgentBindingCreateInputV2) {
      const prepared = prepareTenantAgentBindingCreateOperationV2(input);
      return runDesktopTenantAgentBindingsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.create(prepared.input, prepared.idempotencyKey, prepared.signal),
      );
    },
    deleteTenantAgentBinding(input: DesktopTenantAgentBindingDeleteInputV2) {
      const prepared = prepareTenantAgentBindingDeleteOperationV2(input);
      return runDesktopTenantAgentBindingsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.delete(prepared.bindingId, prepared.idempotencyKey, prepared.signal),
      );
    },
    setTenantAgentBindingEnabled(input: DesktopTenantAgentBindingSetEnabledInputV2) {
      const prepared = prepareTenantAgentBindingSetEnabledOperationV2(input);
      return runDesktopTenantAgentBindingsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.setEnabled(
            prepared.bindingId,
            prepared.enabled,
            prepared.idempotencyKey,
            prepared.signal,
          ),
      );
    },
    testTenantAgentBinding(input: DesktopTenantAgentBindingTestInputV2) {
      const prepared = prepareTenantAgentBindingTestOperationV2(input);
      return runDesktopTenantAgentBindingsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.test(prepared.input, prepared.idempotencyKey, prepared.signal),
      );
    },
  });
}

export function withDesktopTenantAgentBindingsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopTenantAgentBindingsOperationInputV2,
  operation: (
    authority: DesktopTenantAgentBindingsAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopTenantAgentBindingsAuthorityOperationV2(
    actions,
    prepareTenantAgentBindingsBaseOperationV2(input),
    operation,
  );
}

export function createDesktopTenantAgentBindingsClientV2(
  operations: DesktopTenantAgentBindingsOperationsV2,
  config: DesktopRuntimeConfig,
): TenantAgentBindingsClient {
  const operationConfig = cloneDesktopTenantAgentBindingsRuntimeConfigV2(config);
  return Object.freeze({
    async list(scope, query, options) {
      return operations.listTenantAgentBindings({
        config: operationConfig,
        scope,
        ...(query === undefined ? {} : { query }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    async create(scope, input, options) {
      return operations.createTenantAgentBinding({
        config: operationConfig,
        scope,
        input,
        ...(options?.idempotencyKey === undefined
          ? {}
          : { idempotencyKey: options.idempotencyKey }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    async delete(scope, bindingId, options) {
      return operations.deleteTenantAgentBinding({
        config: operationConfig,
        scope,
        bindingId,
        ...(options?.idempotencyKey === undefined
          ? {}
          : { idempotencyKey: options.idempotencyKey }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    async setEnabled(scope, bindingId, enabled, options) {
      return operations.setTenantAgentBindingEnabled({
        config: operationConfig,
        scope,
        bindingId,
        enabled,
        ...(options?.idempotencyKey === undefined
          ? {}
          : { idempotencyKey: options.idempotencyKey }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    async test(scope, input, options) {
      return operations.testTenantAgentBinding({
        config: operationConfig,
        scope,
        input,
        ...(options?.idempotencyKey === undefined
          ? {}
          : { idempotencyKey: options.idempotencyKey }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

async function runDesktopTenantAgentBindingsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedTenantAgentBindingsOperationV2,
  operation: (
    authority: DesktopTenantAgentBindingsAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantAgentBindingsAuthorityServiceV2>({
      service: DESKTOP_TENANT_AGENT_BINDINGS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_AGENT_BINDINGS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantAgentBindingsAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireTenantAgentBindingsServiceV2(candidate);
      const authority = requireTenantAgentBindingsAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableTenantAgentBindingsAuthorityV2(
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

function createDesktopTenantAgentBindingsAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: TenantAgentBindingsScope,
): DesktopTenantAgentBindingsAuthorityV2 {
  const operationConfig = cloneDesktopTenantAgentBindingsRuntimeConfigV2(config);
  const operationScope = cloneDesktopTenantAgentBindingsScopeV2(scope, operationConfig);
  return Object.freeze({
    async list(query?: TenantAgentBindingsListQuery, signal?: AbortSignal) {
      if (operationConfig.mode === 'local') {
        const payload = await requestJsonV2(
          operationConfig,
          bindingListPathV2(operationScope, query),
          { method: 'GET', signal },
        );
        return projectDesktopTenantAgentBindingsLocalSnapshotV2(payload, operationScope);
      }
      const [bindings, definitions, workspaceContext] = await Promise.all([
        requestJsonV2(operationConfig, bindingListPathV2(operationScope, query), {
          method: 'GET',
          signal,
        }),
        requestJsonV2(
          operationConfig,
          `/api/v1/agent/definitions?${new URLSearchParams({
            tenant_id: operationScope.tenantId,
            scope: 'tenant',
            enabled_only: 'true',
            limit: '100',
          })}`,
          { method: 'GET', signal },
        ),
        requestJsonV2(operationConfig, '/api/v1/workspace-context', {
          method: 'GET',
          signal,
        }),
      ]);
      return projectDesktopTenantAgentBindingsCloudSnapshotV2(
        bindings,
        definitions,
        workspaceContext,
        operationScope,
      );
    },
    async create(
      input: CreateTenantAgentBindingInput,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      const payload = await requestJsonV2(
        operationConfig,
        tenantMutationPathV2('/api/v1/agent/bindings', operationScope),
        {
          method: 'POST',
          body: desktopTenantAgentBindingCreateBodyV2(input),
          idempotencyKey,
          signal,
        },
      );
      return projectDesktopTenantAgentBindingV2(payload, operationScope);
    },
    async delete(
      bindingId: string,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      const payload = await requestJsonV2(
        operationConfig,
        tenantMutationPathV2(
          `/api/v1/agent/bindings/${encodeURIComponent(bindingId)}`,
          operationScope,
        ),
        { method: 'DELETE', idempotencyKey, signal },
      );
      if (!isPlainRecordV2(payload) || payload.deleted !== true || payload.id !== bindingId) {
        throw tenantAgentBindingsContractErrorV2(contractReasonV2(operationConfig));
      }
    },
    async setEnabled(
      bindingId: string,
      enabled: boolean,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      const payload = await requestJsonV2(
        operationConfig,
        tenantMutationPathV2(
          `/api/v1/agent/bindings/${encodeURIComponent(bindingId)}/enabled`,
          operationScope,
        ),
        { method: 'PATCH', body: { enabled }, idempotencyKey, signal },
      );
      return projectDesktopTenantAgentBindingV2(payload, operationScope);
    },
    async test(
      input: TestTenantAgentBindingInput,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      const payload = await requestJsonV2(
        operationConfig,
        tenantMutationPathV2('/api/v1/agent/bindings/test', operationScope),
        {
          method: 'POST',
          body: desktopTenantAgentBindingTestBodyV2(input),
          idempotencyKey,
          signal,
        },
      );
      return projectDesktopTenantAgentBindingTestResultV2(
        payload,
        contractReasonV2(operationConfig),
      );
    },
  });
}

function createRevocableTenantAgentBindingsAuthorityV2(
  authority: DesktopTenantAgentBindingsAuthorityV2,
  scope: TenantAgentBindingsScope,
  isOperationActive: () => boolean,
): DesktopTenantAgentBindingsAuthorityV2 {
  return Object.freeze({
    async list(query?: TenantAgentBindingsListQuery, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.list(query, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantAgentBindingsSnapshotV2(result, scope);
    },
    async create(
      input: CreateTenantAgentBindingInput,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.create(input, idempotencyKey, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantAgentBindingV2(result, scope);
    },
    async delete(
      bindingId: string,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.delete(bindingId, idempotencyKey, signal);
      requireOperationActiveV2(isOperationActive);
      if (result !== undefined) throw invalidServiceV2();
    },
    async setEnabled(
      bindingId: string,
      enabled: boolean,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.setEnabled(bindingId, enabled, idempotencyKey, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantAgentBindingV2(result, scope);
    },
    async test(
      input: TestTenantAgentBindingInput,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.test(input, idempotencyKey, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantAgentBindingTestResultV2(result);
    },
  });
}

type RequestOptionsV2 = Readonly<{
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: Readonly<Record<string, unknown>>;
  idempotencyKey?: string;
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
  if (options.idempotencyKey !== undefined) {
    headers.set('Idempotency-Key', options.idempotencyKey);
  }
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
    throw tenantAgentBindingsContractErrorV2(contractReasonV2(config));
  }
  return payload;
}

function requireTenantAgentBindingsServiceV2(
  value: unknown,
): DesktopTenantAgentBindingsAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopTenantAgentBindingsAuthorityServiceV2;
}

function requireTenantAgentBindingsAuthorityV2(
  value: unknown,
): DesktopTenantAgentBindingsAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.list !== 'function' ||
    typeof value.create !== 'function' ||
    typeof value.delete !== 'function' ||
    typeof value.setEnabled !== 'function' ||
    typeof value.test !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopTenantAgentBindingsAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopTenantAgentBindingsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_tenant_agent_bindings_operation_released',
    'desktop tenant agent bindings operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_agent_bindings_service_invalid',
    'desktop tenant agent bindings authority service is invalid',
  );
}

function bindingListPathV2(
  scope: TenantAgentBindingsScope,
  query?: TenantAgentBindingsListQuery,
): string {
  const params = new URLSearchParams({ tenant_id: scope.tenantId });
  if (query?.agentId !== undefined) params.set('agent_id', query.agentId);
  if (query?.enabledOnly !== undefined) params.set('enabled_only', String(query.enabledOnly));
  return `/api/v1/agent/bindings?${params}`;
}

function tenantMutationPathV2(path: string, scope: TenantAgentBindingsScope): string {
  return `${path}?${new URLSearchParams({ tenant_id: scope.tenantId })}`;
}

function contractReasonV2(config: DesktopRuntimeConfig): string {
  return `${config.mode}_tenant_agent_bindings_contract_invalid`;
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isPlainRecordV2(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  const reasonCode = structuredReasonCodeV2(payload);
  return reasonCode ?? `tenant_agent_bindings_http_${status}`;
}

function structuredReasonCodeV2(payload: unknown): string | null {
  if (!isPlainRecordV2(payload)) return null;
  if (typeof payload.reason_code === 'string') return payload.reason_code;
  return isPlainRecordV2(payload.detail) && typeof payload.detail.reason_code === 'string'
    ? payload.detail.reason_code
    : null;
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_TENANT_AGENT_BINDINGS_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_tenant_agent_bindings_authority_catalog_missing',
      'desktop tenant agent bindings authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
