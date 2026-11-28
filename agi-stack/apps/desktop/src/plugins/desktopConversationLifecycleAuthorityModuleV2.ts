import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from "@agistack/plugin-runtime";

import { DesktopApiClient } from "../api/client";
import type { AgentConversation, DesktopRuntimeConfig } from "../types";
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from "./desktopRendererGenerationContextV2";

export const DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_MODULE_REF_V2 =
  "builtin://memstack/desktop/conversation-lifecycle-authority";
export const DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2 =
  "service:desktop-renderer.conversation-lifecycle-authority";
export const DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_VERSION_V2 = "1.0.0";

export type DesktopConversationLifecycleIdentityV2 = Readonly<{
  id: string;
  project_id: string;
  tenant_id: string;
  workspace_id: string | null;
}>;

export type DesktopConversationLifecycleOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: AgentConversation;
}>;

export type DesktopConversationTitleOperationInputV2 =
  DesktopConversationLifecycleOperationInputV2 &
    Readonly<{
      title: string;
    }>;

export interface DesktopConversationLifecycleAuthorityV2 {
  readonly deleteAgentConversation: (
    identity: DesktopConversationLifecycleIdentityV2,
  ) => Promise<void>;
  readonly generateAgentConversationSummary: (
    identity: DesktopConversationLifecycleIdentityV2,
  ) => Promise<AgentConversation>;
  readonly updateAgentConversationTitle: (
    identity: DesktopConversationLifecycleIdentityV2,
    title: string,
  ) => Promise<AgentConversation>;
}

export interface DesktopConversationLifecycleAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopConversationLifecycleAuthorityV2;
}

export interface DesktopConversationLifecycleOperationsV2 {
  readonly deleteAgentConversation: (
    input: DesktopConversationLifecycleOperationInputV2,
  ) => Promise<void>;
  readonly generateAgentConversationSummary: (
    input: DesktopConversationLifecycleOperationInputV2,
  ) => Promise<AgentConversation>;
  readonly updateAgentConversationTitle: (
    input: DesktopConversationTitleOperationInputV2,
  ) => Promise<AgentConversation>;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: "rejected" }
>;

type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: "desktop_renderer_generation_actions_unavailable";
  runtimeCode?: undefined;
}>;

type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

type PreparedConversationLifecycleOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  identity: DesktopConversationLifecycleIdentityV2;
}>;

type PreparedConversationTitleOperationV2 =
  PreparedConversationLifecycleOperationV2 &
    Readonly<{
      title: string;
    }>;

export class DesktopConversationLifecycleAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2["reasonCode"];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = "DesktopConversationLifecycleAuthorityUnavailableErrorV2";
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopConversationLifecycleAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== "desktop-api-client") {
    throw new RuntimeV2Error(
      "desktop_conversation_lifecycle_authority_config_invalid",
      "desktop conversation lifecycle authority requires desktop-api-client strategy",
    );
  }
  const service: DesktopConversationLifecycleAuthorityServiceV2 = Object.freeze(
    {
      bindOperation: createDesktopConversationLifecycleAuthorityV2,
    },
  );
  context.provide(DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2, service);
}

export const desktopConversationLifecycleAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopConversationLifecycleAuthorityV2,
  });

export function createDesktopConversationLifecycleOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopConversationLifecycleOperationsV2 {
  return Object.freeze({
    deleteAgentConversation(
      input: DesktopConversationLifecycleOperationInputV2,
    ) {
      const prepared = prepareConversationLifecycleOperationV2(input);
      return runDesktopConversationLifecycleAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.deleteAgentConversation(prepared.identity),
      );
    },
    generateAgentConversationSummary(
      input: DesktopConversationLifecycleOperationInputV2,
    ) {
      const prepared = prepareConversationLifecycleOperationV2(input);
      return runDesktopConversationLifecycleAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.generateAgentConversationSummary(prepared.identity),
      );
    },
    updateAgentConversationTitle(
      input: DesktopConversationTitleOperationInputV2,
    ) {
      const prepared = prepareConversationTitleOperationV2(input);
      return runDesktopConversationLifecycleAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.updateAgentConversationTitle(
            prepared.identity,
            prepared.title,
          ),
      );
    },
  });
}

export function withDesktopConversationLifecycleAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopConversationLifecycleOperationInputV2,
  operation: (
    authority: DesktopConversationLifecycleAuthorityV2,
    prepared: PreparedConversationLifecycleOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const prepared = prepareConversationLifecycleOperationV2(input);
  return runDesktopConversationLifecycleAuthorityOperationV2(
    actions,
    prepared,
    operation,
  );
}

async function runDesktopConversationLifecycleAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedConversationLifecycleOperationV2,
  operation: (
    authority: DesktopConversationLifecycleAuthorityV2,
    prepared: PreparedConversationLifecycleOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopConversationLifecycleAuthorityServiceV2>(
      {
        service: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_SERVICE_V2,
        version: DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: "session",
          tenant_id: prepared.identity.tenant_id,
          project_id: prepared.identity.project_id,
          session_id: prepared.identity.id,
        }),
      },
    );
  if (admission.status === "rejected") {
    throw new DesktopConversationLifecycleAuthorityUnavailableErrorV2(
      admission,
    );
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableDesktopConversationLifecycleAuthorityV2(
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

function createDesktopConversationLifecycleAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopConversationLifecycleAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    deleteAgentConversation(identity: DesktopConversationLifecycleIdentityV2) {
      const operationIdentity = cloneConversationLifecycleIdentityV2(identity);
      assertConversationLifecycleScopeV2(operationConfig, operationIdentity);
      return transport.deleteAgentConversation(
        operationIdentity.id,
        operationIdentity.project_id,
      );
    },
    generateAgentConversationSummary(
      identity: DesktopConversationLifecycleIdentityV2,
    ) {
      const operationIdentity = cloneConversationLifecycleIdentityV2(identity);
      assertConversationLifecycleScopeV2(operationConfig, operationIdentity);
      return transport
        .generateAgentConversationSummary(
          operationIdentity.id,
          operationIdentity.project_id,
          operationIdentity.workspace_id ?? "",
        )
        .then((response) =>
          validateConversationLifecycleResponseV2(response, operationIdentity),
        );
    },
    updateAgentConversationTitle(
      identity: DesktopConversationLifecycleIdentityV2,
      title: string,
    ) {
      const operationIdentity = cloneConversationLifecycleIdentityV2(identity);
      const operationTitle = cloneConversationTitleV2(title);
      assertConversationLifecycleScopeV2(operationConfig, operationIdentity);
      return transport
        .updateAgentConversationTitle(
          operationIdentity.id,
          operationTitle,
          operationIdentity.project_id,
          operationIdentity.workspace_id ?? "",
        )
        .then((response) => {
          const validated = validateConversationLifecycleResponseV2(
            response,
            operationIdentity,
          );
          if (validated.title !== operationTitle) {
            throw new RuntimeV2Error(
              "desktop_conversation_lifecycle_response_title_mismatch",
              "desktop conversation lifecycle response title differs from the request",
            );
          }
          return validated;
        });
    },
  });
}

function createRevocableDesktopConversationLifecycleAuthorityV2(
  authority: DesktopConversationLifecycleAuthorityV2,
  isOperationActive: () => boolean,
): DesktopConversationLifecycleAuthorityV2 {
  const requireActive = (): void => {
    if (!isOperationActive()) {
      throw new RuntimeV2Error(
        "desktop_conversation_lifecycle_operation_released",
        "desktop conversation lifecycle operation has been released",
      );
    }
  };
  return Object.freeze({
    deleteAgentConversation(identity: DesktopConversationLifecycleIdentityV2) {
      requireActive();
      return authority.deleteAgentConversation(identity);
    },
    generateAgentConversationSummary(
      identity: DesktopConversationLifecycleIdentityV2,
    ) {
      requireActive();
      return authority.generateAgentConversationSummary(identity);
    },
    updateAgentConversationTitle(
      identity: DesktopConversationLifecycleIdentityV2,
      title: string,
    ) {
      requireActive();
      return authority.updateAgentConversationTitle(identity, title);
    },
  });
}

function prepareConversationLifecycleOperationV2(
  input: DesktopConversationLifecycleOperationInputV2,
): PreparedConversationLifecycleOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidConversationLifecycleInputV2();
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const identity = cloneConversationLifecycleIdentityV2(input.conversation);
  assertConversationLifecycleScopeV2(config, identity);
  return Object.freeze({ config, identity });
}

function prepareConversationTitleOperationV2(
  input: DesktopConversationTitleOperationInputV2,
): PreparedConversationTitleOperationV2 {
  const prepared = prepareConversationLifecycleOperationV2(input);
  const title = cloneConversationTitleV2(input.title);
  return Object.freeze({ ...prepared, title });
}

function cloneDesktopRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidConversationLifecycleInputV2();
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
    Object.values(copy).some((value) => typeof value !== "string") ||
    (copy.mode !== "cloud" && copy.mode !== "local")
  ) {
    throw invalidConversationLifecycleInputV2();
  }
  return Object.freeze(copy);
}

function cloneConversationLifecycleIdentityV2(
  conversation: Pick<
    AgentConversation,
    "id" | "project_id" | "tenant_id" | "workspace_id"
  >,
): DesktopConversationLifecycleIdentityV2 {
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
    throw invalidConversationLifecycleInputV2();
  }
  return Object.freeze({
    id: conversation.id,
    tenant_id: conversation.tenant_id,
    project_id: conversation.project_id,
    workspace_id: workspaceId,
  });
}

function cloneConversationTitleV2(title: unknown): string {
  if (typeof title !== "string") throw invalidConversationLifecycleInputV2();
  const normalized = title.trim();
  if (!normalized) throw invalidConversationLifecycleInputV2();
  return normalized;
}

function assertConversationLifecycleScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopConversationLifecycleIdentityV2,
): void {
  const workspaceId = config.workspaceId.trim() || null;
  if (
    config.tenantId !== identity.tenant_id ||
    config.projectId !== identity.project_id ||
    workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      "desktop_conversation_lifecycle_scope_mismatch",
      "desktop conversation lifecycle operation scope differs from the conversation identity",
    );
  }
}

function validateConversationLifecycleResponseV2(
  response: AgentConversation,
  identity: DesktopConversationLifecycleIdentityV2,
): AgentConversation {
  const workspaceId = isPlainRecordV2(response)
    ? cloneWorkspaceIdentityV2(response.workspace_id)
    : undefined;
  if (
    !isPlainRecordV2(response) ||
    response.id !== identity.id ||
    response.tenant_id !== identity.tenant_id ||
    response.project_id !== identity.project_id ||
    workspaceId === undefined ||
    workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      "desktop_conversation_lifecycle_response_scope_mismatch",
      "desktop conversation lifecycle response differs from the requested identity",
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
  throw new DesktopConversationLifecycleAuthorityUnavailableErrorV2({
    reasonCode: "desktop_renderer_generation_actions_unavailable",
  });
}

function invalidConversationLifecycleInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    "desktop_conversation_lifecycle_input_invalid",
    "desktop conversation lifecycle operation input is invalid",
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return (
    typeof value === "string" && value.length > 0 && value === value.trim()
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref ===
      DESKTOP_CONVERSATION_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      "desktop_conversation_lifecycle_authority_catalog_missing",
      "desktop conversation lifecycle authority is absent from the generated catalog",
    );
  }
  return entry.contract_digest;
}
