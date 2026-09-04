import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  RuntimeInstancesClient,
  RuntimeInstancesPage,
  RuntimeInstancesQuery,
  RuntimeInstancesScope,
} from '../features/runtime-instances/runtimeInstancesTypes';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';
import {
  createDesktopRuntimeInstancesHttpAuthorityV2,
} from './desktopRuntimeInstancesHttpProjectionV2';
import {
  cloneDesktopRuntimeInstancesConfigV2,
  prepareDesktopRuntimeInstancesAuthorityOperationV2,
  requireDesktopRuntimeInstancesMutationResultV2,
  requireDesktopRuntimeInstancesCapabilityV2,
  requireDesktopRuntimeInstancesPageV2,
  type DesktopRuntimeInstanceMutationOperationInputV2,
  type DesktopRuntimeInstancesAuthorityOperationInputV2,
  type DesktopRuntimeInstancesListOperationInputV2,
  type DesktopRuntimeInstancesOperationInputV2,
  type PreparedDesktopRuntimeInstancesAuthorityOperationV2,
} from './desktopRuntimeInstancesOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopRuntimeInstanceMutationOperationInputV2,
  DesktopRuntimeInstancesAuthorityOperationInputV2,
  DesktopRuntimeInstancesListOperationInputV2,
  DesktopRuntimeInstancesOperationInputV2,
} from './desktopRuntimeInstancesOperationContractV2';

export const DESKTOP_RUNTIME_INSTANCES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/runtime-instances-authority';
export const DESKTOP_RUNTIME_INSTANCES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.runtime-instances-authority';
export const DESKTOP_RUNTIME_INSTANCES_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopRuntimeInstancesAuthorityV2 {
  readonly list: (
    query: Required<RuntimeInstancesQuery>,
    signal?: AbortSignal,
  ) => Promise<RuntimeInstancesPage>;
  readonly restart: (
    instanceId: string,
    signal?: AbortSignal,
  ) => Promise<void>;
  readonly delete: (instanceId: string, signal?: AbortSignal) => Promise<void>;
  readonly probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}

export interface DesktopRuntimeInstancesAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: RuntimeInstancesScope,
  ) => DesktopRuntimeInstancesAuthorityV2;
}

export interface DesktopRuntimeInstancesOperationsV2 {
  readonly listRuntimeInstances: (
    input: DesktopRuntimeInstancesListOperationInputV2,
  ) => Promise<RuntimeInstancesPage>;
  readonly restartRuntimeInstance: (
    input: DesktopRuntimeInstanceMutationOperationInputV2,
  ) => Promise<void>;
  readonly deleteRuntimeInstance: (
    input: DesktopRuntimeInstanceMutationOperationInputV2,
  ) => Promise<void>;
  readonly probeRuntimeInstances: (
    input: DesktopRuntimeInstancesOperationInputV2,
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
type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

const AUTHORITY_KEYS_V2 = new Set(['list', 'restart', 'delete', 'probe']);

export class DesktopRuntimeInstancesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopRuntimeInstancesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopRuntimeInstancesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_runtime_instances_authority_config_invalid',
      'desktop runtime instances authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopRuntimeInstancesAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopRuntimeInstancesHttpAuthorityV2,
  });
  context.provide(DESKTOP_RUNTIME_INSTANCES_AUTHORITY_SERVICE_V2, service);
}

export const desktopRuntimeInstancesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_RUNTIME_INSTANCES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopRuntimeInstancesAuthorityV2,
});

export function createDesktopRuntimeInstancesOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopRuntimeInstancesOperationsV2 {
  return Object.freeze({
    listRuntimeInstances(input: DesktopRuntimeInstancesListOperationInputV2) {
      const prepared = prepareDesktopRuntimeInstancesAuthorityOperationV2({
        kind: 'list',
        ...input,
      });
      if (prepared.kind !== 'list') throw invalidInputV2();
      return runDesktopRuntimeInstancesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.list(prepared.query, prepared.signal),
      );
    },
    restartRuntimeInstance(input: DesktopRuntimeInstanceMutationOperationInputV2) {
      const prepared = prepareDesktopRuntimeInstancesAuthorityOperationV2({
        kind: 'restart',
        ...input,
      });
      if (prepared.kind !== 'restart') throw invalidInputV2();
      return runDesktopRuntimeInstancesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.restart(prepared.instanceId, prepared.signal),
      );
    },
    deleteRuntimeInstance(input: DesktopRuntimeInstanceMutationOperationInputV2) {
      const prepared = prepareDesktopRuntimeInstancesAuthorityOperationV2({
        kind: 'delete',
        ...input,
      });
      if (prepared.kind !== 'delete') throw invalidInputV2();
      return runDesktopRuntimeInstancesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.delete(prepared.instanceId, prepared.signal),
      );
    },
    probeRuntimeInstances(input: DesktopRuntimeInstancesOperationInputV2) {
      const prepared = prepareDesktopRuntimeInstancesAuthorityOperationV2({
        kind: 'probe',
        ...input,
      });
      return runDesktopRuntimeInstancesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.probe(prepared.signal),
      );
    },
  });
}

export function createDesktopRuntimeInstancesClientV2(
  operations: Pick<
    DesktopRuntimeInstancesOperationsV2,
    'listRuntimeInstances' | 'restartRuntimeInstance' | 'deleteRuntimeInstance'
  >,
  config: DesktopRuntimeConfig,
): RuntimeInstancesClient {
  const operationConfig = cloneDesktopRuntimeInstancesConfigV2(config);
  return Object.freeze({
    list(scope, query, options) {
      return operations.listRuntimeInstances({
        config: operationConfig,
        scope,
        ...(query === undefined ? {} : { query }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    restart(scope, instanceId, options) {
      return operations.restartRuntimeInstance({
        config: operationConfig,
        scope,
        instanceId,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    delete(scope, instanceId, options) {
      return operations.deleteRuntimeInstance({
        config: operationConfig,
        scope,
        instanceId,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopRuntimeInstancesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopRuntimeInstancesAuthorityOperationInputV2,
  operation: (authority: DesktopRuntimeInstancesAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopRuntimeInstancesAuthorityOperationV2(
    actions,
    prepareDesktopRuntimeInstancesAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopRuntimeInstancesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopRuntimeInstancesAuthorityOperationV2,
  operation: (authority: DesktopRuntimeInstancesAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopRuntimeInstancesAuthorityServiceV2>({
      service: DESKTOP_RUNTIME_INSTANCES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_RUNTIME_INSTANCES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopRuntimeInstancesAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireRuntimeInstancesServiceV2(candidate);
      const authority = requireRuntimeInstancesAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableRuntimeInstancesAuthorityV2(
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

function createRevocableRuntimeInstancesAuthorityV2(
  authority: DesktopRuntimeInstancesAuthorityV2,
  scope: RuntimeInstancesScope,
  isOperationActive: () => boolean,
): DesktopRuntimeInstancesAuthorityV2 {
  const active = () => requireOperationActiveV2(isOperationActive);
  return Object.freeze({
    async list(query: Required<RuntimeInstancesQuery>, signal?: AbortSignal) {
      active();
      const result = await authority.list(query, signal);
      active();
      return requireDesktopRuntimeInstancesPageV2(result);
    },
    async restart(instanceId: string, signal?: AbortSignal) {
      active();
      const result = await authority.restart(instanceId, signal);
      active();
      return requireDesktopRuntimeInstancesMutationResultV2(result);
    },
    async delete(instanceId: string, signal?: AbortSignal) {
      active();
      const result = await authority.delete(instanceId, signal);
      active();
      return requireDesktopRuntimeInstancesMutationResultV2(result);
    },
    async probe(signal?: AbortSignal) {
      active();
      const result = await authority.probe(signal);
      active();
      return requireDesktopRuntimeInstancesCapabilityV2(result, scope);
    },
  });
}

function requireRuntimeInstancesServiceV2(
  value: unknown,
): DesktopRuntimeInstancesAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopRuntimeInstancesAuthorityServiceV2;
}

function requireRuntimeInstancesAuthorityV2(value: unknown): DesktopRuntimeInstancesAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    [...AUTHORITY_KEYS_V2].some((key) => typeof value[key] !== 'function')
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopRuntimeInstancesAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopRuntimeInstancesAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_runtime_instances_operation_released',
    'desktop runtime instances operation has been released',
  );
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_instances_operation_input_invalid',
    'desktop runtime instances operation input is invalid',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_instances_service_invalid',
    'desktop runtime instances authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_RUNTIME_INSTANCES_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_runtime_instances_authority_catalog_missing',
      'desktop runtime instances authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
