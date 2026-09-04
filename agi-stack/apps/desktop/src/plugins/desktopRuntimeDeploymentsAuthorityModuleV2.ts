import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  RuntimeDeployment,
  RuntimeDeploymentProgressEvent,
  RuntimeDeploymentsClient,
  RuntimeDeploymentsPage,
  RuntimeDeploymentsQuery,
  RuntimeDeploymentsScope,
} from '../features/runtime-deployments/runtimeDeploymentsTypes';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopRuntimeDeploymentsHttpAuthorityV2 } from './desktopRuntimeDeploymentsHttpProjectionV2';
import {
  cloneDesktopRuntimeDeploymentsConfigV2,
  prepareDesktopRuntimeDeploymentsAuthorityOperationV2,
  requireDesktopRuntimeDeploymentProgressEventV2,
  requireDesktopRuntimeDeploymentV2,
  requireDesktopRuntimeDeploymentsCapabilityV2,
  requireDesktopRuntimeDeploymentsPageV2,
  requireDesktopRuntimeDeploymentsStreamResultV2,
  type DesktopRuntimeDeploymentGetOperationInputV2,
  type DesktopRuntimeDeploymentsAuthorityOperationInputV2,
  type DesktopRuntimeDeploymentsListOperationInputV2,
  type DesktopRuntimeDeploymentsOperationInputV2,
  type DesktopRuntimeDeploymentStreamOperationInputV2,
  type PreparedDesktopRuntimeDeploymentsAuthorityOperationV2,
} from './desktopRuntimeDeploymentsOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopRuntimeDeploymentGetOperationInputV2,
  DesktopRuntimeDeploymentsAuthorityOperationInputV2,
  DesktopRuntimeDeploymentsListOperationInputV2,
  DesktopRuntimeDeploymentsOperationInputV2,
  DesktopRuntimeDeploymentStreamOperationInputV2,
} from './desktopRuntimeDeploymentsOperationContractV2';

export const DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/runtime-deployments-authority';
export const DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.runtime-deployments-authority';
export const DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopRuntimeDeploymentsAuthorityV2 {
  readonly list: (
    query: Required<RuntimeDeploymentsQuery>,
    signal?: AbortSignal,
  ) => Promise<RuntimeDeploymentsPage>;
  readonly get: (deploymentId: string, signal?: AbortSignal) => Promise<RuntimeDeployment>;
  readonly streamProgress: (
    deploymentId: string,
    onEvent: (
      event: RuntimeDeploymentProgressEvent,
    ) => void | Promise<void>,
    signal?: AbortSignal,
  ) => Promise<void>;
  readonly probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}

export interface DesktopRuntimeDeploymentsAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: RuntimeDeploymentsScope,
  ) => DesktopRuntimeDeploymentsAuthorityV2;
}

export interface DesktopRuntimeDeploymentsOperationsV2 {
  readonly listRuntimeDeployments: (
    input: DesktopRuntimeDeploymentsListOperationInputV2,
  ) => Promise<RuntimeDeploymentsPage>;
  readonly getRuntimeDeployment: (
    input: DesktopRuntimeDeploymentGetOperationInputV2,
  ) => Promise<RuntimeDeployment>;
  readonly streamRuntimeDeploymentProgress: (
    input: DesktopRuntimeDeploymentStreamOperationInputV2,
  ) => Promise<void>;
  readonly probeRuntimeDeployments: (
    input: DesktopRuntimeDeploymentsOperationInputV2,
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

const AUTHORITY_KEYS_V2 = new Set(['list', 'get', 'streamProgress', 'probe']);

export class DesktopRuntimeDeploymentsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopRuntimeDeploymentsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopRuntimeDeploymentsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_runtime_deployments_authority_config_invalid',
      'desktop runtime deployments authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopRuntimeDeploymentsAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopRuntimeDeploymentsHttpAuthorityV2,
  });
  context.provide(DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2, service);
}

export const desktopRuntimeDeploymentsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopRuntimeDeploymentsAuthorityV2,
});

export function createDesktopRuntimeDeploymentsOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopRuntimeDeploymentsOperationsV2 {
  return Object.freeze({
    listRuntimeDeployments(input: DesktopRuntimeDeploymentsListOperationInputV2) {
      const prepared = prepareDesktopRuntimeDeploymentsAuthorityOperationV2({
        kind: 'list',
        ...input,
      });
      if (prepared.kind !== 'list') throw invalidInputV2();
      return runDesktopRuntimeDeploymentsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.list(prepared.query, prepared.signal),
      );
    },
    getRuntimeDeployment(input: DesktopRuntimeDeploymentGetOperationInputV2) {
      const prepared = prepareDesktopRuntimeDeploymentsAuthorityOperationV2({
        kind: 'get',
        ...input,
      });
      if (prepared.kind !== 'get') throw invalidInputV2();
      return runDesktopRuntimeDeploymentsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.get(prepared.deploymentId, prepared.signal),
      );
    },
    streamRuntimeDeploymentProgress(input: DesktopRuntimeDeploymentStreamOperationInputV2) {
      const prepared = prepareDesktopRuntimeDeploymentsAuthorityOperationV2({
        kind: 'streamProgress',
        ...input,
      });
      if (prepared.kind !== 'streamProgress') throw invalidInputV2();
      return runDesktopRuntimeDeploymentsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.streamProgress(
            prepared.deploymentId,
            prepared.onEvent,
            prepared.signal,
          ),
      );
    },
    probeRuntimeDeployments(input: DesktopRuntimeDeploymentsOperationInputV2) {
      const prepared = prepareDesktopRuntimeDeploymentsAuthorityOperationV2({
        kind: 'probe',
        ...input,
      });
      return runDesktopRuntimeDeploymentsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.probe(prepared.signal),
      );
    },
  });
}

export function createDesktopRuntimeDeploymentsClientV2(
  operations: Pick<
    DesktopRuntimeDeploymentsOperationsV2,
    | 'listRuntimeDeployments'
    | 'getRuntimeDeployment'
    | 'streamRuntimeDeploymentProgress'
  >,
  config: DesktopRuntimeConfig,
): RuntimeDeploymentsClient {
  const operationConfig = cloneDesktopRuntimeDeploymentsConfigV2(config);
  return Object.freeze({
    list(scope, query, options) {
      return operations.listRuntimeDeployments({
        config: operationConfig,
        scope,
        ...(query === undefined ? {} : { query }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    get(scope, deploymentId, options) {
      return operations.getRuntimeDeployment({
        config: operationConfig,
        scope,
        deploymentId,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    streamProgress(scope, deploymentId, onEvent, options) {
      return operations.streamRuntimeDeploymentProgress({
        config: operationConfig,
        scope,
        deploymentId,
        onEvent,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopRuntimeDeploymentsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopRuntimeDeploymentsAuthorityOperationInputV2,
  operation: (authority: DesktopRuntimeDeploymentsAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopRuntimeDeploymentsAuthorityOperationV2(
    actions,
    prepareDesktopRuntimeDeploymentsAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopRuntimeDeploymentsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopRuntimeDeploymentsAuthorityOperationV2,
  operation: (authority: DesktopRuntimeDeploymentsAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopRuntimeDeploymentsAuthorityServiceV2>({
      service: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopRuntimeDeploymentsAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireRuntimeDeploymentsServiceV2(candidate);
      const authority = requireRuntimeDeploymentsAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableRuntimeDeploymentsAuthorityV2(
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

function createRevocableRuntimeDeploymentsAuthorityV2(
  authority: DesktopRuntimeDeploymentsAuthorityV2,
  scope: RuntimeDeploymentsScope,
  isOperationActive: () => boolean,
): DesktopRuntimeDeploymentsAuthorityV2 {
  const active = () => requireOperationActiveV2(isOperationActive);
  return Object.freeze({
    async list(query: Required<RuntimeDeploymentsQuery>, signal?: AbortSignal) {
      active();
      const result = await authority.list(query, signal);
      active();
      return requireDesktopRuntimeDeploymentsPageV2(result, scope);
    },
    async get(deploymentId: string, signal?: AbortSignal) {
      active();
      const result = await authority.get(deploymentId, signal);
      active();
      return requireDesktopRuntimeDeploymentV2(result, scope);
    },
    async streamProgress(
      deploymentId: string,
      onEvent: (
        event: RuntimeDeploymentProgressEvent,
      ) => void | Promise<void>,
      signal?: AbortSignal,
    ) {
      active();
      const result = await authority.streamProgress(
        deploymentId,
        async (event) => {
          active();
          const validated = requireDesktopRuntimeDeploymentProgressEventV2(
            event,
            deploymentId,
          );
          await onEvent(validated);
          active();
        },
        signal,
      );
      active();
      return requireDesktopRuntimeDeploymentsStreamResultV2(result);
    },
    async probe(signal?: AbortSignal) {
      active();
      const result = await authority.probe(signal);
      active();
      return requireDesktopRuntimeDeploymentsCapabilityV2(result, scope);
    },
  });
}

function requireRuntimeDeploymentsServiceV2(
  value: unknown,
): DesktopRuntimeDeploymentsAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopRuntimeDeploymentsAuthorityServiceV2;
}

function requireRuntimeDeploymentsAuthorityV2(
  value: unknown,
): DesktopRuntimeDeploymentsAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    [...AUTHORITY_KEYS_V2].some((key) => typeof value[key] !== 'function')
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopRuntimeDeploymentsAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopRuntimeDeploymentsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_runtime_deployments_operation_released',
    'desktop runtime deployments operation has been released',
  );
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_deployments_operation_input_invalid',
    'desktop runtime deployments operation input is invalid',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_runtime_deployments_service_invalid',
    'desktop runtime deployments authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_RUNTIME_DEPLOYMENTS_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_runtime_deployments_authority_catalog_missing',
      'desktop runtime deployments authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
