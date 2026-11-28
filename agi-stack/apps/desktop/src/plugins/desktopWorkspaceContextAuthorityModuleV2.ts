import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  DesktopRuntimeConfig,
  ProjectSummary,
  WorkspaceContextResponse,
  WorkspaceContextSwitchOutcome,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-context-authority';
export const DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-context-authority';
export const DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopWorkspaceContextAuthorityV2 {
  readonly listProjects: (tenantId: string, signal: AbortSignal) => Promise<ProjectSummary[]>;
  readonly getWorkspaceContext: (signal: AbortSignal) => Promise<WorkspaceContextResponse>;
  readonly switchWorkspaceContext: (
    tenantId: string,
    projectId: string,
    expectedRevision: number,
    idempotencyKey: string,
    signal: AbortSignal,
  ) => Promise<WorkspaceContextSwitchOutcome>;
}

export interface DesktopWorkspaceContextAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopWorkspaceContextAuthorityV2;
}

type DesktopWorkspaceContextAuthorityAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;

export class DesktopWorkspaceContextAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceContextAuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: DesktopWorkspaceContextAuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopWorkspaceContextAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceContextAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_workspace_context_authority_config_invalid',
      'desktop workspace context authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopWorkspaceContextAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceContextAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceContextAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopWorkspaceContextAuthorityV2,
});

export async function withDesktopWorkspaceContextAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  config: DesktopRuntimeConfig,
  operation: (authority: DesktopWorkspaceContextAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceContextAuthorityServiceV2>({
      service: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_SERVICE_V2,
      version: DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'root' }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopWorkspaceContextAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) => {
      const authority = createRevocableDesktopWorkspaceContextAuthorityV2(
        service.bindOperation(operationConfig),
        () => operationActive,
      );
      return operation(authority);
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

function createRevocableDesktopWorkspaceContextAuthorityV2(
  authority: DesktopWorkspaceContextAuthorityV2,
  isOperationActive: () => boolean,
): DesktopWorkspaceContextAuthorityV2 {
  const assertActive = (): void => {
    if (!isOperationActive()) {
      throw new RuntimeV2Error(
        'desktop_workspace_context_authority_operation_released',
        'desktop workspace context authority operation has been released',
      );
    }
  };
  return Object.freeze({
    listProjects: (tenantId: string, signal: AbortSignal) => {
      assertActive();
      return authority.listProjects(tenantId, signal);
    },
    getWorkspaceContext: (signal: AbortSignal) => {
      assertActive();
      return authority.getWorkspaceContext(signal);
    },
    switchWorkspaceContext: (
      tenantId: string,
      projectId: string,
      expectedRevision: number,
      idempotencyKey: string,
      signal: AbortSignal,
    ) => {
      assertActive();
      return authority.switchWorkspaceContext(
        tenantId,
        projectId,
        expectedRevision,
        idempotencyKey,
        signal,
      );
    },
  });
}

function createDesktopWorkspaceContextAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceContextAuthorityV2 {
  const authority = new DesktopApiClient(cloneDesktopRuntimeConfigV2(config));
  return Object.freeze({
    listProjects: (tenantId: string, signal: AbortSignal) =>
      authority.listProjects(tenantId, signal),
    getWorkspaceContext: (signal: AbortSignal) => authority.getWorkspaceContext(signal),
    switchWorkspaceContext: (
      tenantId: string,
      projectId: string,
      expectedRevision: number,
      idempotencyKey: string,
      signal: AbortSignal,
    ) =>
      authority.switchWorkspaceContext(
        tenantId,
        projectId,
        expectedRevision,
        idempotencyKey,
        signal,
      ),
  });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local')
  ) {
    throw new RuntimeV2Error(
      'desktop_workspace_context_runtime_config_invalid',
      'desktop workspace context operation requires a complete runtime config',
    );
  }
  return Object.freeze(copy);
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_WORKSPACE_CONTEXT_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_workspace_context_authority_catalog_missing',
      'desktop workspace context authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
