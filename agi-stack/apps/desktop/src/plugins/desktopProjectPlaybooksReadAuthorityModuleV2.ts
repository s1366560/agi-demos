import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { desktopVaultBoundCloudRequestBroker } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import type {
  ProjectPlaybooksClient,
  ProjectPlaybooksSnapshot,
} from '../features/project-playbooks/projectPlaybooksClient';
import {
  createDesktopProjectPlaybooksReadHttpAuthorityV2,
  requireDesktopProjectPlaybooksSnapshotV2,
} from './desktopProjectPlaybooksReadHttpProjectionV2';
import {
  prepareDesktopProjectPlaybooksReadOperationV2,
  type DesktopProjectPlaybooksReadOperationInputV2,
} from './desktopProjectPlaybooksReadOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_PROJECT_PLAYBOOKS_READ_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-playbooks-read-authority';
export const DESKTOP_PROJECT_PLAYBOOKS_READ_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-playbooks-read-authority';
export const DESKTOP_PROJECT_PLAYBOOKS_READ_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectPlaybooksReadAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => ProjectPlaybooksClient;
}

export interface DesktopProjectPlaybooksReadOperationsV2 {
  readonly loadProjectPlaybooks: (
    input: DesktopProjectPlaybooksReadOperationInputV2,
  ) => Promise<ProjectPlaybooksSnapshot>;
}

type AdmissionRejectionV2 =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopProjectPlaybooksReadAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectPlaybooksReadAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectPlaybooksReadAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'vault-bound-cloud-request-broker') {
    throw new RuntimeV2Error(
      'desktop_project_playbooks_read_authority_config_invalid',
      'desktop project playbooks read authority requires vault-bound-cloud-request-broker strategy',
    );
  }
  context.provide(
    DESKTOP_PROJECT_PLAYBOOKS_READ_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation: (runtimeConfig: DesktopRuntimeConfig) =>
        createDesktopProjectPlaybooksReadHttpAuthorityV2(
          runtimeConfig,
          desktopVaultBoundCloudRequestBroker(),
        ),
    }),
  );
}

export const desktopProjectPlaybooksReadAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_PLAYBOOKS_READ_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectPlaybooksReadAuthorityV2,
});

export function createDesktopProjectPlaybooksReadOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectPlaybooksReadOperationsV2 {
  return Object.freeze({
    loadProjectPlaybooks(input: DesktopProjectPlaybooksReadOperationInputV2) {
      const prepared = prepareDesktopProjectPlaybooksReadOperationV2(input);
      const actions = resolveActions();
      if (actions === null) {
        throw new DesktopProjectPlaybooksReadAuthorityUnavailableErrorV2({
          reasonCode: 'desktop_renderer_generation_actions_unavailable',
        });
      }
      return runV2(actions, prepared);
    },
  });
}

export function createDesktopProjectPlaybooksReadClientV2(
  operations: DesktopProjectPlaybooksReadOperationsV2,
  config: DesktopRuntimeConfig,
): ProjectPlaybooksClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(scope, options) {
      return operations.loadProjectPlaybooks({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

async function runV2(
  actions: DesktopRendererGenerationActionsV2,
  prepared: DesktopProjectPlaybooksReadOperationInputV2,
): Promise<ProjectPlaybooksSnapshot> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectPlaybooksReadAuthorityServiceV2>({
      service: DESKTOP_PROJECT_PLAYBOOKS_READ_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_PLAYBOOKS_READ_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectPlaybooksReadAuthorityUnavailableErrorV2(admission);
  }
  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService(async (candidate) => {
      const service = requireServiceV2(candidate);
      const client = requireClientV2(service.bindOperation(prepared.config));
      requireActiveV2(operationActive);
      const result = await client.load(prepared.scope, { signal: prepared.signal });
      requireActiveV2(operationActive);
      return requireDesktopProjectPlaybooksSnapshotV2(result, prepared.scope);
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

function requireServiceV2(value: unknown): DesktopProjectPlaybooksReadAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectPlaybooksReadAuthorityServiceV2;
}

function requireClientV2(value: unknown): ProjectPlaybooksClient {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as ProjectPlaybooksClient;
}

function requireActiveV2(active: boolean): void {
  if (active) return;
  throw new RuntimeV2Error(
    'desktop_project_playbooks_read_operation_released',
    'desktop project playbooks read operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_playbooks_read_service_invalid',
    'desktop project playbooks read authority service is invalid',
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_PLAYBOOKS_READ_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_playbooks_read_authority_catalog_missing',
      'desktop project playbooks read authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
