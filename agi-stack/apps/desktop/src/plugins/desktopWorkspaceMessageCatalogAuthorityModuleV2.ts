import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from "@agistack/plugin-runtime";

import { DesktopApiClient } from "../api/client";
import type { DesktopRuntimeConfig, WorkspaceMessage } from "../types";
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from "./desktopRendererGenerationContextV2";

export const DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_MODULE_REF_V2 =
  "builtin://memstack/desktop/workspace-message-catalog-authority";
export const DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2 =
  "service:desktop-renderer.workspace-message-catalog-authority";
export const DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_VERSION_V2 = "1.0.0";

export type DesktopWorkspaceMessageCatalogOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  signal?: AbortSignal;
}>;

export interface DesktopWorkspaceMessageCatalogAuthorityV2 {
  readonly listMessages: (signal?: AbortSignal) => Promise<WorkspaceMessage[]>;
}

export interface DesktopWorkspaceMessageCatalogAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceMessageCatalogAuthorityV2;
}

export interface DesktopWorkspaceMessageCatalogOperationsV2 {
  readonly listMessages: (
    input: DesktopWorkspaceMessageCatalogOperationInputV2,
  ) => Promise<WorkspaceMessage[]>;
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

type PreparedWorkspaceMessageCatalogOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  signal?: AbortSignal;
}>;

export class DesktopWorkspaceMessageCatalogAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2["reasonCode"];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = "DesktopWorkspaceMessageCatalogAuthorityUnavailableErrorV2";
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceMessageCatalogAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== "desktop-api-client") {
    throw new RuntimeV2Error(
      "desktop_workspace_message_catalog_authority_config_invalid",
      "desktop workspace message catalog authority requires desktop-api-client strategy",
    );
  }
  const service: DesktopWorkspaceMessageCatalogAuthorityServiceV2 =
    Object.freeze({
      bindOperation: createDesktopWorkspaceMessageCatalogAuthorityV2,
    });
  context.provide(
    DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2,
    service,
  );
}

export const desktopWorkspaceMessageCatalogAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopWorkspaceMessageCatalogAuthorityV2,
  });

export function createDesktopWorkspaceMessageCatalogOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkspaceMessageCatalogOperationsV2 {
  return Object.freeze({
    listMessages(input: DesktopWorkspaceMessageCatalogOperationInputV2) {
      const prepared = prepareWorkspaceMessageCatalogOperationV2(input);
      return runDesktopWorkspaceMessageCatalogAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listMessages(prepared.signal),
      );
    },
  });
}

export function withDesktopWorkspaceMessageCatalogAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopWorkspaceMessageCatalogOperationInputV2,
  operation: (
    authority: DesktopWorkspaceMessageCatalogAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopWorkspaceMessageCatalogAuthorityOperationV2(
    actions,
    prepareWorkspaceMessageCatalogOperationV2(input),
    operation,
  );
}

async function runDesktopWorkspaceMessageCatalogAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedWorkspaceMessageCatalogOperationV2,
  operation: (
    authority: DesktopWorkspaceMessageCatalogAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceMessageCatalogAuthorityServiceV2>(
      {
        service: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: "project",
          tenant_id: prepared.config.tenantId,
          project_id: prepared.config.projectId,
        }),
      },
    );
  if (admission.status === "rejected") {
    throw new DesktopWorkspaceMessageCatalogAuthorityUnavailableErrorV2(
      admission,
    );
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableDesktopWorkspaceMessageCatalogAuthorityV2(
          service.bindOperation(prepared.config),
          () => operationActive,
        ),
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

function createDesktopWorkspaceMessageCatalogAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceMessageCatalogAuthorityV2 {
  const transport = new DesktopApiClient(cloneDesktopRuntimeConfigV2(config));
  return Object.freeze({
    listMessages: (signal?: AbortSignal) => transport.listMessages(signal),
  });
}

function createRevocableDesktopWorkspaceMessageCatalogAuthorityV2(
  authority: DesktopWorkspaceMessageCatalogAuthorityV2,
  isOperationActive: () => boolean,
): DesktopWorkspaceMessageCatalogAuthorityV2 {
  return Object.freeze({
    listMessages: (signal?: AbortSignal) => {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          "desktop_workspace_message_catalog_operation_released",
          "desktop workspace message catalog operation has been released",
        );
      }
      return authority.listMessages(signal);
    },
  });
}

function prepareWorkspaceMessageCatalogOperationV2(
  input: DesktopWorkspaceMessageCatalogOperationInputV2,
): PreparedWorkspaceMessageCatalogOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidWorkspaceMessageCatalogInputV2();
  const config = cloneDesktopRuntimeConfigV2(input.config);
  if (
    !isCanonicalStringV2(config.tenantId) ||
    !isCanonicalStringV2(config.projectId) ||
    !isCanonicalStringV2(config.workspaceId)
  ) {
    throw invalidWorkspaceMessageCatalogInputV2();
  }
  return Object.freeze({
    config,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function cloneDesktopRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidWorkspaceMessageCatalogInputV2();
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
    throw invalidWorkspaceMessageCatalogInputV2();
  }
  return Object.freeze(copy);
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceMessageCatalogAuthorityUnavailableErrorV2({
    reasonCode: "desktop_renderer_generation_actions_unavailable",
  });
}

function invalidWorkspaceMessageCatalogInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    "desktop_workspace_message_catalog_input_invalid",
    "desktop workspace message catalog operation input is invalid",
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
      DESKTOP_WORKSPACE_MESSAGE_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      "desktop_workspace_message_catalog_authority_catalog_missing",
      "desktop workspace message catalog authority is absent from the generated catalog",
    );
  }
  return entry.contract_digest;
}
