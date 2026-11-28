import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import { createDesktopAgentAuthorityAdapter } from '../features/agent-authority/cloudAgentAuthorityClient';
import type { CloudAgentAuthorityScope } from '../features/agent-authority/agentAuthorityTypes';
import type { DesktopRuntimeConfig, ProjectMyWorkResponse } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_MY_WORK_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/my-work-authority';
export const DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2 = 'service:desktop-renderer.my-work-authority';
export const DESKTOP_MY_WORK_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopMyWorkAuthorityBindingInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  principalId?: string | null;
}>;

export type DesktopMyWorkOperationInputV2 = DesktopMyWorkAuthorityBindingInputV2 &
  Readonly<{
    signal?: AbortSignal;
  }>;

export interface DesktopMyWorkAuthorityV2 {
  readonly listMyWork: (signal?: AbortSignal) => Promise<ProjectMyWorkResponse>;
}

export interface DesktopMyWorkAuthorityServiceV2 {
  readonly bindOperation: (input: DesktopMyWorkAuthorityBindingInputV2) => DesktopMyWorkAuthorityV2;
}

export interface DesktopMyWorkOperationsV2 {
  readonly listMyWork: (input: DesktopMyWorkOperationInputV2) => Promise<ProjectMyWorkResponse>;
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

type PreparedMyWorkOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  principalId: string | null;
  signal?: AbortSignal;
}>;

export class DesktopMyWorkAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopMyWorkAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopMyWorkAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_my_work_authority_config_invalid',
      'desktop My Work authority requires desktop-api-client strategy'
    );
  }
  const service: DesktopMyWorkAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopMyWorkAuthorityV2,
  });
  context.provide(DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2, service);
}

export const desktopMyWorkAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_MY_WORK_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopMyWorkAuthorityV2,
});

export function createDesktopMyWorkOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null
): DesktopMyWorkOperationsV2 {
  return Object.freeze({
    listMyWork(input: DesktopMyWorkOperationInputV2) {
      const prepared = prepareMyWorkOperationV2(input);
      return runDesktopMyWorkAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listMyWork(prepared.signal)
      );
    },
  });
}

export function withDesktopMyWorkAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopMyWorkOperationInputV2,
  operation: (
    authority: DesktopMyWorkAuthorityV2,
    prepared: PreparedMyWorkOperationV2
  ) => TResult | Promise<TResult>
): Promise<TResult> {
  return runDesktopMyWorkAuthorityOperationV2(actions, prepareMyWorkOperationV2(input), operation);
}

async function runDesktopMyWorkAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedMyWorkOperationV2,
  operation: (
    authority: DesktopMyWorkAuthorityV2,
    prepared: PreparedMyWorkOperationV2
  ) => TResult | Promise<TResult>
): Promise<TResult> {
  const admission = await actions.acquireServiceOperationLease<DesktopMyWorkAuthorityServiceV2>({
    service: DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2,
    version: DESKTOP_MY_WORK_AUTHORITY_VERSION_V2,
    scope: Object.freeze({
      kind: 'project',
      tenant_id: prepared.config.tenantId,
      project_id: prepared.config.projectId,
    }),
  });
  if (admission.status === 'rejected') {
    throw new DesktopMyWorkAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireMyWorkServiceV2(candidate);
      const authority = requireMyWorkAuthorityV2(
        service.bindOperation({
          config: prepared.config,
          principalId: prepared.principalId,
        })
      );
      return operation(
        createRevocableDesktopMyWorkAuthorityV2(authority, () => operationActive),
        prepared
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

function createDesktopMyWorkAuthorityV2(
  input: DesktopMyWorkAuthorityBindingInputV2
): DesktopMyWorkAuthorityV2 {
  const prepared = prepareMyWorkBindingV2(input);
  if (prepared.config.mode === 'cloud') {
    const adapter = createDesktopAgentAuthorityAdapter(prepared.config);
    const cloudClient = adapter.client;
    if (cloudClient === null || prepared.principalId === null) {
      throw invalidMyWorkServiceV2();
    }
    const scope: CloudAgentAuthorityScope = Object.freeze({
      authority: 'cloud',
      principalId: prepared.principalId,
      tenantId: prepared.config.tenantId,
      projectId: prepared.config.projectId,
    });
    return Object.freeze({
      listMyWork: (signal?: AbortSignal) =>
        cloudClient
          .listMyWork(scope, { signal })
          .then((response) => assertMyWorkResponseScopeV2(response, prepared.config.projectId)),
    });
  }

  const transport = new DesktopApiClient(prepared.config);
  return Object.freeze({
    listMyWork: (signal?: AbortSignal) =>
      transport
        .listMyWork(prepared.config.projectId, signal)
        .then((response) => assertMyWorkResponseScopeV2(response, prepared.config.projectId)),
  });
}

function createRevocableDesktopMyWorkAuthorityV2(
  authority: DesktopMyWorkAuthorityV2,
  isOperationActive: () => boolean
): DesktopMyWorkAuthorityV2 {
  return Object.freeze({
    listMyWork(signal?: AbortSignal) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_my_work_operation_released',
          'desktop My Work operation has been released'
        );
      }
      return authority.listMyWork(signal);
    },
  });
}

function prepareMyWorkOperationV2(input: DesktopMyWorkOperationInputV2): PreparedMyWorkOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidMyWorkInputV2();
  const prepared = prepareMyWorkBindingV2(input);
  if (input.signal !== undefined && !isAbortSignalV2(input.signal)) {
    throw invalidMyWorkInputV2();
  }
  return Object.freeze({
    ...prepared,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function prepareMyWorkBindingV2(
  input: DesktopMyWorkAuthorityBindingInputV2
): Readonly<{ config: DesktopRuntimeConfig; principalId: string | null }> {
  if (!isPlainRecordV2(input)) throw invalidMyWorkInputV2();
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const principalId = clonePrincipalIdV2(config, input.principalId);
  return Object.freeze({ config, principalId });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidMyWorkInputV2();
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
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalStringV2(copy.tenantId) ||
    !isCanonicalStringV2(copy.projectId)
  ) {
    throw invalidMyWorkInputV2();
  }
  return Object.freeze(copy);
}

function clonePrincipalIdV2(
  config: DesktopRuntimeConfig,
  principalId: string | null | undefined
): string | null {
  if (principalId === null || principalId === undefined) {
    if (config.mode === 'cloud') throw invalidMyWorkInputV2();
    return null;
  }
  if (!isCanonicalStringV2(principalId)) throw invalidMyWorkInputV2();
  return principalId;
}

function assertMyWorkResponseScopeV2(
  response: ProjectMyWorkResponse,
  projectId: string
): ProjectMyWorkResponse {
  if (!isPlainRecordV2(response) || response.project_id !== projectId) {
    throw new RuntimeV2Error(
      'desktop_my_work_response_scope_mismatch',
      'desktop My Work response differs from the operation identity'
    );
  }
  return response;
}

function requireMyWorkServiceV2(value: unknown): DesktopMyWorkAuthorityServiceV2 {
  if (!isPlainRecordV2(value) || typeof value.bindOperation !== 'function') {
    throw invalidMyWorkServiceV2();
  }
  return value as unknown as DesktopMyWorkAuthorityServiceV2;
}

function requireMyWorkAuthorityV2(value: unknown): DesktopMyWorkAuthorityV2 {
  if (!isPlainRecordV2(value) || typeof value.listMyWork !== 'function') {
    throw invalidMyWorkServiceV2();
  }
  return value as unknown as DesktopMyWorkAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopMyWorkAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidMyWorkInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_my_work_input_invalid',
    'desktop My Work operation input is invalid'
  );
}

function invalidMyWorkServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_my_work_service_invalid',
    'desktop My Work service is invalid'
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_MY_WORK_AUTHORITY_MODULE_REF_V2
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_my_work_authority_catalog_missing',
      'desktop My Work authority is absent from the generated catalog'
    );
  }
  return entry.contract_digest;
}
