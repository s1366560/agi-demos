import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { ProjectAdministrationScope } from '../features/project-administration/projectAdministrationClient';
import {
  PROJECT_SCHEMA_LOCAL_REASON,
  type ProjectSchemaClient,
  type ProjectSchemaSnapshot,
} from '../features/project-administration/projectSchemaClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectSchemaHttpAuthorityV2 } from './desktopProjectSchemaHttpProjectionV2';
import {
  prepareDesktopProjectSchemaAuthorityOperationV2,
  requireDesktopProjectSchemaSnapshotV2,
  type DesktopProjectSchemaAuthorityOperationInputV2,
  type DesktopProjectSchemaLoadOperationInputV2,
  type PreparedDesktopProjectSchemaAuthorityOperationV2,
} from './desktopProjectSchemaOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopProjectSchemaAuthorityOperationInputV2,
  DesktopProjectSchemaLoadOperationInputV2,
} from './desktopProjectSchemaOperationContractV2';

export const DESKTOP_PROJECT_SCHEMA_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-schema-authority';
export const DESKTOP_PROJECT_SCHEMA_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-schema-authority';
export const DESKTOP_PROJECT_SCHEMA_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectSchemaAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectSchemaSnapshot>;
}

export interface DesktopProjectSchemaAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectAdministrationScope,
  ) => DesktopProjectSchemaAuthorityV2;
}

export interface DesktopProjectSchemaOperationsV2 {
  readonly loadProjectSchema: (
    input: DesktopProjectSchemaLoadOperationInputV2,
  ) => Promise<ProjectSchemaSnapshot>;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;
type LocalAuthorityUnavailableV2 = Readonly<{
  reasonCode: typeof PROJECT_SCHEMA_LOCAL_REASON;
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2
  | LocalAuthorityUnavailableV2;

const AUTHORITY_KEYS_V2 = new Set(['load']);

export class DesktopProjectSchemaAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;
  readonly status: number;
  readonly payload: Readonly<{ reason_code: string }>;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectSchemaAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
    this.status = rejection.reasonCode === PROJECT_SCHEMA_LOCAL_REASON ? 501 : 503;
    this.payload = Object.freeze({ reason_code: rejection.reasonCode });
  }
}

export function applyDesktopProjectSchemaAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_schema_authority_config_invalid',
      'desktop project schema authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectSchemaAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectSchemaHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_SCHEMA_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectSchemaAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_SCHEMA_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectSchemaAuthorityV2,
});

export function createDesktopProjectSchemaOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectSchemaOperationsV2 {
  return Object.freeze({
    loadProjectSchema(input: DesktopProjectSchemaLoadOperationInputV2) {
      const prepared = prepareDesktopProjectSchemaAuthorityOperationV2({
        kind: 'load',
        ...input,
      });
      rejectLocalOperationV2(prepared);
      return runDesktopProjectSchemaAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function createDesktopProjectSchemaClientV2(
  operations: Pick<DesktopProjectSchemaOperationsV2, 'loadProjectSchema'>,
  config: DesktopRuntimeConfig,
): ProjectSchemaClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(
      scope: Parameters<ProjectSchemaClient['load']>[0],
      options?: Parameters<ProjectSchemaClient['load']>[1],
    ) {
      return operations.loadProjectSchema({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectSchemaAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectSchemaAuthorityOperationInputV2,
  operation: (authority: DesktopProjectSchemaAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectSchemaAuthorityOperationV2(
    actions,
    prepareDesktopProjectSchemaAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopProjectSchemaAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectSchemaAuthorityOperationV2,
  operation: (authority: DesktopProjectSchemaAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  rejectLocalOperationV2(prepared);
  return runCloudDesktopProjectSchemaAuthorityOperationV2(actions, prepared, operation);
}

async function runCloudDesktopProjectSchemaAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectSchemaAuthorityOperationV2,
  operation: (authority: DesktopProjectSchemaAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectSchemaAuthorityServiceV2>({
      service: DESKTOP_PROJECT_SCHEMA_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_SCHEMA_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectSchemaAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectSchemaServiceV2(candidate);
      const authority = requireProjectSchemaAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectSchemaAuthorityV2(authority, prepared.scope, () => operationActive),
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

function rejectLocalOperationV2(prepared: PreparedDesktopProjectSchemaAuthorityOperationV2): void {
  if (prepared.config.mode !== 'local') return;
  throw new DesktopProjectSchemaAuthorityUnavailableErrorV2({
    reasonCode: PROJECT_SCHEMA_LOCAL_REASON,
  });
}

function createRevocableProjectSchemaAuthorityV2(
  authority: DesktopProjectSchemaAuthorityV2,
  scope: ProjectAdministrationScope,
  isOperationActive: () => boolean,
): DesktopProjectSchemaAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectSchemaSnapshotV2(result, scope);
    },
  });
}

function requireProjectSchemaServiceV2(value: unknown): DesktopProjectSchemaAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectSchemaAuthorityServiceV2;
}

function requireProjectSchemaAuthorityV2(value: unknown): DesktopProjectSchemaAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectSchemaAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectSchemaAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_schema_operation_released',
    'desktop project schema operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_schema_service_invalid',
    'desktop project schema authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_SCHEMA_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_schema_authority_catalog_missing',
      'desktop project schema authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
