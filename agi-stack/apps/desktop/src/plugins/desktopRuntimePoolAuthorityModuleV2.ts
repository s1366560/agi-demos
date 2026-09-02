import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  RuntimePoolClient,
  RuntimePoolInstancePage,
  RuntimePoolMetrics,
  RuntimePoolQuery,
  RuntimePoolScope,
  RuntimePoolStatus,
} from '../features/runtime-pool/runtimePoolClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';
import {
  requireDesktopRuntimePoolCapabilityV2,
  requireDesktopRuntimePoolInstancePageV2,
  requireDesktopRuntimePoolMetricsV2,
  requireDesktopRuntimePoolStatusV2,
  requireDesktopRuntimePoolVoidResultV2,
} from './desktopRuntimePoolContractV2';
import { createDesktopRuntimePoolHttpAuthorityV2 } from './desktopRuntimePoolHttpProjectionV2';
import {
  cloneDesktopRuntimePoolConfigV2,
  prepareDesktopRuntimePoolInstanceOperationV2,
  prepareDesktopRuntimePoolListOperationV2,
  prepareDesktopRuntimePoolOperationV2,
  prepareDesktopRuntimePoolTerminateOperationV2,
  type DesktopRuntimePoolInstanceOperationInputV2,
  type DesktopRuntimePoolListOperationInputV2,
  type DesktopRuntimePoolOperationInputV2,
  type DesktopRuntimePoolTerminateOperationInputV2,
  type PreparedDesktopRuntimePoolOperationV2,
} from './desktopRuntimePoolOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopRuntimePoolInstanceOperationInputV2,
  DesktopRuntimePoolListOperationInputV2,
  DesktopRuntimePoolOperationInputV2,
  DesktopRuntimePoolTerminateOperationInputV2,
} from './desktopRuntimePoolOperationContractV2';

export const DESKTOP_RUNTIME_POOL_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/runtime-pool-authority';
export const DESKTOP_RUNTIME_POOL_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.runtime-pool-authority';
export const DESKTOP_RUNTIME_POOL_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopRuntimePoolAuthorityV2 {
  readonly getStatus: (signal?: AbortSignal) => Promise<RuntimePoolStatus>;
  readonly listInstances: (
    query: Required<RuntimePoolQuery>,
    signal?: AbortSignal,
  ) => Promise<RuntimePoolInstancePage>;
  readonly getMetrics: (signal?: AbortSignal) => Promise<RuntimePoolMetrics>;
  readonly pauseInstance: (instanceKey: string, signal?: AbortSignal) => Promise<void>;
  readonly resumeInstance: (instanceKey: string, signal?: AbortSignal) => Promise<void>;
  readonly terminateInstance: (
    instanceKey: string,
    graceful: boolean,
    signal?: AbortSignal,
  ) => Promise<void>;
  readonly probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}

export interface DesktopRuntimePoolAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: RuntimePoolScope,
  ) => DesktopRuntimePoolAuthorityV2;
}

export interface DesktopRuntimePoolOperationsV2 {
  readonly getRuntimePoolStatus: (
    input: DesktopRuntimePoolOperationInputV2,
  ) => Promise<RuntimePoolStatus>;
  readonly listRuntimePoolInstances: (
    input: DesktopRuntimePoolListOperationInputV2,
  ) => Promise<RuntimePoolInstancePage>;
  readonly getRuntimePoolMetrics: (
    input: DesktopRuntimePoolOperationInputV2,
  ) => Promise<RuntimePoolMetrics>;
  readonly pauseRuntimePoolInstance: (
    input: DesktopRuntimePoolInstanceOperationInputV2,
  ) => Promise<void>;
  readonly resumeRuntimePoolInstance: (
    input: DesktopRuntimePoolInstanceOperationInputV2,
  ) => Promise<void>;
  readonly terminateRuntimePoolInstance: (
    input: DesktopRuntimePoolTerminateOperationInputV2,
  ) => Promise<void>;
  readonly probeRuntimePool: (
    input: DesktopRuntimePoolOperationInputV2,
  ) => Promise<DesktopCapabilityAvailability>;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 = ServiceAdmissionRejectionV2 | GenerationActionsUnavailableV2;

const AUTHORITY_KEYS_V2 = new Set([
  'getStatus',
  'listInstances',
  'getMetrics',
  'pauseInstance',
  'resumeInstance',
  'terminateInstance',
  'probe',
]);

export class DesktopRuntimePoolAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopRuntimePoolAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopRuntimePoolAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_runtime_pool_authority_config_invalid',
      'desktop runtime pool authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopRuntimePoolAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopRuntimePoolHttpAuthorityV2,
  });
  context.provide(DESKTOP_RUNTIME_POOL_AUTHORITY_SERVICE_V2, service);
}

export const desktopRuntimePoolAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_RUNTIME_POOL_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopRuntimePoolAuthorityV2,
});

export function createDesktopRuntimePoolOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopRuntimePoolOperationsV2 {
  return Object.freeze({
    getRuntimePoolStatus(input: DesktopRuntimePoolOperationInputV2) {
      const prepared = prepareDesktopRuntimePoolOperationV2(input);
      return runDesktopRuntimePoolAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.getStatus(prepared.signal),
      );
    },
    listRuntimePoolInstances(input: DesktopRuntimePoolListOperationInputV2) {
      const prepared = prepareDesktopRuntimePoolListOperationV2(input);
      return runDesktopRuntimePoolAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listInstances(prepared.query, prepared.signal),
      );
    },
    getRuntimePoolMetrics(input: DesktopRuntimePoolOperationInputV2) {
      const prepared = prepareDesktopRuntimePoolOperationV2(input);
      return runDesktopRuntimePoolAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.getMetrics(prepared.signal),
      );
    },
    pauseRuntimePoolInstance(input: DesktopRuntimePoolInstanceOperationInputV2) {
      const prepared = prepareDesktopRuntimePoolInstanceOperationV2(input);
      return runDesktopRuntimePoolAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.pauseInstance(prepared.instanceKey, prepared.signal),
      );
    },
    resumeRuntimePoolInstance(input: DesktopRuntimePoolInstanceOperationInputV2) {
      const prepared = prepareDesktopRuntimePoolInstanceOperationV2(input);
      return runDesktopRuntimePoolAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.resumeInstance(prepared.instanceKey, prepared.signal),
      );
    },
    terminateRuntimePoolInstance(input: DesktopRuntimePoolTerminateOperationInputV2) {
      const prepared = prepareDesktopRuntimePoolTerminateOperationV2(input);
      return runDesktopRuntimePoolAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.terminateInstance(prepared.instanceKey, prepared.graceful, prepared.signal),
      );
    },
    probeRuntimePool(input: DesktopRuntimePoolOperationInputV2) {
      const prepared = prepareDesktopRuntimePoolOperationV2(input);
      return runDesktopRuntimePoolAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.probe(prepared.signal),
      );
    },
  });
}

export function createDesktopRuntimePoolClientV2(
  operations: DesktopRuntimePoolOperationsV2,
  config: DesktopRuntimeConfig,
): RuntimePoolClient {
  const operationConfig = cloneDesktopRuntimePoolConfigV2(config);
  return Object.freeze({
    getStatus: (scope, options) =>
      operations.getRuntimePoolStatus({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    listInstances: (scope, query, options) =>
      operations.listRuntimePoolInstances({
        config: operationConfig,
        scope,
        ...(query === undefined ? {} : { query }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    getMetrics: (scope, options) =>
      operations.getRuntimePoolMetrics({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    pauseInstance: (scope, instanceKey, options) =>
      operations.pauseRuntimePoolInstance({
        config: operationConfig,
        scope,
        instanceKey,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    resumeInstance: (scope, instanceKey, options) =>
      operations.resumeRuntimePoolInstance({
        config: operationConfig,
        scope,
        instanceKey,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    terminateInstance: (scope, instanceKey, graceful, options) =>
      operations.terminateRuntimePoolInstance({
        config: operationConfig,
        scope,
        instanceKey,
        graceful,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
  });
}

export function withDesktopRuntimePoolAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopRuntimePoolOperationInputV2,
  operation: (authority: DesktopRuntimePoolAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopRuntimePoolAuthorityOperationV2(
    actions,
    prepareDesktopRuntimePoolOperationV2(input),
    operation,
  );
}

async function runDesktopRuntimePoolAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopRuntimePoolOperationV2,
  operation: (authority: DesktopRuntimePoolAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopRuntimePoolAuthorityServiceV2>({
      service: DESKTOP_RUNTIME_POOL_AUTHORITY_SERVICE_V2,
      version: DESKTOP_RUNTIME_POOL_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'tenant',
        tenant_id: prepared.scope.tenantId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopRuntimePoolAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireRuntimePoolServiceV2(candidate);
      const authority = requireRuntimePoolAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableRuntimePoolAuthorityV2(authority, prepared.scope, () => operationActive),
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

function createRevocableRuntimePoolAuthorityV2(
  authority: DesktopRuntimePoolAuthorityV2,
  scope: RuntimePoolScope,
  isOperationActive: () => boolean,
): DesktopRuntimePoolAuthorityV2 {
  const active = () => requireOperationActiveV2(isOperationActive);
  return Object.freeze({
    async getStatus(signal?: AbortSignal) {
      active();
      const result = await authority.getStatus(signal);
      active();
      return requireDesktopRuntimePoolStatusV2(result);
    },
    async listInstances(query: Required<RuntimePoolQuery>, signal?: AbortSignal) {
      active();
      const result = await authority.listInstances(query, signal);
      active();
      return requireDesktopRuntimePoolInstancePageV2(result, scope);
    },
    async getMetrics(signal?: AbortSignal) {
      active();
      const result = await authority.getMetrics(signal);
      active();
      return requireDesktopRuntimePoolMetricsV2(result);
    },
    async pauseInstance(instanceKey: string, signal?: AbortSignal) {
      active();
      const result = await authority.pauseInstance(instanceKey, signal);
      active();
      requireDesktopRuntimePoolVoidResultV2(result);
    },
    async resumeInstance(instanceKey: string, signal?: AbortSignal) {
      active();
      const result = await authority.resumeInstance(instanceKey, signal);
      active();
      requireDesktopRuntimePoolVoidResultV2(result);
    },
    async terminateInstance(instanceKey: string, graceful: boolean, signal?: AbortSignal) {
      active();
      const result = await authority.terminateInstance(instanceKey, graceful, signal);
      active();
      requireDesktopRuntimePoolVoidResultV2(result);
    },
    async probe(signal?: AbortSignal) {
      active();
      const result = await authority.probe(signal);
      active();
      return requireDesktopRuntimePoolCapabilityV2(result, scope);
    },
  });
}

function requireRuntimePoolServiceV2(value: unknown): DesktopRuntimePoolAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopRuntimePoolAuthorityServiceV2;
}

function requireRuntimePoolAuthorityV2(value: unknown): DesktopRuntimePoolAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    [...AUTHORITY_KEYS_V2].some((key) => typeof value[key] !== 'function')
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopRuntimePoolAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopRuntimePoolAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_runtime_pool_operation_released',
    'desktop runtime pool operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_pool_service_invalid',
    'desktop runtime pool authority service is invalid',
  );
}

function hasExactKeysV2(value: Record<string, unknown>, expected: ReadonlySet<string>): boolean {
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
    (candidate) => candidate.module_ref === DESKTOP_RUNTIME_POOL_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_runtime_pool_authority_catalog_missing',
      'desktop runtime pool authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
