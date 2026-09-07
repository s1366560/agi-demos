import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  ProjectAdministrationScope,
} from '../features/project-administration/projectAdministrationClient';
import {
  PROJECT_MAINTENANCE_LOCAL_REASON,
  type ProjectMaintenanceClient,
  type ProjectMaintenanceSnapshot,
} from '../features/project-administration/projectMaintenanceClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  createDesktopProjectMaintenanceHttpAuthorityV2,
} from './desktopProjectMaintenanceHttpProjectionV2';
import {
  prepareDesktopProjectMaintenanceAuthorityOperationV2,
  requireDesktopProjectMaintenanceSnapshotV2,
  type DesktopProjectMaintenanceAuthorityOperationInputV2,
  type DesktopProjectMaintenanceLoadOperationInputV2,
  type PreparedDesktopProjectMaintenanceAuthorityOperationV2,
} from './desktopProjectMaintenanceOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopProjectMaintenanceAuthorityOperationInputV2,
  DesktopProjectMaintenanceLoadOperationInputV2,
} from './desktopProjectMaintenanceOperationContractV2';

export const DESKTOP_PROJECT_MAINTENANCE_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-maintenance-authority';
export const DESKTOP_PROJECT_MAINTENANCE_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-maintenance-authority';
export const DESKTOP_PROJECT_MAINTENANCE_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectMaintenanceAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectMaintenanceSnapshot>;
}

export interface DesktopProjectMaintenanceAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectAdministrationScope,
  ) => DesktopProjectMaintenanceAuthorityV2;
}

export interface DesktopProjectMaintenanceOperationsV2 {
  readonly loadProjectMaintenance: (
    input: DesktopProjectMaintenanceLoadOperationInputV2,
  ) => Promise<ProjectMaintenanceSnapshot>;
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
  reasonCode: typeof PROJECT_MAINTENANCE_LOCAL_REASON;
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2
  | LocalAuthorityUnavailableV2;

const AUTHORITY_KEYS_V2 = new Set(['load']);

export class DesktopProjectMaintenanceAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;
  readonly status: number;
  readonly payload: Readonly<{ reason_code: string }>;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectMaintenanceAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
    this.status = rejection.reasonCode === PROJECT_MAINTENANCE_LOCAL_REASON ? 501 : 503;
    this.payload = Object.freeze({ reason_code: rejection.reasonCode });
  }
}

export function applyDesktopProjectMaintenanceAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_maintenance_authority_config_invalid',
      'desktop project maintenance authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectMaintenanceAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectMaintenanceHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_MAINTENANCE_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectMaintenanceAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_MAINTENANCE_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectMaintenanceAuthorityV2,
});

export function createDesktopProjectMaintenanceOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectMaintenanceOperationsV2 {
  return Object.freeze({
    loadProjectMaintenance(input: DesktopProjectMaintenanceLoadOperationInputV2) {
      const prepared = prepareDesktopProjectMaintenanceAuthorityOperationV2({
        kind: 'load',
        ...input,
      });
      rejectLocalOperationV2(prepared);
      return runDesktopProjectMaintenanceAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function createDesktopProjectMaintenanceClientV2(
  operations: Pick<DesktopProjectMaintenanceOperationsV2, 'loadProjectMaintenance'>,
  config: DesktopRuntimeConfig,
): ProjectMaintenanceClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(
      scope: Parameters<ProjectMaintenanceClient['load']>[0],
      options?: Parameters<ProjectMaintenanceClient['load']>[1],
    ) {
      return operations.loadProjectMaintenance({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectMaintenanceAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectMaintenanceAuthorityOperationInputV2,
  operation: (authority: DesktopProjectMaintenanceAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectMaintenanceAuthorityOperationV2(
    actions,
    prepareDesktopProjectMaintenanceAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopProjectMaintenanceAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectMaintenanceAuthorityOperationV2,
  operation: (authority: DesktopProjectMaintenanceAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  rejectLocalOperationV2(prepared);
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectMaintenanceAuthorityServiceV2>({
      service: DESKTOP_PROJECT_MAINTENANCE_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_MAINTENANCE_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectMaintenanceAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectMaintenanceServiceV2(candidate);
      const authority = requireProjectMaintenanceAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectMaintenanceAuthorityV2(
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

function rejectLocalOperationV2(
  prepared: PreparedDesktopProjectMaintenanceAuthorityOperationV2,
): void {
  if (prepared.config.mode !== 'local') return;
  throw new DesktopProjectMaintenanceAuthorityUnavailableErrorV2({
    reasonCode: PROJECT_MAINTENANCE_LOCAL_REASON,
  });
}

function createRevocableProjectMaintenanceAuthorityV2(
  authority: DesktopProjectMaintenanceAuthorityV2,
  scope: ProjectAdministrationScope,
  isOperationActive: () => boolean,
): DesktopProjectMaintenanceAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectMaintenanceSnapshotV2(result, scope);
    },
  });
}

function requireProjectMaintenanceServiceV2(
  value: unknown,
): DesktopProjectMaintenanceAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectMaintenanceAuthorityServiceV2;
}

function requireProjectMaintenanceAuthorityV2(
  value: unknown,
): DesktopProjectMaintenanceAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectMaintenanceAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectMaintenanceAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_maintenance_operation_released',
    'desktop project maintenance operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_maintenance_service_invalid',
    'desktop project maintenance authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_MAINTENANCE_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_maintenance_authority_catalog_missing',
      'desktop project maintenance authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
