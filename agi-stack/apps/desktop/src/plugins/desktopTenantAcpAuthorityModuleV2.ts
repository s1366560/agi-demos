import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from "@agistack/plugin-runtime";
import type { DesktopRuntimeConfig } from "../types";
import type {
  TenantAcpAgent,
  TenantAcpClient,
  TenantAcpSnapshot,
} from "../features/tenant-admin/tenantAcpClient";
import type { TenantManagementRequestOptions } from "../features/tenant-admin/tenantManagementHttp";
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from "./desktopRendererGenerationContextV2";
import { createDesktopTenantAcpHttpProjectionV2 } from "./desktopTenantAcpHttpProjectionV2";
import {
  freezeTenantAcpConfigV2,
  prepareTenantAcpCreateV2,
  prepareTenantAcpDeleteV2,
  prepareTenantAcpLoadV2,
  prepareTenantAcpTestV2,
  prepareTenantAcpUpdateV2,
  requireTenantAcpAgentV2,
  requireTenantAcpSnapshotV2,
  requireTenantAcpTestResultV2,
  type DesktopTenantAcpCreateInputV2,
  type DesktopTenantAcpDeleteInputV2,
  type DesktopTenantAcpLoadInputV2,
  type DesktopTenantAcpTestOperationInputV2,
  type DesktopTenantAcpUpdateInputV2,
} from "./desktopTenantAcpOperationContractV2";

export const DESKTOP_TENANT_ACP_AUTHORITY_MODULE_REF_V2 =
  "builtin://memstack/desktop/tenant-acp-authority";
export const DESKTOP_TENANT_ACP_AUTHORITY_SERVICE_V2 =
  "service:desktop-renderer.tenant-acp-authority";
export const DESKTOP_TENANT_ACP_AUTHORITY_VERSION_V2 = "1.0.0";
export interface DesktopTenantAcpAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): TenantAcpClient;
}
export interface DesktopTenantAcpOperationsV2 {
  loadTenantAcp(input: DesktopTenantAcpLoadInputV2): Promise<TenantAcpSnapshot>;
  createTenantAcpAgent(
    input: DesktopTenantAcpCreateInputV2,
  ): Promise<TenantAcpAgent>;
  updateTenantAcpAgent(
    input: DesktopTenantAcpUpdateInputV2,
  ): Promise<TenantAcpAgent>;
  deleteTenantAcpAgent(input: DesktopTenantAcpDeleteInputV2): Promise<void>;
  testTenantAcpAgent(
    input: DesktopTenantAcpTestOperationInputV2,
  ): Promise<Readonly<Record<string, unknown>>>;
}
type Rejection =
  | Extract<
      DesktopRendererServiceOperationLeaseAdmissionV2<never>,
      { status: "rejected" }
    >
  | Readonly<{
      reasonCode: "desktop_renderer_generation_actions_unavailable";
      runtimeCode?: undefined;
    }>;
export class DesktopTenantAcpAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode;
  readonly runtimeCode;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = "DesktopTenantAcpAuthorityUnavailableErrorV2";
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}
export function applyDesktopTenantAcpAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (
    Object.keys(config).length !== 1 ||
    config.strategy !== "desktop-api-fetch"
  )
    throw new RuntimeV2Error(
      "desktop_tenant_acp_authority_config_invalid",
      "desktop tenant ACP authority requires desktop-api-fetch strategy",
    );
  context.provide(
    DESKTOP_TENANT_ACP_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopTenantAcpHttpProjectionV2 }),
  );
}
export const desktopTenantAcpAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_ACP_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopTenantAcpAuthorityV2,
  });
export function createDesktopTenantAcpOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantAcpOperationsV2 {
  return Object.freeze({
    loadTenantAcp(input: DesktopTenantAcpLoadInputV2) {
      const p = prepareTenantAcpLoadV2(input);
      return run(resolve, p, (a) =>
        a
          .load(p.scope, options(p.signal))
          .then((v) => requireTenantAcpSnapshotV2(v, p.scope)),
      );
    },
    createTenantAcpAgent(input: DesktopTenantAcpCreateInputV2) {
      const p = prepareTenantAcpCreateV2(input);
      return run(resolve, p, (a) =>
        a
          .createAgent(
            p.scope,
            p.agent as Parameters<TenantAcpClient["createAgent"]>[1],
            options(p.signal),
          )
          .then(requireTenantAcpAgentV2),
      );
    },
    updateTenantAcpAgent(input: DesktopTenantAcpUpdateInputV2) {
      const p = prepareTenantAcpUpdateV2(input);
      return run(resolve, p, (a) =>
        a
          .updateAgent(p.scope, p.agentKey, p.agent, options(p.signal))
          .then(requireTenantAcpAgentV2),
      );
    },
    deleteTenantAcpAgent(input: DesktopTenantAcpDeleteInputV2) {
      const p = prepareTenantAcpDeleteV2(input);
      return run(resolve, p, (a) =>
        a.deleteAgent(p.scope, p.agentKey, options(p.signal)),
      );
    },
    testTenantAcpAgent(input: DesktopTenantAcpTestOperationInputV2) {
      const p = prepareTenantAcpTestV2(input);
      return run(resolve, p, (a) =>
        a
          .testAgent(p.scope, p.agentKey, p.test, options(p.signal))
          .then(requireTenantAcpTestResultV2),
      );
    },
  });
}
export function createDesktopTenantAcpClientV2(
  operations: DesktopTenantAcpOperationsV2,
  config: DesktopRuntimeConfig,
): TenantAcpClient {
  const frozen = freezeTenantAcpConfigV2(config);
  return Object.freeze({
    load: (scope, request) =>
      operations.loadTenantAcp({
        config: frozen,
        scope,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
    createAgent: (scope, agent, request) =>
      operations.createTenantAcpAgent({
        config: frozen,
        scope,
        agent,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
    updateAgent: (scope, agentKey, agent, request) =>
      operations.updateTenantAcpAgent({
        config: frozen,
        scope,
        agentKey,
        agent,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
    deleteAgent: (scope, agentKey, request) =>
      operations.deleteTenantAcpAgent({
        config: frozen,
        scope,
        agentKey,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
    testAgent: (scope, agentKey, test, request) =>
      operations.testTenantAcpAgent({
        config: frozen,
        scope,
        agentKey,
        test,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
  });
}
async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantAcpLoadInputV2,
  operation: (authority: TenantAcpClient) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions)
    throw new DesktopTenantAcpAuthorityUnavailableErrorV2({
      reasonCode: "desktop_renderer_generation_actions_unavailable",
    });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantAcpAuthorityServiceV2>(
      {
        service: DESKTOP_TENANT_ACP_AUTHORITY_SERVICE_V2,
        version: DESKTOP_TENANT_ACP_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: "tenant",
          tenant_id: prepared.scope.tenantId,
        }),
      },
    );
  if (admission.status === "rejected")
    throw new DesktopTenantAcpAuthorityUnavailableErrorV2(admission);
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      if (
        !record(candidate) ||
        Object.keys(candidate).length !== 1 ||
        typeof candidate.bindOperation !== "function"
      )
        throw invalidService();
      const raw = candidate.bindOperation(prepared.config);
      if (
        !record(raw) ||
        Object.keys(raw).length !== 5 ||
        typeof raw.load !== "function" ||
        typeof raw.createAgent !== "function" ||
        typeof raw.updateAgent !== "function" ||
        typeof raw.deleteAgent !== "function" ||
        typeof raw.testAgent !== "function"
      )
        throw invalidService();
      const authority = Object.freeze({
        load: (...args: Parameters<TenantAcpClient["load"]>) => {
          assertActive(active);
          return raw.load(...args);
        },
        createAgent: (...args: Parameters<TenantAcpClient["createAgent"]>) => {
          assertActive(active);
          return raw.createAgent(...args);
        },
        updateAgent: (...args: Parameters<TenantAcpClient["updateAgent"]>) => {
          assertActive(active);
          return raw.updateAgent(...args);
        },
        deleteAgent: (...args: Parameters<TenantAcpClient["deleteAgent"]>) => {
          assertActive(active);
          return raw.deleteAgent(...args);
        },
        testAgent: (...args: Parameters<TenantAcpClient["testAgent"]>) => {
          assertActive(active);
          return raw.testAgent(...args);
        },
      });
      const result = await operation(authority);
      assertActive(active);
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}
function options(
  signal?: AbortSignal,
): TenantManagementRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}
function assertActive(active: boolean) {
  if (!active)
    throw new RuntimeV2Error(
      "desktop_tenant_acp_operation_released",
      "desktop tenant ACP operation released",
    );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function invalidService() {
  return new RuntimeV2Error(
    "desktop_tenant_acp_service_invalid",
    "desktop tenant ACP authority service invalid",
  );
}
function generatedDigest() {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_ACP_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      "desktop_tenant_acp_authority_catalog_missing",
      "desktop tenant ACP authority absent from catalog",
    );
  return entry.contract_digest;
}
