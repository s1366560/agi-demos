import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import { createDesktopRunReviewHttpProjectionV2 } from './desktopRunReviewHttpProjectionV2';
import {
  checkRunReviewAbortV2,
  runReviewErrorV2,
  requireRunReviewSummaryV2,
} from './desktopRunReviewContractV2';
import type { AgentConversation, DesktopRuntimeConfig, RunSummary } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_SESSION_PROJECTION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/session-projection-authority';
export const DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.session-projection-authority';
export const DESKTOP_SESSION_PROJECTION_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopSessionProjectionIdentityV2 = Readonly<{
  id: string;
  project_id: string;
  tenant_id: string;
  workspace_id: string | null;
}>;

export type DesktopSessionProjectionOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: AgentConversation;
  signal: AbortSignal;
}>;

export type DesktopSessionRunSummaryOperationInputV2 = DesktopSessionProjectionOperationInputV2 &
  Readonly<{ runId: string }>;

export interface DesktopSessionProjectionAuthorityV2 {
  readonly getRunSummary: (
    identity: DesktopSessionProjectionIdentityV2,
    runId: string,
    signal: AbortSignal,
  ) => Promise<RunSummary>;
  readonly getConversationSession: (
    identity: DesktopSessionProjectionIdentityV2,
    signal: AbortSignal,
  ) => Promise<unknown>;
}

export interface DesktopSessionProjectionAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopSessionProjectionAuthorityV2;
}

export interface DesktopSessionProjectionOperationsV2 {
  readonly getRunSummary: (input: DesktopSessionRunSummaryOperationInputV2) => Promise<RunSummary>;
  readonly getConversationSession: (
    input: DesktopSessionProjectionOperationInputV2,
  ) => Promise<unknown>;
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

type PreparedSessionProjectionOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  identity: DesktopSessionProjectionIdentityV2;
  signal: AbortSignal;
}>;

export class DesktopSessionProjectionAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopSessionProjectionAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopSessionProjectionAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_session_projection_authority_config_invalid',
      'desktop session projection authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopSessionProjectionAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopSessionProjectionAuthorityV2,
  });
  context.provide(DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2, service);
}

export const desktopSessionProjectionAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_SESSION_PROJECTION_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopSessionProjectionAuthorityV2,
});

export function createDesktopSessionProjectionOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopSessionProjectionOperationsV2 {
  return Object.freeze({
    getRunSummary(input: DesktopSessionRunSummaryOperationInputV2) {
      if (!isPlainRecordV2(input) || !isCanonicalStringV2(input.runId))
        throw runReviewErrorV2('desktop_run_review_identity_invalid');
      const runId = input.runId;
      const actions = requireGenerationActionsV2(resolveActions());
      return withDesktopSessionProjectionAuthorityOperationV2(
        actions,
        input,
        async (authority, prepared) =>
          requireRunReviewSummaryV2(
            await authority.getRunSummary(prepared.identity, runId, prepared.signal),
            prepared.identity,
            runId,
          ),
      );
    },
    getConversationSession(input: DesktopSessionProjectionOperationInputV2) {
      const actions = requireGenerationActionsV2(resolveActions());
      return withDesktopSessionProjectionAuthorityOperationV2(
        actions,
        input,
        (authority, prepared) =>
          authority.getConversationSession(prepared.identity, prepared.signal),
      );
    },
  });
}

export function withDesktopSessionProjectionAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopSessionProjectionOperationInputV2,
  operation: (
    authority: DesktopSessionProjectionAuthorityV2,
    prepared: PreparedSessionProjectionOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const prepared = prepareSessionProjectionOperationV2(input);
  return runDesktopSessionProjectionAuthorityOperationV2(actions, prepared, operation);
}

async function runDesktopSessionProjectionAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedSessionProjectionOperationV2,
  operation: (
    authority: DesktopSessionProjectionAuthorityV2,
    prepared: PreparedSessionProjectionOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopSessionProjectionAuthorityServiceV2>({
      service: DESKTOP_SESSION_PROJECTION_AUTHORITY_SERVICE_V2,
      version: DESKTOP_SESSION_PROJECTION_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'session',
        tenant_id: prepared.identity.tenant_id,
        project_id: prepared.identity.project_id,
        session_id: prepared.identity.id,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopSessionProjectionAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  let consumed = false;
  try {
    return await admission.useService(async (service) => {
      if (!operationActive || consumed)
        throw new RuntimeV2Error(
          'desktop_session_projection_operation_released',
          'operation callback already consumed',
        );
      consumed = true;
      checkRunReviewAbortV2(prepared.signal);
      const result = await operation(
        createRevocableDesktopSessionProjectionAuthorityV2(
          service.bindOperation(prepared.config),
          () => operationActive,
        ),
        prepared,
      );
      checkRunReviewAbortV2(prepared.signal);
      return result;
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

function createDesktopSessionProjectionAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopSessionProjectionAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  const runReview = createDesktopRunReviewHttpProjectionV2(operationConfig);
  return Object.freeze({
    getRunSummary(
      identity: DesktopSessionProjectionIdentityV2,
      runId: string,
      signal: AbortSignal,
    ) {
      const operationIdentity = cloneSessionProjectionIdentityV2(identity);
      assertSessionProjectionScopeV2(operationConfig, operationIdentity);
      return runReview.getRunSummary(operationIdentity, runId, signal);
    },
    getConversationSession(identity: DesktopSessionProjectionIdentityV2, signal: AbortSignal) {
      const operationIdentity = cloneSessionProjectionIdentityV2(identity);
      if (!isAbortSignalV2(signal)) throw invalidSessionProjectionInputV2();
      assertSessionProjectionScopeV2(operationConfig, operationIdentity);
      return transport.getConversationSession(
        operationIdentity.id,
        {
          tenantId: operationIdentity.tenant_id,
          projectId: operationIdentity.project_id,
          workspaceId: operationIdentity.workspace_id,
        },
        signal,
      );
    },
  });
}

function createRevocableDesktopSessionProjectionAuthorityV2(
  authority: DesktopSessionProjectionAuthorityV2,
  isOperationActive: () => boolean,
): DesktopSessionProjectionAuthorityV2 {
  return Object.freeze({
    getRunSummary(
      identity: DesktopSessionProjectionIdentityV2,
      runId: string,
      signal: AbortSignal,
    ) {
      if (!isOperationActive())
        throw new RuntimeV2Error(
          'desktop_session_projection_operation_released',
          'desktop session projection operation has been released',
        );
      checkRunReviewAbortV2(signal);
      return authority.getRunSummary(identity, runId, signal);
    },
    getConversationSession(identity: DesktopSessionProjectionIdentityV2, signal: AbortSignal) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_session_projection_operation_released',
          'desktop session projection operation has been released',
        );
      }
      return authority.getConversationSession(identity, signal);
    },
  });
}

function prepareSessionProjectionOperationV2(
  input: DesktopSessionProjectionOperationInputV2,
): PreparedSessionProjectionOperationV2 {
  if (!isPlainRecordV2(input) || !isAbortSignalV2(input.signal)) {
    throw invalidSessionProjectionInputV2();
  }
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const identity = cloneSessionProjectionIdentityV2(input.conversation);
  assertSessionProjectionScopeV2(config, identity);
  return Object.freeze({ config, identity, signal: input.signal });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidSessionProjectionInputV2();
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
    throw invalidSessionProjectionInputV2();
  }
  return Object.freeze(copy);
}

function cloneSessionProjectionIdentityV2(
  conversation: Pick<AgentConversation, 'id' | 'project_id' | 'tenant_id' | 'workspace_id'>,
): DesktopSessionProjectionIdentityV2 {
  const workspaceId = isPlainRecordV2(conversation)
    ? cloneWorkspaceIdentityV2(conversation.workspace_id)
    : undefined;
  if (
    !isPlainRecordV2(conversation) ||
    !isCanonicalStringV2(conversation.id) ||
    !isCanonicalStringV2(conversation.tenant_id) ||
    !isCanonicalStringV2(conversation.project_id) ||
    workspaceId === undefined
  ) {
    throw invalidSessionProjectionInputV2();
  }
  return Object.freeze({
    id: conversation.id,
    tenant_id: conversation.tenant_id,
    project_id: conversation.project_id,
    workspace_id: workspaceId,
  });
}

function assertSessionProjectionScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionProjectionIdentityV2,
): void {
  const workspaceId = config.workspaceId.trim() || null;
  if (
    config.tenantId !== identity.tenant_id ||
    config.projectId !== identity.project_id ||
    workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      'desktop_session_projection_scope_mismatch',
      'desktop session projection scope differs from the conversation identity',
    );
  }
}

function cloneWorkspaceIdentityV2(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return null;
  return isCanonicalStringV2(value) ? value : undefined;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopSessionProjectionAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidSessionProjectionInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_projection_input_invalid',
    'desktop session projection operation input is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_SESSION_PROJECTION_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_session_projection_authority_catalog_missing',
      'desktop session projection authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
