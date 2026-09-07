import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  ProjectEntitiesClient,
  ProjectEntitiesSnapshot,
  ProjectEntityRelationship,
} from '../features/project-knowledge/projectEntitiesClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectEntitiesHttpAuthorityV2 } from './desktopProjectEntitiesHttpProjectionV2';
import {
  prepareDesktopProjectEntitiesAuthorityOperationV2,
  requireDesktopProjectEntitiesSnapshotV2,
  requireDesktopProjectEntityRelationshipsV2,
  type DesktopProjectEntitiesAuthorityOperationInputV2,
  type DesktopProjectEntitiesLoadOperationInputV2,
  type DesktopProjectEntityRelationshipsOperationInputV2,
  type PreparedDesktopProjectEntitiesAuthorityOperationV2,
} from './desktopProjectEntitiesOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopProjectEntitiesAuthorityOperationInputV2,
  DesktopProjectEntitiesLoadOperationInputV2,
  DesktopProjectEntityRelationshipsOperationInputV2,
} from './desktopProjectEntitiesOperationContractV2';

export const DESKTOP_PROJECT_ENTITIES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-entities-authority';
export const DESKTOP_PROJECT_ENTITIES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-entities-authority';
export const DESKTOP_PROJECT_ENTITIES_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectEntitiesAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectEntitiesSnapshot>;
  readonly relationships: (
    entityId: string,
    signal?: AbortSignal,
  ) => Promise<readonly ProjectEntityRelationship[]>;
}

export interface DesktopProjectEntitiesAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectKnowledgeScope,
  ) => DesktopProjectEntitiesAuthorityV2;
}

export interface DesktopProjectEntitiesOperationsV2 {
  readonly loadProjectEntities: (
    input: DesktopProjectEntitiesLoadOperationInputV2,
  ) => Promise<ProjectEntitiesSnapshot>;
  readonly loadProjectEntityRelationships: (
    input: DesktopProjectEntityRelationshipsOperationInputV2,
  ) => Promise<readonly ProjectEntityRelationship[]>;
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

const AUTHORITY_KEYS_V2 = new Set(['load', 'relationships']);

export class DesktopProjectEntitiesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectEntitiesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectEntitiesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_entities_authority_config_invalid',
      'desktop project entities authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectEntitiesAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectEntitiesHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_ENTITIES_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectEntitiesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_ENTITIES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectEntitiesAuthorityV2,
});

export function createDesktopProjectEntitiesOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectEntitiesOperationsV2 {
  return Object.freeze({
    loadProjectEntities(input: DesktopProjectEntitiesLoadOperationInputV2) {
      const prepared = prepareDesktopProjectEntitiesAuthorityOperationV2({
        kind: 'load',
        ...input,
      });
      return runDesktopProjectEntitiesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
    loadProjectEntityRelationships(
      input: DesktopProjectEntityRelationshipsOperationInputV2,
    ) {
      const prepared = prepareDesktopProjectEntitiesAuthorityOperationV2({
        kind: 'relationships',
        ...input,
      });
      if (prepared.kind !== 'relationships') {
        throw new RuntimeV2Error(
          'desktop_project_entities_operation_input_invalid',
          'desktop project entities operation input is invalid',
        );
      }
      return runDesktopProjectEntitiesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.relationships(prepared.entityId, prepared.signal),
      );
    },
  });
}

export function createDesktopProjectEntitiesClientV2(
  operations: Pick<
    DesktopProjectEntitiesOperationsV2,
    'loadProjectEntities' | 'loadProjectEntityRelationships'
  >,
  config: DesktopRuntimeConfig,
): ProjectEntitiesClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(
      scope: Parameters<ProjectEntitiesClient['load']>[0],
      options?: Parameters<ProjectEntitiesClient['load']>[1],
    ) {
      return operations.loadProjectEntities({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    relationships(
      scope: Parameters<ProjectEntitiesClient['relationships']>[0],
      entityId: Parameters<ProjectEntitiesClient['relationships']>[1],
      options?: Parameters<ProjectEntitiesClient['relationships']>[2],
    ) {
      return operations.loadProjectEntityRelationships({
        config: operationConfig,
        scope,
        entityId,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectEntitiesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectEntitiesAuthorityOperationInputV2,
  operation: (authority: DesktopProjectEntitiesAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectEntitiesAuthorityOperationV2(
    actions,
    prepareDesktopProjectEntitiesAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopProjectEntitiesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectEntitiesAuthorityOperationV2,
  operation: (authority: DesktopProjectEntitiesAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectEntitiesAuthorityServiceV2>({
      service: DESKTOP_PROJECT_ENTITIES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_ENTITIES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectEntitiesAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectEntitiesServiceV2(candidate);
      const authority = requireProjectEntitiesAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectEntitiesAuthorityV2(
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

function createRevocableProjectEntitiesAuthorityV2(
  authority: DesktopProjectEntitiesAuthorityV2,
  scope: ProjectKnowledgeScope,
  isOperationActive: () => boolean,
): DesktopProjectEntitiesAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectEntitiesSnapshotV2(result, scope);
    },
    async relationships(entityId: string, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.relationships(entityId, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectEntityRelationshipsV2(result, scope);
    },
  });
}

function requireProjectEntitiesServiceV2(
  value: unknown,
): DesktopProjectEntitiesAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectEntitiesAuthorityServiceV2;
}

function requireProjectEntitiesAuthorityV2(
  value: unknown,
): DesktopProjectEntitiesAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function' ||
    typeof value.relationships !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectEntitiesAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectEntitiesAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_entities_operation_released',
    'desktop project entities operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_entities_service_invalid',
    'desktop project entities authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_ENTITIES_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_entities_authority_catalog_missing',
      'desktop project entities authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
