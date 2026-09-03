import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  ProjectCommunitiesClient,
  ProjectCommunitiesSnapshot,
} from '../features/project-knowledge/projectCommunitiesClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectCommunitiesHttpAuthorityV2 } from './desktopProjectCommunitiesHttpProjectionV2';
import {
  prepareDesktopProjectCommunitiesAuthorityOperationV2,
  requireDesktopProjectCommunitiesSnapshotV2,
  type DesktopProjectCommunitiesAuthorityOperationInputV2,
  type DesktopProjectCommunitiesLoadOperationInputV2,
  type PreparedDesktopProjectCommunitiesAuthorityOperationV2,
} from './desktopProjectCommunitiesOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopProjectCommunitiesAuthorityOperationInputV2,
  DesktopProjectCommunitiesLoadOperationInputV2,
} from './desktopProjectCommunitiesOperationContractV2';

export const DESKTOP_PROJECT_COMMUNITIES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-communities-authority';
export const DESKTOP_PROJECT_COMMUNITIES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-communities-authority';
export const DESKTOP_PROJECT_COMMUNITIES_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectCommunitiesAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectCommunitiesSnapshot>;
}

export interface DesktopProjectCommunitiesAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectKnowledgeScope,
  ) => DesktopProjectCommunitiesAuthorityV2;
}

export interface DesktopProjectCommunitiesOperationsV2 {
  readonly loadProjectCommunities: (
    input: DesktopProjectCommunitiesLoadOperationInputV2,
  ) => Promise<ProjectCommunitiesSnapshot>;
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

export class DesktopProjectCommunitiesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectCommunitiesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectCommunitiesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_communities_authority_config_invalid',
      'desktop project communities authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectCommunitiesAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectCommunitiesHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_COMMUNITIES_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectCommunitiesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_COMMUNITIES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectCommunitiesAuthorityV2,
});

export function createDesktopProjectCommunitiesOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectCommunitiesOperationsV2 {
  return Object.freeze({
    loadProjectCommunities(input: DesktopProjectCommunitiesLoadOperationInputV2) {
      const prepared = prepareDesktopProjectCommunitiesAuthorityOperationV2({
        kind: 'load',
        ...input,
      });
      return runDesktopProjectCommunitiesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function createDesktopProjectCommunitiesClientV2(
  operations: Pick<DesktopProjectCommunitiesOperationsV2, 'loadProjectCommunities'>,
  config: DesktopRuntimeConfig,
): ProjectCommunitiesClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(
      scope: Parameters<ProjectCommunitiesClient['load']>[0],
      options?: Parameters<ProjectCommunitiesClient['load']>[1],
    ) {
      return operations.loadProjectCommunities({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectCommunitiesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectCommunitiesAuthorityOperationInputV2,
  operation: (authority: DesktopProjectCommunitiesAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectCommunitiesAuthorityOperationV2(
    actions,
    prepareDesktopProjectCommunitiesAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopProjectCommunitiesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectCommunitiesAuthorityOperationV2,
  operation: (authority: DesktopProjectCommunitiesAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectCommunitiesAuthorityServiceV2>({
      service: DESKTOP_PROJECT_COMMUNITIES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_COMMUNITIES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectCommunitiesAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectCommunitiesServiceV2(candidate);
      const authority = requireProjectCommunitiesAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectCommunitiesAuthorityV2(
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

function createRevocableProjectCommunitiesAuthorityV2(
  authority: DesktopProjectCommunitiesAuthorityV2,
  scope: ProjectKnowledgeScope,
  isOperationActive: () => boolean,
): DesktopProjectCommunitiesAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectCommunitiesSnapshotV2(result, scope);
    },
  });
}

function requireProjectCommunitiesServiceV2(
  value: unknown,
): DesktopProjectCommunitiesAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectCommunitiesAuthorityServiceV2;
}

function requireProjectCommunitiesAuthorityV2(
  value: unknown,
): DesktopProjectCommunitiesAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectCommunitiesAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectCommunitiesAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_communities_operation_released',
    'desktop project communities operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_communities_service_invalid',
    'desktop project communities authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_COMMUNITIES_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_communities_authority_catalog_missing',
      'desktop project communities authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
