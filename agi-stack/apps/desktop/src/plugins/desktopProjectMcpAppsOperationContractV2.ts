import { DesktopApiError } from '../api/client';
import type {
  DesktopMCPAppSummary,
  DesktopMCPAppToolCallResponse,
  DesktopMCPToolCallResponse,
  DesktopMCPAppResourceReadResponse,
  DesktopMCPAppResourceListResponse,
} from '../api/client';
import type { DesktopRuntimeConfig } from '../types';
export interface McpAppsArgumentsV2 {
  listMCPApps: [projectId: string];
  callMCPAppTool: [
    appId: string,
    toolName: string,
    argumentsValue: Record<string, unknown>,
    idempotencyKey: string,
  ];
  callMCPToolByServerId: [
    serverId: string,
    toolName: string,
    argumentsValue: Record<string, unknown>,
    idempotencyKey: string,
  ];
  callMCPAppToolDirect: [
    projectId: string,
    serverName: string,
    toolName: string,
    argumentsValue: Record<string, unknown>,
    idempotencyKey: string,
  ];
  readMCPAppResource: [projectId: string, uri: string, serverName?: string | null];
  listMCPAppResources: [projectId: string, serverName?: string | null];
}
export interface McpAppsResultsV2 {
  listMCPApps: DesktopMCPAppSummary[];
  callMCPAppTool: DesktopMCPAppToolCallResponse;
  callMCPToolByServerId: DesktopMCPToolCallResponse;
  callMCPAppToolDirect: DesktopMCPAppToolCallResponse;
  readMCPAppResource: DesktopMCPAppResourceReadResponse;
  listMCPAppResources: DesktopMCPAppResourceListResponse;
}
export type McpAppsMethodV2 = keyof McpAppsArgumentsV2;
export const MCP_APPS_METHODS_V2: readonly McpAppsMethodV2[] = Object.freeze([
  'listMCPApps',
  'callMCPAppTool',
  'callMCPToolByServerId',
  'callMCPAppToolDirect',
  'readMCPAppResource',
  'listMCPAppResources',
]);
export type McpAppsScopeV2 = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
  projectId: string;
}>;
export type McpAppsInputV2<K extends McpAppsMethodV2 = McpAppsMethodV2> = Readonly<{
  config: DesktopRuntimeConfig;
  scope: McpAppsScopeV2;
  args: McpAppsArgumentsV2[K];
  signal?: AbortSignal;
}>;
export interface DesktopProjectMcpAppsAuthorityV2 {
  execute(method: McpAppsMethodV2, input: McpAppsInputV2): Promise<unknown>;
}
export function mcpAppsErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, Object.freeze({ code, reason_code: code }));
}
export function mcpAppsRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function mcpAppsIdentifierV2(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim())
    throw mcpAppsErrorV2('project_mcp_apps_identifier_invalid');
  return value;
}
export function freezeMcpAppsJsonV2<T>(value: T, depth = 0): T {
  if (depth > 32) throw mcpAppsErrorV2('project_mcp_apps_json_invalid');
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  )
    return value;
  if (Array.isArray(value))
    return Object.freeze(value.map((v) => freezeMcpAppsJsonV2(v, depth + 1))) as T;
  if (!mcpAppsRecordV2(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value)))
    throw mcpAppsErrorV2('project_mcp_apps_json_invalid');
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (['__proto__', 'constructor', 'prototype'].includes(key))
      throw mcpAppsErrorV2('project_mcp_apps_json_invalid');
    if (item !== undefined) result[key] = freezeMcpAppsJsonV2(item, depth + 1);
  }
  return Object.freeze(result) as T;
}
export function freezeMcpAppsConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  const keys = [
    'apiBaseUrl',
    'deviceAuthorizationBaseUrl',
    'apiKey',
    'localApiToken',
    'tenantId',
    'projectId',
    'workspaceId',
    'mode',
    'workspaceRoot',
  ];
  if (
    !mcpAppsRecordV2(config) ||
    Object.keys(config).length !== keys.length ||
    keys.some((k) => typeof config[k as keyof DesktopRuntimeConfig] !== 'string') ||
    !['cloud', 'local'].includes(config.mode)
  )
    throw mcpAppsErrorV2('project_mcp_apps_config_invalid');
  return Object.freeze({ ...config });
}
export function prepareMcpAppsInputV2<K extends McpAppsMethodV2>(
  method: K,
  input: McpAppsInputV2<K>,
): McpAppsInputV2<K> {
  if (
    !MCP_APPS_METHODS_V2.includes(method) ||
    !mcpAppsRecordV2(input) ||
    !mcpAppsRecordV2(input.scope) ||
    Object.keys(input.scope).length !== 3
  )
    throw mcpAppsErrorV2('project_mcp_apps_operation_invalid');
  const config = freezeMcpAppsConfigV2(input.config);
  const tenantId = mcpAppsIdentifierV2(input.scope.tenantId);
  const projectId = mcpAppsIdentifierV2(input.scope.projectId);
  if (
    config.mode !== input.scope.authority ||
    config.tenantId !== tenantId ||
    config.projectId !== projectId
  )
    throw mcpAppsErrorV2('project_mcp_apps_scope_mismatch', 409);
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal))
    throw mcpAppsErrorV2('project_mcp_apps_signal_invalid');
  if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const args = freezeMcpAppsJsonV2(input.args);
  if (!Array.isArray(args)) throw mcpAppsErrorV2('project_mcp_apps_arguments_invalid');
  const lengths = {
    listMCPApps: [1],
    callMCPAppTool: [4],
    callMCPToolByServerId: [4],
    callMCPAppToolDirect: [5],
    readMCPAppResource: [2, 3],
    listMCPAppResources: [1, 2],
  };
  if (!lengths[method].includes(args.length))
    throw mcpAppsErrorV2('project_mcp_apps_arguments_invalid');
  mcpAppsIdentifierV2(args[0]);
  if (
    ['listMCPApps', 'callMCPAppToolDirect', 'readMCPAppResource', 'listMCPAppResources'].includes(
      method,
    ) &&
    args[0] !== projectId
  )
    throw mcpAppsErrorV2('project_mcp_apps_scope_mismatch', 409);
  if (
    method === 'callMCPAppTool' ||
    method === 'callMCPToolByServerId' ||
    method === 'callMCPAppToolDirect'
  ) {
    const offset = method === 'callMCPAppToolDirect' ? 1 : 0;
    if (offset) mcpAppsIdentifierV2(args[1]);
    mcpAppsIdentifierV2(args[1 + offset]);
    if (!mcpAppsRecordV2(args[2 + offset]))
      throw mcpAppsErrorV2('project_mcp_apps_tool_arguments_invalid');
    const key = args[3 + offset];
    if (
      typeof key !== 'string' ||
      !key ||
      key.length > (config.mode === 'local' ? 200 : 256) ||
      /[\u0000-\u001f\u007f]/u.test(key)
    )
      throw mcpAppsErrorV2('local_mcp_idempotency_key_invalid');
  } else {
    if (method === 'readMCPAppResource') mcpAppsIdentifierV2(args[1]);
    const server = args[method === 'readMCPAppResource' ? 2 : 1];
    if (server !== undefined && server !== null && typeof server !== 'string')
      throw mcpAppsErrorV2('project_mcp_apps_server_name_invalid');
  }
  return Object.freeze({
    config,
    scope: Object.freeze({ authority: config.mode, tenantId, projectId }),
    args,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
