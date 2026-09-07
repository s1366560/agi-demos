import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  ProjectTeamClient,
  ProjectTeamSnapshot,
} from '../features/project-knowledge/projectTeamClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectTeamHttpAuthorityV2 } from './desktopProjectTeamHttpProjectionV2';
import {
  prepareDesktopProjectTeamAuthorityOperationV2,
  requireDesktopProjectTeamSnapshotV2,
  type DesktopProjectTeamAuthorityOperationInputV2,
  type DesktopProjectTeamLoadOperationInputV2,
  type PreparedDesktopProjectTeamAuthorityOperationV2,
} from './desktopProjectTeamOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopProjectTeamAuthorityOperationInputV2,
  DesktopProjectTeamLoadOperationInputV2,
} from './desktopProjectTeamOperationContractV2';

export const DESKTOP_PROJECT_TEAM_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-team-authority';
export const DESKTOP_PROJECT_TEAM_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-team-authority';
export const DESKTOP_PROJECT_TEAM_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectTeamAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectTeamSnapshot>;
}

export interface DesktopProjectTeamAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectKnowledgeScope,
  ) => DesktopProjectTeamAuthorityV2;
}

export interface DesktopProjectTeamOperationsV2 {
  readonly loadProjectTeam: (
    input: DesktopProjectTeamLoadOperationInputV2,
  ) => Promise<ProjectTeamSnapshot>;
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

const AUTHORITY_KEYS_V2 = new Set(['load']);

export class DesktopProjectTeamAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectTeamAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectTeamAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_team_authority_config_invalid',
      'desktop project team authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectTeamAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectTeamHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_TEAM_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectTeamAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_TEAM_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectTeamAuthorityV2,
});

export function createDesktopProjectTeamOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectTeamOperationsV2 {
  return Object.freeze({
    loadProjectTeam(input: DesktopProjectTeamLoadOperationInputV2) {
      const prepared = prepareDesktopProjectTeamAuthorityOperationV2({
        kind: 'load',
        ...input,
      });
      return runDesktopProjectTeamAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function createDesktopProjectTeamClientV2(
  operations: Pick<DesktopProjectTeamOperationsV2, 'loadProjectTeam'>,
  config: DesktopRuntimeConfig,
): ProjectTeamClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(
      scope: Parameters<ProjectTeamClient['load']>[0],
      options?: Parameters<ProjectTeamClient['load']>[1],
    ) {
      return operations.loadProjectTeam({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectTeamAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectTeamAuthorityOperationInputV2,
  operation: (authority: DesktopProjectTeamAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectTeamAuthorityOperationV2(
    actions,
    prepareDesktopProjectTeamAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopProjectTeamAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectTeamAuthorityOperationV2,
  operation: (authority: DesktopProjectTeamAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectTeamAuthorityServiceV2>({
      service: DESKTOP_PROJECT_TEAM_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_TEAM_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectTeamAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectTeamServiceV2(candidate);
      const authority = requireProjectTeamAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectTeamAuthorityV2(authority, prepared.scope, () => operationActive),
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

function createRevocableProjectTeamAuthorityV2(
  authority: DesktopProjectTeamAuthorityV2,
  scope: ProjectKnowledgeScope,
  isOperationActive: () => boolean,
): DesktopProjectTeamAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectTeamSnapshotV2(result, scope);
    },
  });
}

function requireProjectTeamServiceV2(value: unknown): DesktopProjectTeamAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectTeamAuthorityServiceV2;
}

function requireProjectTeamAuthorityV2(value: unknown): DesktopProjectTeamAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectTeamAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectTeamAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_team_operation_released',
    'desktop project team operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_team_service_invalid',
    'desktop project team authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_TEAM_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_team_authority_catalog_missing',
      'desktop project team authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
