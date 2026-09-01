import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from "@agistack/plugin-runtime";

import { DesktopApiClient } from "../api/client";
import type { DesktopRuntimeConfig, WorkspaceSummary } from "../types";
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from "./desktopRendererGenerationContextV2";

export const DESKTOP_WORKSPACE_CATALOG_AUTHORITY_MODULE_REF_V2 =
  "builtin://memstack/desktop/workspace-catalog-authority";
export const DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2 =
  "service:desktop-renderer.workspace-catalog-authority";
export const DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2 = "1.0.0";

export type DesktopWorkspaceCatalogOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  signal?: AbortSignal;
}>;

export interface DesktopWorkspaceCatalogAuthorityV2 {
  readonly listWorkspacesForProject: (
    signal?: AbortSignal,
  ) => Promise<WorkspaceSummary[]>;
}

export interface DesktopWorkspaceCatalogAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceCatalogAuthorityV2;
}

export interface DesktopWorkspaceCatalogOperationsV2 {
  readonly listWorkspacesForProject: (
    input: DesktopWorkspaceCatalogOperationInputV2,
  ) => Promise<WorkspaceSummary[]>;
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

type PreparedWorkspaceCatalogOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  signal?: AbortSignal;
}>;

export class DesktopWorkspaceCatalogAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2["reasonCode"];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = "DesktopWorkspaceCatalogAuthorityUnavailableErrorV2";
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceCatalogAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== "desktop-api-client") {
    throw new RuntimeV2Error(
      "desktop_workspace_catalog_authority_config_invalid",
      "desktop workspace catalog authority requires desktop-api-client strategy",
    );
  }
  const service: DesktopWorkspaceCatalogAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceCatalogAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceCatalogAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopWorkspaceCatalogAuthorityV2,
  });

export function createDesktopWorkspaceCatalogOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkspaceCatalogOperationsV2 {
  return Object.freeze({
    listWorkspacesForProject(input: DesktopWorkspaceCatalogOperationInputV2) {
      const prepared = prepareWorkspaceCatalogOperationV2(input);
      return runDesktopWorkspaceCatalogAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listWorkspacesForProject(prepared.signal),
      );
    },
  });
}

export function withDesktopWorkspaceCatalogAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopWorkspaceCatalogOperationInputV2,
  operation: (
    authority: DesktopWorkspaceCatalogAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopWorkspaceCatalogAuthorityOperationV2(
    actions,
    prepareWorkspaceCatalogOperationV2(input),
    operation,
  );
}

async function runDesktopWorkspaceCatalogAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedWorkspaceCatalogOperationV2,
  operation: (
    authority: DesktopWorkspaceCatalogAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceCatalogAuthorityServiceV2>(
      {
        service: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: "project",
          tenant_id: prepared.config.tenantId,
          project_id: prepared.config.projectId,
        }),
      },
    );
  if (admission.status === "rejected") {
    throw new DesktopWorkspaceCatalogAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableDesktopWorkspaceCatalogAuthorityV2(
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

function createDesktopWorkspaceCatalogAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceCatalogAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    listWorkspacesForProject: (signal?: AbortSignal) =>
      transport.listWorkspacesForProject(
        operationConfig.projectId,
        operationConfig.tenantId,
        signal,
      ),
  });
}

function createRevocableDesktopWorkspaceCatalogAuthorityV2(
  authority: DesktopWorkspaceCatalogAuthorityV2,
  isOperationActive: () => boolean,
): DesktopWorkspaceCatalogAuthorityV2 {
  return Object.freeze({
    listWorkspacesForProject: (signal?: AbortSignal) => {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          "desktop_workspace_catalog_operation_released",
          "desktop workspace catalog operation has been released",
        );
      }
      return authority.listWorkspacesForProject(signal);
    },
  });
}

function prepareWorkspaceCatalogOperationV2(
  input: DesktopWorkspaceCatalogOperationInputV2,
): PreparedWorkspaceCatalogOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidWorkspaceCatalogInputV2();
  const config = cloneDesktopRuntimeConfigV2(input.config);
  if (
    !isCanonicalStringV2(config.tenantId) ||
    !isCanonicalStringV2(config.projectId) ||
    config.workspaceId !== ""
  ) {
    throw invalidWorkspaceCatalogInputV2();
  }
  return Object.freeze({
    config,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function cloneDesktopRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidWorkspaceCatalogInputV2();
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
    throw invalidWorkspaceCatalogInputV2();
  }
  return Object.freeze(copy);
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceCatalogAuthorityUnavailableErrorV2({
    reasonCode: "desktop_renderer_generation_actions_unavailable",
  });
}

function invalidWorkspaceCatalogInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    "desktop_workspace_catalog_input_invalid",
    "desktop workspace catalog operation input is invalid",
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
      DESKTOP_WORKSPACE_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      "desktop_workspace_catalog_authority_catalog_missing",
      "desktop workspace catalog authority is absent from the generated catalog",
    );
  }
  return entry.contract_digest;
}
