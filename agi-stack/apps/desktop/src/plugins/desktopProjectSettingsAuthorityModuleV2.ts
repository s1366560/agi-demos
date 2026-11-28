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
  PROJECT_SETTINGS_LOCAL_REASON,
  type ProjectSettingsClient,
  type ProjectSettingsSnapshot,
} from '../features/project-administration/projectSettingsClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  createDesktopProjectSettingsHttpAuthorityV2,
} from './desktopProjectSettingsHttpProjectionV2';
import {
  prepareDesktopProjectSettingsAuthorityOperationV2,
  requireDesktopProjectSettingsSnapshotV2,
  type DesktopProjectSettingsAuthorityOperationInputV2,
  type DesktopProjectSettingsLoadOperationInputV2,
  type PreparedDesktopProjectSettingsAuthorityOperationV2,
} from './desktopProjectSettingsOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopProjectSettingsAuthorityOperationInputV2,
  DesktopProjectSettingsLoadOperationInputV2,
} from './desktopProjectSettingsOperationContractV2';

export const DESKTOP_PROJECT_SETTINGS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-settings-authority';
export const DESKTOP_PROJECT_SETTINGS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-settings-authority';
export const DESKTOP_PROJECT_SETTINGS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectSettingsAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectSettingsSnapshot>;
}

export interface DesktopProjectSettingsAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectAdministrationScope,
  ) => DesktopProjectSettingsAuthorityV2;
}

export interface DesktopProjectSettingsOperationsV2 {
  readonly loadProjectSettings: (
    input: DesktopProjectSettingsLoadOperationInputV2,
  ) => Promise<ProjectSettingsSnapshot>;
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
  reasonCode: typeof PROJECT_SETTINGS_LOCAL_REASON;
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2
  | LocalAuthorityUnavailableV2;

const AUTHORITY_KEYS_V2 = new Set(['load']);

export class DesktopProjectSettingsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;
  readonly status: number;
  readonly payload: Readonly<{ reason_code: string }>;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectSettingsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
    this.status = rejection.reasonCode === PROJECT_SETTINGS_LOCAL_REASON ? 501 : 503;
    this.payload = Object.freeze({ reason_code: rejection.reasonCode });
  }
}

export function applyDesktopProjectSettingsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_settings_authority_config_invalid',
      'desktop project settings authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectSettingsAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectSettingsHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_SETTINGS_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectSettingsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_SETTINGS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectSettingsAuthorityV2,
});

export function createDesktopProjectSettingsOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectSettingsOperationsV2 {
  return Object.freeze({
    loadProjectSettings(input: DesktopProjectSettingsLoadOperationInputV2) {
      const prepared = prepareDesktopProjectSettingsAuthorityOperationV2({
        kind: 'load',
        ...input,
      });
      rejectLocalOperationV2(prepared);
      return runDesktopProjectSettingsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function createDesktopProjectSettingsClientV2(
  operations: Pick<DesktopProjectSettingsOperationsV2, 'loadProjectSettings'>,
  config: DesktopRuntimeConfig,
): ProjectSettingsClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(
      scope: Parameters<ProjectSettingsClient['load']>[0],
      options?: Parameters<ProjectSettingsClient['load']>[1],
    ) {
      return operations.loadProjectSettings({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectSettingsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectSettingsAuthorityOperationInputV2,
  operation: (authority: DesktopProjectSettingsAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectSettingsAuthorityOperationV2(
    actions,
    prepareDesktopProjectSettingsAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopProjectSettingsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectSettingsAuthorityOperationV2,
  operation: (authority: DesktopProjectSettingsAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  rejectLocalOperationV2(prepared);
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectSettingsAuthorityServiceV2>({
      service: DESKTOP_PROJECT_SETTINGS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_SETTINGS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectSettingsAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectSettingsServiceV2(candidate);
      const authority = requireProjectSettingsAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectSettingsAuthorityV2(
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
  prepared: PreparedDesktopProjectSettingsAuthorityOperationV2,
): void {
  if (prepared.config.mode !== 'local') return;
  throw new DesktopProjectSettingsAuthorityUnavailableErrorV2({
    reasonCode: PROJECT_SETTINGS_LOCAL_REASON,
  });
}

function createRevocableProjectSettingsAuthorityV2(
  authority: DesktopProjectSettingsAuthorityV2,
  scope: ProjectAdministrationScope,
  isOperationActive: () => boolean,
): DesktopProjectSettingsAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectSettingsSnapshotV2(result, scope);
    },
  });
}

function requireProjectSettingsServiceV2(
  value: unknown,
): DesktopProjectSettingsAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectSettingsAuthorityServiceV2;
}

function requireProjectSettingsAuthorityV2(
  value: unknown,
): DesktopProjectSettingsAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectSettingsAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectSettingsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_settings_operation_released',
    'desktop project settings operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_settings_service_invalid',
    'desktop project settings authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_SETTINGS_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_settings_authority_catalog_missing',
      'desktop project settings authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
