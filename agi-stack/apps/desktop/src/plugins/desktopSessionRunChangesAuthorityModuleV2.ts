import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { createDesktopRunReviewHttpProjectionV2 } from './desktopRunReviewHttpProjectionV2';
import {
  checkRunReviewAbortV2,
  prepareRunChangesScopeV2,
  requireRunReviewSnapshotIdentityV2,
  type DesktopRunChangesScopeV2,
} from './desktopRunReviewContractV2';
import type { AgentConversation, ChangeSnapshot, DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_SESSION_RUN_CHANGES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/session-run-changes-authority';
export const DESKTOP_SESSION_RUN_CHANGES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.session-run-changes-authority';
export const DESKTOP_SESSION_RUN_CHANGES_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopSessionRunChangesIdentityV2 = Readonly<{
  id: string;
  project_id: string;
  tenant_id: string;
  workspace_id: string | null;
}>;

export type DesktopSessionRunChangesOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: AgentConversation;
  expectedRevision: number;
  runId: string;
  scope?: 'turn' | 'run' | 'session';
  turnId?: string;
  signal: AbortSignal;
}>;

export interface DesktopSessionRunChangesAuthorityV2 {
  readonly getRunChanges: (
    identity: DesktopSessionRunChangesIdentityV2,
    runId: string,
    expectedRevision: number,
    signal: AbortSignal,
    options?: DesktopRunChangesScopeV2,
  ) => Promise<ChangeSnapshot>;
}

export interface DesktopSessionRunChangesAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopSessionRunChangesAuthorityV2;
}

export interface DesktopSessionRunChangesOperationsV2 {
  readonly getRunChanges: (
    input: DesktopSessionRunChangesOperationInputV2,
  ) => Promise<ChangeSnapshot>;
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

type PreparedSessionRunChangesOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  expectedRevision: number;
  identity: DesktopSessionRunChangesIdentityV2;
  runId: string;
  scope?: 'turn' | 'run' | 'session';
  turnId?: string;
  signal: AbortSignal;
}>;

export class DesktopSessionRunChangesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopSessionRunChangesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopSessionRunChangesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_session_run_changes_authority_config_invalid',
      'desktop session run changes authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopSessionRunChangesAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopSessionRunChangesAuthorityV2,
  });
  context.provide(DESKTOP_SESSION_RUN_CHANGES_AUTHORITY_SERVICE_V2, service);
}

export const desktopSessionRunChangesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_SESSION_RUN_CHANGES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopSessionRunChangesAuthorityV2,
});

export function createDesktopSessionRunChangesOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopSessionRunChangesOperationsV2 {
  return Object.freeze({
    getRunChanges(input: DesktopSessionRunChangesOperationInputV2) {
      const actions = requireGenerationActionsV2(resolveActions());
      return withDesktopSessionRunChangesAuthorityOperationV2(
        actions,
        input,
        async (authority, prepared) => {
          const request = { scope: prepared.scope, turnId: prepared.turnId };
          const value = await authority.getRunChanges(
            prepared.identity,
            prepared.runId,
            prepared.expectedRevision,
            prepared.signal,
            request,
          );
          return requireRunReviewSnapshotIdentityV2(
            value,
            prepared.config,
            prepared.identity,
            prepared.runId,
            prepared.expectedRevision,
            request,
          );
        },
      );
    },
  });
}

export function withDesktopSessionRunChangesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopSessionRunChangesOperationInputV2,
  operation: (
    authority: DesktopSessionRunChangesAuthorityV2,
    prepared: PreparedSessionRunChangesOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const prepared = prepareSessionRunChangesOperationV2(input);
  return runDesktopSessionRunChangesAuthorityOperationV2(actions, prepared, operation);
}

async function runDesktopSessionRunChangesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedSessionRunChangesOperationV2,
  operation: (
    authority: DesktopSessionRunChangesAuthorityV2,
    prepared: PreparedSessionRunChangesOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopSessionRunChangesAuthorityServiceV2>({
      service: DESKTOP_SESSION_RUN_CHANGES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_SESSION_RUN_CHANGES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'session',
        tenant_id: prepared.identity.tenant_id,
        project_id: prepared.identity.project_id,
        session_id: prepared.identity.id,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopSessionRunChangesAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  let consumed = false;
  try {
    return await admission.useService(async (service) => {
      if (!operationActive || consumed)
        throw new RuntimeV2Error(
          'desktop_session_run_changes_operation_released',
          'operation callback already consumed',
        );
      consumed = true;
      checkRunReviewAbortV2(prepared.signal);
      const result = await operation(
        createRevocableDesktopSessionRunChangesAuthorityV2(
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

function createDesktopSessionRunChangesAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopSessionRunChangesAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const transport = createDesktopRunReviewHttpProjectionV2(operationConfig);
  return Object.freeze({
    getRunChanges(
      identity: DesktopSessionRunChangesIdentityV2,
      runId: string,
      expectedRevision: number,
      signal: AbortSignal,
      options: DesktopRunChangesScopeV2 = {},
    ) {
      const operationIdentity = cloneSessionRunChangesIdentityV2(identity);
      const operationRequest = cloneSessionRunChangesRequestV2(runId, expectedRevision, signal);
      assertSessionRunChangesScopeV2(operationConfig, operationIdentity);
      return transport.getRunChanges(
        operationIdentity,
        operationRequest.runId,
        operationRequest.expectedRevision,
        operationRequest.signal,
        options,
      );
    },
  });
}

function createRevocableDesktopSessionRunChangesAuthorityV2(
  authority: DesktopSessionRunChangesAuthorityV2,
  isOperationActive: () => boolean,
): DesktopSessionRunChangesAuthorityV2 {
  return Object.freeze({
    getRunChanges(
      identity: DesktopSessionRunChangesIdentityV2,
      runId: string,
      expectedRevision: number,
      signal: AbortSignal,
      options: DesktopRunChangesScopeV2 = {},
    ) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_session_run_changes_operation_released',
          'desktop session run changes operation has been released',
        );
      }
      checkRunReviewAbortV2(signal);
      return authority.getRunChanges(identity, runId, expectedRevision, signal, options);
    },
  });
}

function prepareSessionRunChangesOperationV2(
  input: DesktopSessionRunChangesOperationInputV2,
): PreparedSessionRunChangesOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidSessionRunChangesInputV2();
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const identity = cloneSessionRunChangesIdentityV2(input.conversation);
  const request = cloneSessionRunChangesRequestV2(
    input.runId,
    input.expectedRevision,
    input.signal,
  );
  assertSessionRunChangesScopeV2(config, identity);
  const scope = prepareRunChangesScopeV2(config, request.expectedRevision, {
    scope: input.scope,
    turnId: input.turnId,
  });
  checkRunReviewAbortV2(request.signal);
  return Object.freeze({ config, identity, ...request, ...scope });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidSessionRunChangesInputV2();
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
    throw invalidSessionRunChangesInputV2();
  }
  return Object.freeze(copy);
}

function cloneSessionRunChangesIdentityV2(
  conversation: Pick<AgentConversation, 'id' | 'project_id' | 'tenant_id' | 'workspace_id'>,
): DesktopSessionRunChangesIdentityV2 {
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
    throw invalidSessionRunChangesInputV2();
  }
  return Object.freeze({
    id: conversation.id,
    tenant_id: conversation.tenant_id,
    project_id: conversation.project_id,
    workspace_id: workspaceId,
  });
}

function cloneSessionRunChangesRequestV2(
  runId: unknown,
  expectedRevision: unknown,
  signal: unknown,
): Readonly<{ expectedRevision: number; runId: string; signal: AbortSignal }> {
  if (
    !isCanonicalStringV2(runId) ||
    !Number.isSafeInteger(expectedRevision) ||
    (expectedRevision as number) < 0 ||
    !isAbortSignalV2(signal)
  ) {
    throw invalidSessionRunChangesInputV2();
  }
  return Object.freeze({
    runId,
    expectedRevision: expectedRevision as number,
    signal,
  });
}

function assertSessionRunChangesScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunChangesIdentityV2,
): void {
  const workspaceId = config.workspaceId.trim() || null;
  if (
    config.tenantId !== identity.tenant_id ||
    config.projectId !== identity.project_id ||
    workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      'desktop_session_run_changes_scope_mismatch',
      'desktop session run changes scope differs from the conversation identity',
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
  throw new DesktopSessionRunChangesAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidSessionRunChangesInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_run_changes_input_invalid',
    'desktop session run changes operation input is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_SESSION_RUN_CHANGES_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_session_run_changes_authority_catalog_missing',
      'desktop session run changes authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
