import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  ProjectGraphClient,
  ProjectGraphSnapshot,
} from '../features/project-knowledge/projectGraphClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectGraphHttpAuthorityV2 } from './desktopProjectGraphHttpProjectionV2';
import {
  cloneDesktopProjectGraphRuntimeConfigV2,
  prepareDesktopProjectGraphOperationV2,
  requireDesktopProjectGraphSnapshotV2,
  type DesktopProjectGraphOperationInputV2,
  type PreparedDesktopProjectGraphOperationV2,
} from './desktopProjectGraphOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type { DesktopProjectGraphOperationInputV2 } from './desktopProjectGraphOperationContractV2';

export const DESKTOP_PROJECT_GRAPH_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-graph-authority';
export const DESKTOP_PROJECT_GRAPH_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-graph-authority';
export const DESKTOP_PROJECT_GRAPH_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectGraphAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectGraphSnapshot>;
}

export interface DesktopProjectGraphAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectKnowledgeScope,
  ) => DesktopProjectGraphAuthorityV2;
}

export interface DesktopProjectGraphOperationsV2 {
  readonly loadProjectGraph: (
    input: DesktopProjectGraphOperationInputV2,
  ) => Promise<ProjectGraphSnapshot>;
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

const AUTHORITY_KEYS_V2 = new Set(['load']);

export class DesktopProjectGraphAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectGraphAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectGraphAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_graph_authority_config_invalid',
      'desktop project graph authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectGraphAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectGraphHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_GRAPH_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectGraphAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_GRAPH_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectGraphAuthorityV2,
});

export function createDesktopProjectGraphOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectGraphOperationsV2 {
  return Object.freeze({
    loadProjectGraph(input: DesktopProjectGraphOperationInputV2) {
      const prepared = prepareDesktopProjectGraphOperationV2(input);
      return runDesktopProjectGraphAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function createDesktopProjectGraphClientV2(
  operations: Pick<DesktopProjectGraphOperationsV2, 'loadProjectGraph'>,
  config: DesktopRuntimeConfig,
): ProjectGraphClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(
      scope: Parameters<ProjectGraphClient['load']>[0],
      options?: Parameters<ProjectGraphClient['load']>[1],
    ) {
      return operations.loadProjectGraph({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectGraphAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectGraphOperationInputV2,
  operation: (authority: DesktopProjectGraphAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectGraphAuthorityOperationV2(
    actions,
    prepareDesktopProjectGraphOperationV2(input),
    operation,
  );
}

async function runDesktopProjectGraphAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectGraphOperationV2,
  operation: (authority: DesktopProjectGraphAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectGraphAuthorityServiceV2>({
      service: DESKTOP_PROJECT_GRAPH_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_GRAPH_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectGraphAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectGraphServiceV2(candidate);
      const authority = requireProjectGraphAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectGraphAuthorityV2(
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

function createRevocableProjectGraphAuthorityV2(
  authority: DesktopProjectGraphAuthorityV2,
  scope: ProjectKnowledgeScope,
  isOperationActive: () => boolean,
): DesktopProjectGraphAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectGraphSnapshotV2(result, scope);
    },
  });
}

function requireProjectGraphServiceV2(
  value: unknown,
): DesktopProjectGraphAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectGraphAuthorityServiceV2;
}

function requireProjectGraphAuthorityV2(value: unknown): DesktopProjectGraphAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectGraphAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectGraphAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_graph_operation_released',
    'desktop project graph operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_graph_service_invalid',
    'desktop project graph authority service is invalid',
  );
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_GRAPH_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_graph_authority_catalog_missing',
      'desktop project graph authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
