import { RuntimeV2Error } from "@agistack/plugin-runtime";

import type { DesktopRuntimeConfig } from "../types";
import type {
  TenantTrustPolicy,
  TenantTrustPolicyInput,
  TenantTrustScope,
  TenantTrustSnapshot,
} from "../features/tenant-admin/tenantTrustClient";

export type DesktopTenantTrustLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantTrustScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantTrustCreateInputV2 = DesktopTenantTrustLoadInputV2 &
  Readonly<{ policy: TenantTrustPolicyInput }>;
export type DesktopTenantTrustRevokeInputV2 = DesktopTenantTrustLoadInputV2 &
  Readonly<{ policyId: string }>;

const CONFIG_KEYS = Object.freeze([
  "apiBaseUrl",
  "deviceAuthorizationBaseUrl",
  "apiKey",
  "localApiToken",
  "tenantId",
  "projectId",
  "workspaceId",
  "mode",
  "workspaceRoot",
]);

export function prepareTenantTrustLoadV2(input: DesktopTenantTrustLoadInputV2) {
  return Object.freeze(common(input));
}
export function prepareTenantTrustCreateV2(
  input: DesktopTenantTrustCreateInputV2,
) {
  const prepared = common(input);
  if (!record(input.policy) || Object.keys(input.policy).length !== 3)
    throw invalidInput();
  const grantType = input.policy.grantType;
  if (grantType !== "once" && grantType !== "always") throw invalidInput();
  return Object.freeze({
    ...prepared,
    policy: Object.freeze({
      agentInstanceId: identifier(input.policy.agentInstanceId),
      actionType: identifier(input.policy.actionType),
      grantType,
    }),
  });
}
export function prepareTenantTrustRevokeV2(
  input: DesktopTenantTrustRevokeInputV2,
) {
  return Object.freeze({
    ...common(input),
    policyId: identifier(input.policyId),
  });
}
export function freezeTenantTrustConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !record(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== "cloud" && config.mode !== "local")
  )
    throw invalidInput();
  for (const key of CONFIG_KEYS)
    if (
      key !== "mode" &&
      typeof config[key as keyof DesktopRuntimeConfig] !== "string"
    )
      throw invalidInput();
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}
export function requireTenantTrustSnapshotV2(
  value: unknown,
  scope: TenantTrustScope,
): TenantTrustSnapshot {
  if (
    !record(value) ||
    !record(value.scope) ||
    !record(value.data) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.scope.workspaceId !== scope.workspaceId ||
    value.authority !== "cloud" ||
    value.availability !== "available" ||
    value.reasonCode !== null ||
    value.contractVersion !== "4.0.0" ||
    !Array.isArray(value.allowedActions) ||
    !value.allowedActions.every((item) => typeof item === "string") ||
    typeof value.data.membershipRole !== "string" ||
    !Array.isArray(value.data.policies) ||
    value.membershipRole !== value.data.membershipRole ||
    value.policies !== value.data.policies
  )
    throw invalidResponse();
  for (const policy of value.data.policies)
    requireTenantTrustPolicyV2(policy, scope);
  return value as unknown as TenantTrustSnapshot;
}
export function requireTenantTrustPolicyV2(
  value: unknown,
  scope: TenantTrustScope,
): TenantTrustPolicy {
  if (
    !record(value) ||
    value.tenantId !== scope.tenantId ||
    value.workspaceId !== scope.workspaceId ||
    !text(value.id) ||
    !text(value.agentInstanceId) ||
    !text(value.actionType) ||
    !text(value.grantedBy) ||
    (value.grantType !== "once" && value.grantType !== "always") ||
    !text(value.scope) ||
    !Number.isSafeInteger(value.revision) ||
    Number(value.revision) < 0 ||
    !nullableText(value.revokedBy) ||
    !nullableText(value.revokedAt) ||
    !text(value.createdAt) ||
    !nullableText(value.deletedAt)
  )
    throw invalidResponse();
  return value as unknown as TenantTrustPolicy;
}
function common(input: DesktopTenantTrustLoadInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantTrustConfigV2(input.config);
  if (
    !record(input.scope) ||
    Object.keys(input.scope).length !== 3 ||
    input.scope.authority !== config.mode ||
    input.scope.tenantId !== config.tenantId ||
    input.scope.workspaceId !== config.workspaceId
  )
    throw invalidInput();
  identifier(input.scope.tenantId);
  identifier(input.scope.workspaceId);
  if (
    input.signal !== undefined &&
    (!record(input.signal) ||
      typeof input.signal.aborted !== "boolean" ||
      typeof input.signal.addEventListener !== "function")
  )
    throw invalidInput();
  return {
    config,
    scope: Object.freeze({ ...input.scope }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
}
function identifier(value: unknown): string {
  if (!text(value) || value !== value.trim()) throw invalidInput();
  return value;
}
function text(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}
function nullableText(value: unknown): boolean {
  return value === null || text(value);
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function invalidInput() {
  return new RuntimeV2Error(
    "desktop_tenant_trust_operation_input_invalid",
    "desktop tenant trust operation input invalid",
  );
}
function invalidResponse() {
  return new RuntimeV2Error(
    "desktop_tenant_trust_operation_response_invalid",
    "desktop tenant trust operation response invalid",
  );
}
