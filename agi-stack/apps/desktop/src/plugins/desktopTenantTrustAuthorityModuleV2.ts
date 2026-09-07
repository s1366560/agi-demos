import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from "@agistack/plugin-runtime";

import type { DesktopRuntimeConfig } from "../types";
import type { TenantAdminRequestOptions } from "../features/tenant-admin/tenantAdminHttp";
import type {
  TenantTrustClient,
  TenantTrustPolicy,
  TenantTrustSnapshot,
} from "../features/tenant-admin/tenantTrustClient";
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from "./desktopRendererGenerationContextV2";
import { createDesktopTenantTrustHttpProjectionV2 } from "./desktopTenantTrustHttpProjectionV2";
import {
  freezeTenantTrustConfigV2,
  prepareTenantTrustCreateV2,
  prepareTenantTrustLoadV2,
  prepareTenantTrustRevokeV2,
  requireTenantTrustPolicyV2,
  requireTenantTrustSnapshotV2,
  type DesktopTenantTrustCreateInputV2,
  type DesktopTenantTrustLoadInputV2,
  type DesktopTenantTrustRevokeInputV2,
} from "./desktopTenantTrustOperationContractV2";

export const DESKTOP_TENANT_TRUST_AUTHORITY_MODULE_REF_V2 =
  "builtin://memstack/desktop/tenant-trust-authority";
export const DESKTOP_TENANT_TRUST_AUTHORITY_SERVICE_V2 =
  "service:desktop-renderer.tenant-trust-authority";
export const DESKTOP_TENANT_TRUST_AUTHORITY_VERSION_V2 = "1.0.0";

export interface DesktopTenantTrustAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): TenantTrustClient;
}
export interface DesktopTenantTrustOperationsV2 {
  loadTenantTrustPolicies(
    input: DesktopTenantTrustLoadInputV2,
  ): Promise<TenantTrustSnapshot>;
  createTenantTrustPolicy(
    input: DesktopTenantTrustCreateInputV2,
  ): Promise<TenantTrustPolicy>;
  revokeTenantTrustPolicy(
    input: DesktopTenantTrustRevokeInputV2,
  ): Promise<TenantTrustPolicy>;
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
export class DesktopTenantTrustAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode;
  readonly runtimeCode;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = "DesktopTenantTrustAuthorityUnavailableErrorV2";
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}
export function applyDesktopTenantTrustAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (
    Object.keys(config).length !== 1 ||
    config.strategy !== "desktop-api-fetch"
  )
    throw new RuntimeV2Error(
      "desktop_tenant_trust_authority_config_invalid",
      "desktop tenant trust authority requires desktop-api-fetch strategy",
    );
  context.provide(
    DESKTOP_TENANT_TRUST_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopTenantTrustHttpProjectionV2 }),
  );
}
export const desktopTenantTrustAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_TRUST_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopTenantTrustAuthorityV2,
  });
export function createDesktopTenantTrustOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantTrustOperationsV2 {
  return Object.freeze({
    loadTenantTrustPolicies(input: DesktopTenantTrustLoadInputV2) {
      const p = prepareTenantTrustLoadV2(input);
      return run(resolve, p, async (a) =>
        requireTenantTrustSnapshotV2(
          await a.load(p.scope, options(p.signal)),
          p.scope,
        ),
      );
    },
    createTenantTrustPolicy(input: DesktopTenantTrustCreateInputV2) {
      const p = prepareTenantTrustCreateV2(input);
      return run(resolve, p, async (a) =>
        requireTenantTrustPolicyV2(
          await a.create(p.scope, p.policy, options(p.signal)),
          p.scope,
        ),
      );
    },
    revokeTenantTrustPolicy(input: DesktopTenantTrustRevokeInputV2) {
      const p = prepareTenantTrustRevokeV2(input);
      return run(resolve, p, async (a) =>
        requireTenantTrustPolicyV2(
          await a.revoke(p.scope, p.policyId, options(p.signal)),
          p.scope,
        ),
      );
    },
  });
}
export function createDesktopTenantTrustClientV2(
  operations: DesktopTenantTrustOperationsV2,
  config: DesktopRuntimeConfig,
): TenantTrustClient {
  const frozen = freezeTenantTrustConfigV2(config);
  return Object.freeze({
    load: (scope, request) =>
      operations.loadTenantTrustPolicies({
        config: frozen,
        scope,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
    create: (scope, policy, request) =>
      operations.createTenantTrustPolicy({
        config: frozen,
        scope,
        policy,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
    revoke: (scope, policyId, request) =>
      operations.revokeTenantTrustPolicy({
        config: frozen,
        scope,
        policyId,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
  });
}
async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantTrustLoadInputV2,
  operation: (authority: TenantTrustClient) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions)
    throw new DesktopTenantTrustAuthorityUnavailableErrorV2({
      reasonCode: "desktop_renderer_generation_actions_unavailable",
    });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantTrustAuthorityServiceV2>(
      {
        service: DESKTOP_TENANT_TRUST_AUTHORITY_SERVICE_V2,
        version: DESKTOP_TENANT_TRUST_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: "tenant",
          tenant_id: prepared.scope.tenantId,
        }),
      },
    );
  if (admission.status === "rejected")
    throw new DesktopTenantTrustAuthorityUnavailableErrorV2(admission);
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
        Object.keys(raw).length !== 3 ||
        typeof raw.load !== "function" ||
        typeof raw.create !== "function" ||
        typeof raw.revoke !== "function"
      )
        throw invalidService();
      const authority = Object.freeze({
        load: (...args: Parameters<TenantTrustClient["load"]>) => {
          assertActive(active);
          return raw.load(...args);
        },
        create: (...args: Parameters<TenantTrustClient["create"]>) => {
          assertActive(active);
          return raw.create(...args);
        },
        revoke: (...args: Parameters<TenantTrustClient["revoke"]>) => {
          assertActive(active);
          return raw.revoke(...args);
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
function options(signal?: AbortSignal): TenantAdminRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}
function assertActive(active: boolean) {
  if (!active)
    throw new RuntimeV2Error(
      "desktop_tenant_trust_operation_released",
      "desktop tenant trust operation released",
    );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function invalidService() {
  return new RuntimeV2Error(
    "desktop_tenant_trust_service_invalid",
    "desktop tenant trust authority service invalid",
  );
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_TRUST_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      "desktop_tenant_trust_authority_catalog_missing",
      "desktop tenant trust authority absent from catalog",
    );
  return entry.contract_digest;
}
