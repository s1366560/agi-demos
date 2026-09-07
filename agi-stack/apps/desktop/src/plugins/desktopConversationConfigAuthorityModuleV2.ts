import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type { AgentConversation, DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_CONVERSATION_CONFIG_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/conversation-config-authority';
export const DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.conversation-config-authority';
export const DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopConversationConfigIdentityV2 = Readonly<{
  id: string;
  project_id: string;
  tenant_id: string;
  workspace_id: string | null;
}>;

export type DesktopConversationConfigMutationV2 = Readonly<{
  llmModelOverride: string | null;
  llmRouteOverride: Readonly<{
    model_id: string;
    provider_id: string;
  }> | null;
}>;

export type DesktopConversationConfigOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: AgentConversation;
  llmModelOverride: string | null;
  llmRouteOverride?: Readonly<{
    model_id: string;
    provider_id: string;
  }> | null;
}>;

export interface DesktopConversationConfigAuthorityV2 {
  readonly updateModelOverride: (
    identity: DesktopConversationConfigIdentityV2,
    mutation: DesktopConversationConfigMutationV2,
  ) => Promise<AgentConversation>;
}

export interface DesktopConversationConfigAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopConversationConfigAuthorityV2;
}

export interface DesktopConversationConfigOperationsV2 {
  readonly updateModelOverride: (
    input: DesktopConversationConfigOperationInputV2,
  ) => Promise<AgentConversation>;
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

type PreparedConversationConfigOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  identity: DesktopConversationConfigIdentityV2;
  mutation: DesktopConversationConfigMutationV2;
}>;

export class DesktopConversationConfigAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopConversationConfigAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopConversationConfigAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_conversation_config_authority_config_invalid',
      'desktop conversation config authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopConversationConfigAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopConversationConfigAuthorityV2,
  });
  context.provide(DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2, service);
}

export const desktopConversationConfigAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopConversationConfigAuthorityV2,
});

export function createDesktopConversationConfigOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopConversationConfigOperationsV2 {
  return Object.freeze({
    updateModelOverride(input: DesktopConversationConfigOperationInputV2) {
      const actions = requireGenerationActionsV2(resolveActions());
      return withDesktopConversationConfigAuthorityOperationV2(
        actions,
        input,
        (authority, prepared) =>
          authority.updateModelOverride(prepared.identity, prepared.mutation),
      );
    },
  });
}

export function withDesktopConversationConfigAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopConversationConfigOperationInputV2,
  operation: (
    authority: DesktopConversationConfigAuthorityV2,
    prepared: PreparedConversationConfigOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const prepared = prepareConversationConfigOperationV2(input);
  return runDesktopConversationConfigAuthorityOperationV2(actions, prepared, operation);
}

async function runDesktopConversationConfigAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedConversationConfigOperationV2,
  operation: (
    authority: DesktopConversationConfigAuthorityV2,
    prepared: PreparedConversationConfigOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopConversationConfigAuthorityServiceV2>({
      service: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_SERVICE_V2,
      version: DESKTOP_CONVERSATION_CONFIG_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'session',
        tenant_id: prepared.identity.tenant_id,
        project_id: prepared.identity.project_id,
        session_id: prepared.identity.id,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopConversationConfigAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableDesktopConversationConfigAuthorityV2(
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

function createDesktopConversationConfigAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopConversationConfigAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    updateModelOverride(
      identity: DesktopConversationConfigIdentityV2,
      mutation: DesktopConversationConfigMutationV2,
    ) {
      const operationIdentity = cloneConversationIdentityV2(identity);
      const operationMutation = cloneConversationConfigMutationV2(mutation);
      assertConversationConfigScopeV2(operationConfig, operationIdentity);
      const payload = {
        llm_model_override: operationMutation.llmModelOverride,
        ...(operationConfig.mode === 'local'
          ? { llm_route_override: operationMutation.llmRouteOverride }
          : {}),
      };
      return transport
        .updateAgentConversationConfig(
          operationIdentity.id,
          payload,
          operationIdentity.project_id,
        )
        .then((response) => validateConversationConfigResponseV2(response, operationIdentity));
    },
  });
}

function createRevocableDesktopConversationConfigAuthorityV2(
  authority: DesktopConversationConfigAuthorityV2,
  isOperationActive: () => boolean,
): DesktopConversationConfigAuthorityV2 {
  return Object.freeze({
    updateModelOverride(
      identity: DesktopConversationConfigIdentityV2,
      mutation: DesktopConversationConfigMutationV2,
    ) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_conversation_config_operation_released',
          'desktop conversation config operation has been released',
        );
      }
      return authority.updateModelOverride(identity, mutation);
    },
  });
}

function prepareConversationConfigOperationV2(
  input: DesktopConversationConfigOperationInputV2,
): PreparedConversationConfigOperationV2 {
  if (!isRecordV2(input)) {
    throw invalidConversationConfigInputV2();
  }
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const identity = cloneConversationIdentityV2(input.conversation);
  const mutation = cloneConversationConfigMutationV2({
    llmModelOverride: input.llmModelOverride,
    llmRouteOverride: input.llmRouteOverride ?? null,
  });
  assertConversationConfigScopeV2(config, identity);
  return Object.freeze({ config, identity, mutation });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isRecordV2(config)) {
    throw invalidConversationConfigInputV2();
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
    throw invalidConversationConfigInputV2();
  }
  return Object.freeze(copy);
}

function cloneConversationIdentityV2(
  conversation: Pick<AgentConversation, 'id' | 'project_id' | 'tenant_id' | 'workspace_id'>,
): DesktopConversationConfigIdentityV2 {
  if (
    !isRecordV2(conversation) ||
    !isCanonicalStringV2(conversation.id) ||
    !isCanonicalStringV2(conversation.tenant_id) ||
    !isCanonicalStringV2(conversation.project_id)
  ) {
    throw invalidConversationConfigInputV2();
  }
  const workspaceId = cloneWorkspaceIdentityV2(conversation.workspace_id);
  if (workspaceId === undefined) {
    throw invalidConversationConfigInputV2();
  }
  return Object.freeze({
    id: conversation.id,
    tenant_id: conversation.tenant_id,
    project_id: conversation.project_id,
    workspace_id: workspaceId,
  });
}

function cloneConversationConfigMutationV2(
  mutation: DesktopConversationConfigMutationV2,
): DesktopConversationConfigMutationV2 {
  if (
    !isRecordV2(mutation) ||
    (mutation.llmModelOverride !== null &&
      !isCanonicalStringV2(mutation.llmModelOverride))
  ) {
    throw invalidConversationConfigInputV2();
  }
  const route = cloneRouteOverrideV2(mutation.llmRouteOverride);
  return Object.freeze({
    llmModelOverride: mutation.llmModelOverride,
    llmRouteOverride: route,
  });
}

function cloneRouteOverrideV2(
  route: DesktopConversationConfigMutationV2['llmRouteOverride'],
): DesktopConversationConfigMutationV2['llmRouteOverride'] {
  if (route === null || route === undefined) return null;
  if (
    !isRecordV2(route) ||
    !isCanonicalStringV2(route.provider_id) ||
    !isCanonicalStringV2(route.model_id)
  ) {
    throw invalidConversationConfigInputV2();
  }
  return Object.freeze({ provider_id: route.provider_id, model_id: route.model_id });
}

function assertConversationConfigScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopConversationConfigIdentityV2,
): void {
  if (config.tenantId !== identity.tenant_id || config.projectId !== identity.project_id) {
    throw new RuntimeV2Error(
      'desktop_conversation_config_scope_mismatch',
      'desktop conversation config operation scope differs from the conversation identity',
    );
  }
}

function validateConversationConfigResponseV2(
  response: AgentConversation,
  identity: DesktopConversationConfigIdentityV2,
): AgentConversation {
  const workspaceId = isRecordV2(response)
    ? cloneWorkspaceIdentityV2(response.workspace_id)
    : undefined;
  if (
    !isRecordV2(response) ||
    response.id !== identity.id ||
    response.tenant_id !== identity.tenant_id ||
    response.project_id !== identity.project_id ||
    workspaceId === undefined ||
    workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      'desktop_conversation_config_response_scope_mismatch',
      'desktop conversation config response differs from the requested identity',
    );
  }
  return response as AgentConversation;
}

function cloneWorkspaceIdentityV2(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return null;
  return isCanonicalStringV2(value) ? value : undefined;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopConversationConfigAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidConversationConfigInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_conversation_config_input_invalid',
    'desktop conversation config operation input is invalid',
  );
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_CONVERSATION_CONFIG_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_conversation_config_authority_catalog_missing',
      'desktop conversation config authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
