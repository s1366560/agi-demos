import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  AgentConversation,
  DesktopRuntimeConfig,
  HitlResponseSubmission,
  HitlType,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_HITL_RESPONSE_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/hitl-response-authority';
export const DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.hitl-response-authority';
export const DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2 = '1.0.0';

const PENDING_HITL_AUTHORITY_REVISION_V2 = 1;
const SETTLED_HITL_AUTHORITY_REVISION_V2 = 2;
const MAX_RESPONSE_DATA_DEPTH_V2 = 32;
const HITL_TYPES_V2 = new Set<HitlType>([
  'clarification',
  'decision',
  'env_var',
  'permission',
  'a2ui_action',
]);

export type DesktopHitlResponseIdentityV2 = Readonly<{
  id: string;
  project_id: string;
  tenant_id: string;
  workspace_id: string | null;
}>;

export type DesktopHitlResponseCommandV2 = Readonly<{
  expectedRevision: typeof PENDING_HITL_AUTHORITY_REVISION_V2;
  hitlType: HitlType;
  idempotencyKey: string;
  requestId: string;
  responseData: Readonly<Record<string, unknown>>;
}>;

export type DesktopHitlResponseReceiptV2 = Readonly<{
  answered_at: string;
  authority_revision: typeof SETTLED_HITL_AUTHORITY_REVISION_V2;
  authority_status: 'answered';
  created_at: string;
  duplicate: boolean;
  expires_at: string | null;
  message: string;
  observed_at: string;
  request_id: string;
  status: 'answered';
  success: true;
}>;

export type DesktopHitlResponseOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: AgentConversation;
  submission: HitlResponseSubmission;
}>;

export interface DesktopHitlResponseAuthorityV2 {
  readonly respond: (
    identity: DesktopHitlResponseIdentityV2,
    command: DesktopHitlResponseCommandV2,
  ) => Promise<DesktopHitlResponseReceiptV2>;
}

export interface DesktopHitlResponseAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopHitlResponseAuthorityV2;
}

export interface DesktopHitlResponseOperationsV2 {
  readonly respond: (
    input: DesktopHitlResponseOperationInputV2,
  ) => Promise<DesktopHitlResponseReceiptV2>;
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

type PreparedHitlResponseOperationV2 = Readonly<{
  command: DesktopHitlResponseCommandV2;
  config: DesktopRuntimeConfig;
  identity: DesktopHitlResponseIdentityV2;
}>;

export class DesktopHitlResponseAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopHitlResponseAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopHitlResponseAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_hitl_response_authority_config_invalid',
      'desktop HITL response authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopHitlResponseAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopHitlResponseAuthorityV2,
  });
  context.provide(DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2, service);
}

export const desktopHitlResponseAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_HITL_RESPONSE_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopHitlResponseAuthorityV2,
});

export function createDesktopHitlResponseOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopHitlResponseOperationsV2 {
  return Object.freeze({
    respond(input: DesktopHitlResponseOperationInputV2) {
      const actions = requireGenerationActionsV2(resolveActions());
      return withDesktopHitlResponseAuthorityOperationV2(
        actions,
        input,
        (authority, prepared) => authority.respond(prepared.identity, prepared.command),
      );
    },
  });
}

export function withDesktopHitlResponseAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopHitlResponseOperationInputV2,
  operation: (
    authority: DesktopHitlResponseAuthorityV2,
    prepared: PreparedHitlResponseOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const prepared = prepareHitlResponseOperationV2(input);
  return runDesktopHitlResponseAuthorityOperationV2(actions, prepared, operation);
}

async function runDesktopHitlResponseAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedHitlResponseOperationV2,
  operation: (
    authority: DesktopHitlResponseAuthorityV2,
    prepared: PreparedHitlResponseOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopHitlResponseAuthorityServiceV2>({
      service: DESKTOP_HITL_RESPONSE_AUTHORITY_SERVICE_V2,
      version: DESKTOP_HITL_RESPONSE_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'session',
        tenant_id: prepared.identity.tenant_id,
        project_id: prepared.identity.project_id,
        session_id: prepared.identity.id,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopHitlResponseAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableDesktopHitlResponseAuthorityV2(
          service.bindOperation(prepared.config),
          () => operationActive,
        ),
        prepared,
      ),
    );
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

function createDesktopHitlResponseAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopHitlResponseAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    respond(
      identity: DesktopHitlResponseIdentityV2,
      command: DesktopHitlResponseCommandV2,
    ) {
      const operationIdentity = cloneHitlResponseIdentityV2(identity);
      const operationCommand = cloneHitlResponseCommandV2(command);
      assertHitlResponseScopeV2(operationConfig, operationIdentity);
      return transport
        .respondToHitl(operationCommand)
        .then((response) => validateHitlResponseReceiptV2(response, operationCommand));
    },
  });
}

function createRevocableDesktopHitlResponseAuthorityV2(
  authority: DesktopHitlResponseAuthorityV2,
  isOperationActive: () => boolean,
): DesktopHitlResponseAuthorityV2 {
  return Object.freeze({
    respond(
      identity: DesktopHitlResponseIdentityV2,
      command: DesktopHitlResponseCommandV2,
    ) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_hitl_response_operation_released',
          'desktop HITL response operation has been released',
        );
      }
      return authority.respond(identity, command);
    },
  });
}

function prepareHitlResponseOperationV2(
  input: DesktopHitlResponseOperationInputV2,
): PreparedHitlResponseOperationV2 {
  if (!isPlainRecordV2(input)) {
    throw invalidHitlResponseInputV2();
  }
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const identity = cloneHitlResponseIdentityV2(input.conversation);
  const command = cloneHitlResponseCommandV2(input.submission);
  assertHitlResponseScopeV2(config, identity);
  return Object.freeze({ command, config, identity });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) {
    throw invalidHitlResponseInputV2();
  }
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
    throw invalidHitlResponseInputV2();
  }
  return Object.freeze(copy);
}

function cloneHitlResponseIdentityV2(
  conversation: Pick<
    AgentConversation,
    'id' | 'project_id' | 'tenant_id' | 'workspace_id'
  >,
): DesktopHitlResponseIdentityV2 {
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
    throw invalidHitlResponseInputV2();
  }
  return Object.freeze({
    id: conversation.id,
    tenant_id: conversation.tenant_id,
    project_id: conversation.project_id,
    workspace_id: workspaceId,
  });
}

function cloneHitlResponseCommandV2(
  submission: HitlResponseSubmission | DesktopHitlResponseCommandV2,
): DesktopHitlResponseCommandV2 {
  if (
    !isPlainRecordV2(submission) ||
    !isCanonicalStringV2(submission.requestId) ||
    !HITL_TYPES_V2.has(submission.hitlType) ||
    submission.expectedRevision !== PENDING_HITL_AUTHORITY_REVISION_V2 ||
    !isVisibleAsciiIdempotencyKeyV2(submission.idempotencyKey) ||
    !isPlainRecordV2(submission.responseData)
  ) {
    throw invalidHitlResponseInputV2();
  }
  const responseData = cloneJsonRecordV2(
    submission.responseData,
    new Set<object>(),
    0,
  );
  return Object.freeze({
    requestId: submission.requestId,
    hitlType: submission.hitlType,
    responseData,
    expectedRevision: PENDING_HITL_AUTHORITY_REVISION_V2,
    idempotencyKey: submission.idempotencyKey,
  });
}

function cloneJsonRecordV2(
  value: Record<string, unknown>,
  ancestors: Set<object>,
  depth: number,
): Readonly<Record<string, unknown>> {
  return cloneJsonValueV2(value, ancestors, depth) as Readonly<Record<string, unknown>>;
}

function cloneJsonValueV2(value: unknown, ancestors: Set<object>, depth: number): unknown {
  if (depth > MAX_RESPONSE_DATA_DEPTH_V2) {
    throw invalidHitlResponseInputV2();
  }
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return value;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw invalidHitlResponseInputV2();
    return value;
  }
  if (typeof value !== 'object' || value === null || ancestors.has(value)) {
    throw invalidHitlResponseInputV2();
  }

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      const keys = Reflect.ownKeys(value).filter((key) => key !== 'length');
      if (
        keys.length !== value.length ||
        keys.some((key, index) => key !== String(index))
      ) {
        throw invalidHitlResponseInputV2();
      }
      return Object.freeze(
        value.map((item) => cloneJsonValueV2(item, ancestors, depth + 1)),
      );
    }
    if (!isPlainRecordV2(value)) throw invalidHitlResponseInputV2();

    const clone: Record<string, unknown> = {};
    for (const key of Reflect.ownKeys(value)) {
      if (typeof key !== 'string') throw invalidHitlResponseInputV2();
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (
        descriptor === undefined ||
        !descriptor.enumerable ||
        !('value' in descriptor)
      ) {
        throw invalidHitlResponseInputV2();
      }
      Object.defineProperty(clone, key, {
        configurable: false,
        enumerable: true,
        value: cloneJsonValueV2(descriptor.value, ancestors, depth + 1),
        writable: false,
      });
    }
    return Object.freeze(clone);
  } finally {
    ancestors.delete(value);
  }
}

function assertHitlResponseScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopHitlResponseIdentityV2,
): void {
  const workspaceId = config.workspaceId.trim() || null;
  if (
    config.tenantId !== identity.tenant_id ||
    config.projectId !== identity.project_id ||
    workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      'desktop_hitl_response_scope_mismatch',
      'desktop HITL response operation scope differs from the conversation identity',
    );
  }
}

function cloneWorkspaceIdentityV2(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return null;
  return isCanonicalStringV2(value) ? value : undefined;
}

function validateHitlResponseReceiptV2(
  response: unknown,
  command: DesktopHitlResponseCommandV2,
): DesktopHitlResponseReceiptV2 {
  if (
    !isPlainRecordV2(response) ||
    response.success !== true ||
    response.request_id !== command.requestId ||
    response.status !== 'answered' ||
    response.authority_status !== 'answered' ||
    response.authority_revision !== SETTLED_HITL_AUTHORITY_REVISION_V2 ||
    typeof response.duplicate !== 'boolean' ||
    !isCanonicalStringV2(response.message) ||
    !isCanonicalStringV2(response.created_at) ||
    !isCanonicalStringV2(response.answered_at) ||
    !isCanonicalStringV2(response.observed_at) ||
    (response.expires_at !== null && !isCanonicalStringV2(response.expires_at))
  ) {
    throw new RuntimeV2Error(
      'desktop_hitl_response_receipt_invalid',
      'desktop HITL response receipt does not match the revisioned authority contract',
    );
  }
  return Object.freeze({
    success: true,
    message: response.message,
    status: 'answered',
    duplicate: response.duplicate,
    request_id: command.requestId,
    authority_revision: SETTLED_HITL_AUTHORITY_REVISION_V2,
    authority_status: 'answered',
    created_at: response.created_at,
    answered_at: response.answered_at,
    expires_at: response.expires_at,
    observed_at: response.observed_at,
  });
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopHitlResponseAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidHitlResponseInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_hitl_response_input_invalid',
    'desktop HITL response operation input is invalid',
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

function isVisibleAsciiIdempotencyKeyV2(value: unknown): value is string {
  if (typeof value !== 'string' || value.length < 1 || value.length > 255) return false;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 0x21 || code > 0x7e) return false;
  }
  return true;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_HITL_RESPONSE_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_hitl_response_authority_catalog_missing',
      'desktop HITL response authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
