import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from "@agistack/plugin-runtime";

import { DesktopApiClient } from "../api/client";
import { loadCloudSubagentTrace } from "../features/chat/cloudSubagentTraceClient";
import type {
  AgentConversation,
  AgentTimelineItem,
  ConversationMessagesResponse,
  DesktopRuntimeConfig,
} from "../types";
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from "./desktopRendererGenerationContextV2";

export const DESKTOP_SESSION_TIMELINE_AUTHORITY_MODULE_REF_V2 =
  "builtin://memstack/desktop/session-timeline-authority";
export const DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2 =
  "service:desktop-renderer.session-timeline-authority";
export const DESKTOP_SESSION_TIMELINE_AUTHORITY_VERSION_V2 = "1.0.0";

export type DesktopSessionTimelineIdentityV2 = Readonly<{
  id: string;
  project_id: string;
  tenant_id: string;
  workspace_id: string | null;
}>;

export type DesktopSessionTimelinePageV2 = Readonly<{
  limit?: number;
  fromTimeUs?: number;
  fromCounter?: number;
  beforeTimeUs?: number;
  beforeCounter?: number;
}>;

export type DesktopSessionTimelineOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: AgentConversation;
  limit?: number;
  fromTimeUs?: number;
  fromCounter?: number;
  beforeTimeUs?: number;
  beforeCounter?: number;
  signal?: AbortSignal;
}>;

export interface DesktopSessionTimelineAuthorityV2 {
  readonly getConversationSubagentRuns: (
    identity: DesktopSessionTimelineIdentityV2,
    signal?: AbortSignal,
  ) => Promise<AgentTimelineItem[]>;
  readonly getConversationMessages: (
    identity: DesktopSessionTimelineIdentityV2,
    page: DesktopSessionTimelinePageV2,
    signal?: AbortSignal,
  ) => Promise<ConversationMessagesResponse>;
}

export interface DesktopSessionTimelineAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopSessionTimelineAuthorityV2;
}

export interface DesktopSessionTimelineOperationsV2 {
  readonly getConversationSubagentRuns: (
    input: DesktopSessionTimelineOperationInputV2,
  ) => Promise<AgentTimelineItem[]>;
  readonly getConversationMessages: (
    input: DesktopSessionTimelineOperationInputV2,
  ) => Promise<ConversationMessagesResponse>;
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

type PreparedSessionTimelineOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  identity: DesktopSessionTimelineIdentityV2;
  page: DesktopSessionTimelinePageV2;
  signal?: AbortSignal;
}>;

export class DesktopSessionTimelineAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2["reasonCode"];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = "DesktopSessionTimelineAuthorityUnavailableErrorV2";
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopSessionTimelineAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== "desktop-api-client") {
    throw new RuntimeV2Error(
      "desktop_session_timeline_authority_config_invalid",
      "desktop session timeline authority requires desktop-api-client strategy",
    );
  }
  const service: DesktopSessionTimelineAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopSessionTimelineAuthorityV2,
  });
  context.provide(DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2, service);
}

export const desktopSessionTimelineAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_SESSION_TIMELINE_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopSessionTimelineAuthorityV2,
  });

export function createDesktopSessionTimelineOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopSessionTimelineOperationsV2 {
  return Object.freeze({
    getConversationSubagentRuns(input: DesktopSessionTimelineOperationInputV2) {
      const prepared = prepareSessionTimelineOperationV2(input);
      return runDesktopSessionTimelineAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.getConversationSubagentRuns(
            prepared.identity,
            prepared.signal,
          ),
      );
    },
    getConversationMessages(input: DesktopSessionTimelineOperationInputV2) {
      const prepared = prepareSessionTimelineOperationV2(input);
      return runDesktopSessionTimelineAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.getConversationMessages(
            prepared.identity,
            prepared.page,
            prepared.signal,
          ),
      );
    },
  });
}

export function withDesktopSessionTimelineAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopSessionTimelineOperationInputV2,
  operation: (
    authority: DesktopSessionTimelineAuthorityV2,
    prepared: PreparedSessionTimelineOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopSessionTimelineAuthorityOperationV2(
    actions,
    prepareSessionTimelineOperationV2(input),
    operation,
  );
}

async function runDesktopSessionTimelineAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedSessionTimelineOperationV2,
  operation: (
    authority: DesktopSessionTimelineAuthorityV2,
    prepared: PreparedSessionTimelineOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopSessionTimelineAuthorityServiceV2>(
      {
        service: DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2,
        version: DESKTOP_SESSION_TIMELINE_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: "session",
          tenant_id: prepared.identity.tenant_id,
          project_id: prepared.identity.project_id,
          session_id: prepared.identity.id,
        }),
      },
    );
  if (admission.status === "rejected") {
    throw new DesktopSessionTimelineAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableDesktopSessionTimelineAuthorityV2(
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

function createDesktopSessionTimelineAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopSessionTimelineAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    getConversationSubagentRuns(
      identity: DesktopSessionTimelineIdentityV2,
      signal?: AbortSignal,
    ) {
      const operationIdentity = cloneSessionTimelineIdentityV2(identity);
      if (signal !== undefined && !isAbortSignalV2(signal))
        throw invalidSessionTimelineInputV2();
      assertSessionTimelineScopeV2(operationConfig, operationIdentity);
      return loadCloudSubagentTrace(operationConfig, operationIdentity, signal);
    },
    getConversationMessages(
      identity: DesktopSessionTimelineIdentityV2,
      page: DesktopSessionTimelinePageV2,
      signal?: AbortSignal,
    ) {
      const operationIdentity = cloneSessionTimelineIdentityV2(identity);
      const operationPage = cloneSessionTimelinePageV2(page);
      if (signal !== undefined && !isAbortSignalV2(signal)) {
        throw invalidSessionTimelineInputV2();
      }
      assertSessionTimelineScopeV2(operationConfig, operationIdentity);
      return transport.getConversationMessages(
        operationIdentity.id,
        operationIdentity.project_id,
        {
          ...operationPage,
          ...(signal === undefined ? {} : { signal }),
        },
      );
    },
  });
}

function createRevocableDesktopSessionTimelineAuthorityV2(
  authority: DesktopSessionTimelineAuthorityV2,
  isOperationActive: () => boolean,
): DesktopSessionTimelineAuthorityV2 {
  return Object.freeze({
    getConversationSubagentRuns(
      identity: DesktopSessionTimelineIdentityV2,
      signal?: AbortSignal,
    ) {
      if (!isOperationActive())
        throw new RuntimeV2Error(
          "desktop_session_timeline_operation_released",
          "desktop session timeline operation has been released",
        );
      return authority.getConversationSubagentRuns(identity, signal);
    },
    getConversationMessages(
      identity: DesktopSessionTimelineIdentityV2,
      page: DesktopSessionTimelinePageV2,
      signal?: AbortSignal,
    ) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          "desktop_session_timeline_operation_released",
          "desktop session timeline operation has been released",
        );
      }
      return authority.getConversationMessages(identity, page, signal);
    },
  });
}

function prepareSessionTimelineOperationV2(
  input: DesktopSessionTimelineOperationInputV2,
): PreparedSessionTimelineOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidSessionTimelineInputV2();
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const identity = cloneSessionTimelineIdentityV2(input.conversation);
  const page = cloneSessionTimelinePageV2(input);
  if (input.signal !== undefined && !isAbortSignalV2(input.signal)) {
    throw invalidSessionTimelineInputV2();
  }
  assertSessionTimelineScopeV2(config, identity);
  return Object.freeze({
    config,
    identity,
    page,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function cloneDesktopRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidSessionTimelineInputV2();
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
    (copy.mode !== "cloud" && copy.mode !== "local") ||
    !isCanonicalStringV2(copy.tenantId) ||
    !isCanonicalStringV2(copy.projectId) ||
    (copy.workspaceId !== "" && !isCanonicalStringV2(copy.workspaceId))
  ) {
    throw invalidSessionTimelineInputV2();
  }
  return Object.freeze(copy);
}

function cloneSessionTimelineIdentityV2(
  conversation: Pick<
    AgentConversation,
    "id" | "project_id" | "tenant_id" | "workspace_id"
  >,
): DesktopSessionTimelineIdentityV2 {
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
    throw invalidSessionTimelineInputV2();
  }
  return Object.freeze({
    id: conversation.id,
    tenant_id: conversation.tenant_id,
    project_id: conversation.project_id,
    workspace_id: workspaceId,
  });
}

function cloneSessionTimelinePageV2(
  page: DesktopSessionTimelinePageV2,
): DesktopSessionTimelinePageV2 {
  if (!isPlainRecordV2(page)) throw invalidSessionTimelineInputV2();
  if (
    (page.limit !== undefined &&
      (!Number.isSafeInteger(page.limit) ||
        page.limit < 1 ||
        page.limit > 500)) ||
    !isOptionalSafeIntegerV2(page.fromTimeUs) ||
    !isOptionalSafeIntegerV2(page.fromCounter) ||
    !isOptionalSafeIntegerV2(page.beforeTimeUs) ||
    !isOptionalSafeIntegerV2(page.beforeCounter)
  ) {
    throw invalidSessionTimelineInputV2();
  }
  return Object.freeze({
    ...(page.limit === undefined ? {} : { limit: page.limit }),
    ...(page.fromTimeUs === undefined ? {} : { fromTimeUs: page.fromTimeUs }),
    ...(page.fromCounter === undefined
      ? {}
      : { fromCounter: page.fromCounter }),
    ...(page.beforeTimeUs === undefined
      ? {}
      : { beforeTimeUs: page.beforeTimeUs }),
    ...(page.beforeCounter === undefined
      ? {}
      : { beforeCounter: page.beforeCounter }),
  });
}

function assertSessionTimelineScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionTimelineIdentityV2,
): void {
  const workspaceId = config.workspaceId || null;
  if (
    config.tenantId !== identity.tenant_id ||
    config.projectId !== identity.project_id ||
    workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      "desktop_session_timeline_scope_mismatch",
      "desktop session timeline scope differs from the conversation identity",
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
  throw new DesktopSessionTimelineAuthorityUnavailableErrorV2({
    reasonCode: "desktop_renderer_generation_actions_unavailable",
  });
}

function invalidSessionTimelineInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    "desktop_session_timeline_input_invalid",
    "desktop session timeline operation input is invalid",
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

function isOptionalSafeIntegerV2(value: unknown): value is number | undefined {
  return (
    value === undefined ||
    (typeof value === "number" && Number.isSafeInteger(value))
  );
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== "undefined" && value instanceof AbortSignal;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_SESSION_TIMELINE_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      "desktop_session_timeline_authority_catalog_missing",
      "desktop session timeline authority is absent from the generated catalog",
    );
  }
  return entry.contract_digest;
}
