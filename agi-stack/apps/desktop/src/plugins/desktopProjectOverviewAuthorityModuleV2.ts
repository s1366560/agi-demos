import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  ProjectOverviewClient,
  ProjectOverviewReadResult,
  ProjectOverviewScope,
} from '../features/project/projectOverviewClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';
import {
  requireDesktopProjectOverviewCapabilityV2,
  requireDesktopProjectOverviewResultV2,
} from './desktopProjectOverviewContractV2';
import { createDesktopProjectOverviewHttpAuthorityV2 } from './desktopProjectOverviewHttpProjectionV2';
import {
  cloneDesktopProjectOverviewRuntimeConfigV2,
  prepareDesktopProjectOverviewOperationV2,
  type DesktopProjectOverviewOperationInputV2,
  type PreparedDesktopProjectOverviewOperationV2,
} from './desktopProjectOverviewOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type { DesktopProjectOverviewOperationInputV2 } from './desktopProjectOverviewOperationContractV2';

export const DESKTOP_PROJECT_OVERVIEW_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-overview-authority';
export const DESKTOP_PROJECT_OVERVIEW_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-overview-authority';
export const DESKTOP_PROJECT_OVERVIEW_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectOverviewAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectOverviewReadResult>;
  readonly probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}

export interface DesktopProjectOverviewAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectOverviewScope
  ) => DesktopProjectOverviewAuthorityV2;
}

export interface DesktopProjectOverviewOperationsV2 {
  readonly loadProjectOverview: (
    input: DesktopProjectOverviewOperationInputV2
  ) => Promise<ProjectOverviewReadResult>;
  readonly probeProjectOverview: (
    input: DesktopProjectOverviewOperationInputV2
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

const AUTHORITY_KEYS_V2 = new Set(['load', 'probe']);

export class DesktopProjectOverviewAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectOverviewAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectOverviewAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_overview_authority_config_invalid',
      'desktop project overview authority requires desktop-api-fetch strategy'
    );
  }
  const service: DesktopProjectOverviewAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectOverviewHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_OVERVIEW_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectOverviewAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_OVERVIEW_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectOverviewAuthorityV2,
});

export function createDesktopProjectOverviewOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null
): DesktopProjectOverviewOperationsV2 {
  return Object.freeze({
    loadProjectOverview(input: DesktopProjectOverviewOperationInputV2) {
      const prepared = prepareDesktopProjectOverviewOperationV2(input);
      return runDesktopProjectOverviewAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal)
      );
    },
    probeProjectOverview(input: DesktopProjectOverviewOperationInputV2) {
      const prepared = prepareDesktopProjectOverviewOperationV2(input);
      return runDesktopProjectOverviewAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.probe(prepared.signal)
      );
    },
  });
}

export function createDesktopProjectOverviewClientV2(
  operations: Pick<DesktopProjectOverviewOperationsV2, 'loadProjectOverview'>,
  config: DesktopRuntimeConfig
): ProjectOverviewClient {
  const operationConfig = cloneDesktopProjectOverviewRuntimeConfigV2(config);
  return Object.freeze({
    load(
      scope: Parameters<ProjectOverviewClient['load']>[0],
      options?: Parameters<ProjectOverviewClient['load']>[1]
    ) {
      return operations.loadProjectOverview({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectOverviewAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectOverviewOperationInputV2,
  operation: (authority: DesktopProjectOverviewAuthorityV2) => TResult | Promise<TResult>
): Promise<TResult> {
  return runDesktopProjectOverviewAuthorityOperationV2(
    actions,
    prepareDesktopProjectOverviewOperationV2(input),
    operation
  );
}

async function runDesktopProjectOverviewAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectOverviewOperationV2,
  operation: (authority: DesktopProjectOverviewAuthorityV2) => TResult | Promise<TResult>
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectOverviewAuthorityServiceV2>({
      service: DESKTOP_PROJECT_OVERVIEW_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_OVERVIEW_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectOverviewAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectOverviewServiceV2(candidate);
      const authority = requireProjectOverviewAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope)
      );
      return operation(
        createRevocableProjectOverviewAuthorityV2(authority, prepared.scope, () => operationActive)
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

function createRevocableProjectOverviewAuthorityV2(
  authority: DesktopProjectOverviewAuthorityV2,
  scope: ProjectOverviewScope,
  isOperationActive: () => boolean
): DesktopProjectOverviewAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectOverviewResultV2(result, scope);
    },
    async probe(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.probe(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectOverviewCapabilityV2(result, scope);
    },
  });
}

function requireProjectOverviewServiceV2(value: unknown): DesktopProjectOverviewAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectOverviewAuthorityServiceV2;
}

function requireProjectOverviewAuthorityV2(value: unknown): DesktopProjectOverviewAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function' ||
    typeof value.probe !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectOverviewAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectOverviewAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_overview_operation_released',
    'desktop project overview operation has been released'
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_overview_service_invalid',
    'desktop project overview authority service is invalid'
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_OVERVIEW_AUTHORITY_MODULE_REF_V2
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_overview_authority_catalog_missing',
      'desktop project overview authority is absent from the generated catalog'
    );
  }
  return entry.contract_digest;
}
