import { RuntimeV2Error } from "@agistack/plugin-runtime";

import type { DesktopRuntimeConfig } from "../types";
import type {
  TenantAcpAgent,
  TenantAcpAgentInput,
  TenantAcpSnapshot,
  TenantAcpTestInput,
  TenantAcpTransport,
} from "../features/tenant-admin/tenantAcpClient";
import type { TenantManagementScope } from "../features/tenant-admin/tenantManagementHttp";

export type DesktopTenantAcpLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantAcpCreateInputV2 = DesktopTenantAcpLoadInputV2 &
  Readonly<{ agent: TenantAcpAgentInput & Readonly<{ agentKey: string }> }>;
export type DesktopTenantAcpUpdateInputV2 = DesktopTenantAcpLoadInputV2 &
  Readonly<{ agentKey: string; agent: TenantAcpAgentInput }>;
export type DesktopTenantAcpDeleteInputV2 = DesktopTenantAcpLoadInputV2 &
  Readonly<{ agentKey: string }>;
export type DesktopTenantAcpTestOperationInputV2 =
  DesktopTenantAcpDeleteInputV2 & Readonly<{ test: TenantAcpTestInput }>;
const CONFIG_KEYS = [
  "apiBaseUrl",
  "deviceAuthorizationBaseUrl",
  "apiKey",
  "localApiToken",
  "tenantId",
  "projectId",
  "workspaceId",
  "mode",
  "workspaceRoot",
] as const;
const AGENT_KEYS = new Set([
  "agentKey",
  "name",
  "transport",
  "command",
  "args",
  "url",
  "env",
  "headers",
  "runnerPoolKey",
  "requiredLabels",
  "cwdPolicy",
  "enabled",
]);

export function prepareTenantAcpLoadV2(input: DesktopTenantAcpLoadInputV2) {
  return Object.freeze(common(input));
}
export function prepareTenantAcpCreateV2(input: DesktopTenantAcpCreateInputV2) {
  return Object.freeze({
    ...common(input),
    agent: freezeAgent(input.agent, true),
  });
}
export function prepareTenantAcpUpdateV2(input: DesktopTenantAcpUpdateInputV2) {
  return Object.freeze({
    ...common(input),
    agentKey: text(input.agentKey),
    agent: freezeAgent(input.agent, false),
  });
}
export function prepareTenantAcpDeleteV2(input: DesktopTenantAcpDeleteInputV2) {
  return Object.freeze({ ...common(input), agentKey: text(input.agentKey) });
}
export function prepareTenantAcpTestV2(
  input: DesktopTenantAcpTestOperationInputV2,
) {
  const prepared = prepareTenantAcpDeleteV2(input);
  if (
    !record(input.test) ||
    Object.keys(input.test).some(
      (key) => !["cwd", "projectId", "prompt", "timeoutSeconds"].includes(key),
    )
  )
    throw invalidInput();
  const timeoutSeconds = input.test.timeoutSeconds;
  if (
    timeoutSeconds !== undefined &&
    (!Number.isSafeInteger(timeoutSeconds) || timeoutSeconds < 1)
  )
    throw invalidInput();
  return Object.freeze({
    ...prepared,
    test: Object.freeze({
      cwd: text(input.test.cwd),
      ...(input.test.projectId === undefined
        ? {}
        : { projectId: text(input.test.projectId) }),
      prompt: text(input.test.prompt),
      ...(timeoutSeconds === undefined ? {} : { timeoutSeconds }),
    }),
  });
}
export function freezeTenantAcpConfigV2(
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
    if (key !== "mode" && typeof config[key] !== "string") throw invalidInput();
  text(config.tenantId);
  return Object.freeze({ ...config });
}
export function requireTenantAcpSnapshotV2(
  value: unknown,
  scope: TenantManagementScope,
): TenantAcpSnapshot {
  if (
    !record(value) ||
    !record(value.scope) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    value.authority !== "cloud" ||
    value.availability !== "available" ||
    value.reasonCode !== null ||
    value.contractVersion !== "4.0.0" ||
    !Array.isArray(value.allowedActions) ||
    !record(value.data) ||
    value.membershipRole !== value.data.membershipRole ||
    value.status !== value.data.status ||
    value.runnerPools !== value.data.runnerPools ||
    !record(value.status) ||
    !Array.isArray(value.runnerPools)
  )
    throw invalidResponse();
  return value as unknown as TenantAcpSnapshot;
}
export function requireTenantAcpAgentV2(value: unknown): TenantAcpAgent {
  if (
    !record(value) ||
    !["stdio", "websocket"].includes(String(value.transport)) ||
    typeof value.enabled !== "boolean" ||
    typeof value.available !== "boolean" ||
    !Array.isArray(value.missingEnv) ||
    ["id", "agentKey", "name"].some(
      (key) => typeof value[key] !== "string" || !value[key],
    ) ||
    (value.command !== null && typeof value.command !== "string") ||
    (value.url !== null && typeof value.url !== "string")
  )
    throw invalidResponse();
  return value as unknown as TenantAcpAgent;
}
export function requireTenantAcpTestResultV2(
  value: unknown,
): Readonly<Record<string, unknown>> {
  if (!record(value)) throw invalidResponse();
  return deepFreezeCopy(value) as Readonly<Record<string, unknown>>;
}
function common(input: DesktopTenantAcpLoadInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantAcpConfigV2(input.config);
  if (
    !record(input.scope) ||
    Object.keys(input.scope).length !== 2 ||
    input.scope.authority !== config.mode ||
    input.scope.tenantId !== config.tenantId
  )
    throw invalidInput();
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
function freezeAgent(
  value: TenantAcpAgentInput,
  requireKey: boolean,
): TenantAcpAgentInput & Readonly<{ agentKey?: string }> {
  if (!record(value) || Object.keys(value).some((key) => !AGENT_KEYS.has(key)))
    throw invalidInput();
  if (
    value.args !== undefined &&
    (!Array.isArray(value.args) ||
      value.args.some((item) => typeof item !== "string"))
  )
    throw invalidInput();
  for (const key of ["command", "url", "runnerPoolKey"] as const)
    if (
      value[key] !== undefined &&
      value[key] !== null &&
      typeof value[key] !== "string"
    )
      throw invalidInput();
  if (value.enabled !== undefined && typeof value.enabled !== "boolean")
    throw invalidInput();
  const source = {
    ...value,
    name: text(value.name),
    transport: transport(value.transport),
    ...(requireKey ? { agentKey: text(value.agentKey) } : {}),
  };
  return deepFreezeCopy(source) as TenantAcpAgentInput &
    Readonly<{ agentKey?: string }>;
}
function deepFreezeCopy(value: unknown, depth = 0): unknown {
  if (depth > 16) throw invalidInput();
  if (value === null || typeof value === "string" || typeof value === "boolean")
    return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw invalidInput();
    return value;
  }
  if (Array.isArray(value))
    return Object.freeze(value.map((item) => deepFreezeCopy(item, depth + 1)));
  if (!record(value)) throw invalidInput();
  const copy: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === "__proto__" || key === "constructor" || key === "prototype")
      throw invalidInput();
    copy[key] = deepFreezeCopy(item, depth + 1);
  }
  return Object.freeze(copy);
}
function transport(value: unknown): TenantAcpTransport {
  if (value !== "stdio" && value !== "websocket") throw invalidInput();
  return value;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value || value !== value.trim())
    throw invalidInput();
  return value;
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function invalidInput() {
  return new RuntimeV2Error(
    "desktop_tenant_acp_operation_input_invalid",
    "desktop tenant ACP operation input invalid",
  );
}
function invalidResponse() {
  return new RuntimeV2Error(
    "desktop_tenant_acp_operation_response_invalid",
    "desktop tenant ACP operation response invalid",
  );
}
