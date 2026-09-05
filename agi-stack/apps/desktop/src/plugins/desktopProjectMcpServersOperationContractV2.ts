import { DesktopApiError } from '../api/client';
import type {
  DesktopMCPCredentialProvisionInput,
  DesktopMCPCredentialProvisionResponse,
  DesktopMCPServerCreateInput,
  DesktopMCPServerUpdateInput,
  DesktopMCPServerToggleInput,
  DesktopMCPServerDeleteInput,
  DesktopMCPServerSummary,
  DesktopMCPServerTestResult,
} from '../api/client';
import type { DesktopRuntimeConfig } from '../types';
export interface McpServersArgumentsV2 {
  listMCPServers: [projectId: string];
  provisionMCPServerCredential: [input: DesktopMCPCredentialProvisionInput];
  createMCPServer: [input: DesktopMCPServerCreateInput];
  updateMCPServer: [serverId: string, input: DesktopMCPServerUpdateInput];
  setMCPServerEnabled: [serverId: string, input: DesktopMCPServerToggleInput];
  deleteMCPServer: [serverId: string, input: DesktopMCPServerDeleteInput];
  testMCPServer: [serverId: string];
}
export interface McpServersResultsV2 {
  listMCPServers: DesktopMCPServerSummary[];
  provisionMCPServerCredential: DesktopMCPCredentialProvisionResponse;
  createMCPServer: DesktopMCPServerSummary;
  updateMCPServer: DesktopMCPServerSummary;
  setMCPServerEnabled: DesktopMCPServerSummary;
  deleteMCPServer: void;
  testMCPServer: DesktopMCPServerTestResult;
}
export type McpServersMethodV2 = keyof McpServersArgumentsV2;
export const MCP_SERVERS_METHODS_V2: readonly McpServersMethodV2[] = Object.freeze([
  'listMCPServers',
  'provisionMCPServerCredential',
  'createMCPServer',
  'updateMCPServer',
  'setMCPServerEnabled',
  'deleteMCPServer',
  'testMCPServer',
]);
export type McpServersScopeV2 = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
  projectId: string;
}>;
export type McpServersInputV2<K extends McpServersMethodV2 = McpServersMethodV2> = Readonly<{
  config: DesktopRuntimeConfig;
  scope: McpServersScopeV2;
  args: McpServersArgumentsV2[K];
  signal?: AbortSignal;
}>;
export interface DesktopProjectMcpServersAuthorityV2 {
  execute(method: McpServersMethodV2, input: McpServersInputV2): Promise<unknown>;
}
export function mcpServersErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, Object.freeze({ code, reason_code: code }));
}
export function mcpServersRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function mcpServersIdentifierV2(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim())
    throw mcpServersErrorV2('project_mcp_servers_identifier_invalid');
  return value;
}
export function freezeMcpServersJsonV2<T>(value: T, depth = 0): T {
  if (depth > 32) throw mcpServersErrorV2('project_mcp_servers_json_invalid');
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  )
    return value;
  if (Array.isArray(value))
    return Object.freeze(value.map((v) => freezeMcpServersJsonV2(v, depth + 1))) as T;
  if (
    !mcpServersRecordV2(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw mcpServersErrorV2('project_mcp_servers_json_invalid');
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (['__proto__', 'constructor', 'prototype'].includes(key))
      throw mcpServersErrorV2('project_mcp_servers_json_invalid');
    if (item !== undefined) result[key] = freezeMcpServersJsonV2(item, depth + 1);
  }
  return Object.freeze(result) as T;
}
export function freezeMcpServersConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
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
    !mcpServersRecordV2(config) ||
    Object.keys(config).length !== keys.length ||
    keys.some((k) => typeof config[k as keyof DesktopRuntimeConfig] !== 'string') ||
    !['cloud', 'local'].includes(config.mode)
  )
    throw mcpServersErrorV2('project_mcp_servers_config_invalid');
  return Object.freeze({ ...config });
}
export function prepareMcpServersInputV2<K extends McpServersMethodV2>(
  method: K,
  input: McpServersInputV2<K>,
): McpServersInputV2<K> {
  if (
    !MCP_SERVERS_METHODS_V2.includes(method) ||
    !mcpServersRecordV2(input) ||
    !mcpServersRecordV2(input.scope) ||
    Object.keys(input.scope).length !== 3
  )
    throw mcpServersErrorV2('project_mcp_servers_operation_invalid');
  const config = freezeMcpServersConfigV2(input.config);
  const tenantId = mcpServersIdentifierV2(input.scope.tenantId);
  const projectId = mcpServersIdentifierV2(input.scope.projectId);
  if (
    config.mode !== input.scope.authority ||
    config.tenantId !== tenantId ||
    config.projectId !== projectId
  )
    throw mcpServersErrorV2('project_mcp_servers_scope_mismatch', 409);
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal))
    throw mcpServersErrorV2('project_mcp_servers_signal_invalid');
  if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const args = freezeMcpServersJsonV2(input.args);
  const itemMutation = ['updateMCPServer', 'setMCPServerEnabled', 'deleteMCPServer'].includes(
    method,
  );
  if (!Array.isArray(args) || args.length !== (itemMutation ? 2 : 1))
    throw mcpServersErrorV2('project_mcp_servers_arguments_invalid');
  if (method === 'listMCPServers') {
    if (mcpServersIdentifierV2(args[0]) !== projectId)
      throw mcpServersErrorV2('project_mcp_servers_scope_mismatch', 409);
  } else if (method === 'testMCPServer') mcpServersIdentifierV2(args[0]);
  else {
    if (itemMutation) mcpServersIdentifierV2(args[0]);
    const body: unknown = args[itemMutation ? 1 : 0];
    if (!mcpServersRecordV2(body) || body.project_id !== projectId)
      throw mcpServersErrorV2('project_mcp_servers_scope_mismatch', 409);
    validateKey(body.idempotency_key);
    if (
      itemMutation &&
      config.mode === 'local' &&
      (!Number.isSafeInteger(body.expected_revision) || Number(body.expected_revision) < 1)
    )
      throw mcpServersErrorV2('local_mcp_revision_required', 428);
    const keys =
      method === 'provisionMCPServerCredential'
        ? [
            'project_id',
            'server_name',
            'server_type',
            'transport_config',
            'credential_kind',
            'credential_name',
            'secret',
            'idempotency_key',
            'mutation_idempotency_key',
          ]
        : method === 'deleteMCPServer'
          ? ['project_id', 'expected_revision', 'idempotency_key']
          : method === 'setMCPServerEnabled'
            ? ['project_id', 'expected_revision', 'idempotency_key', 'enabled']
            : [
                'name',
                'description',
                'server_type',
                'transport_config',
                'enabled',
                'project_id',
                'idempotency_key',
                ...(itemMutation ? ['expected_revision'] : []),
              ];
    if (Object.keys(body).some((key) => !keys.includes(key)))
      throw mcpServersErrorV2('project_mcp_servers_mutation_fields_invalid');
    if (method === 'provisionMCPServerCredential') {
      if (
        typeof body.server_name !== 'string' ||
        !body.server_name ||
        !['env', 'header'].includes(String(body.credential_kind)) ||
        typeof body.secret !== 'string' ||
        !body.secret
      )
        throw mcpServersErrorV2('project_mcp_servers_credential_invalid');
      mcpServersIdentifierV2(body.credential_name);
      if (body.mutation_idempotency_key !== undefined) validateKey(body.mutation_idempotency_key);
      if ((body.server_type === 'stdio') !== (body.credential_kind === 'env'))
        throw mcpServersErrorV2('local_mcp_credential_kind_invalid');
      validateTransport(body.server_type, body.transport_config, config.mode, true);
    } else if (method === 'createMCPServer' || method === 'updateMCPServer') {
      if (
        typeof body.name !== 'string' ||
        !body.name ||
        (body.description !== undefined &&
          body.description !== null &&
          typeof body.description !== 'string') ||
        (body.enabled !== undefined && typeof body.enabled !== 'boolean')
      )
        throw mcpServersErrorV2('project_mcp_servers_mutation_invalid');
      validateTransport(body.server_type, body.transport_config, config.mode, false);
    } else if (method === 'setMCPServerEnabled' && typeof body.enabled !== 'boolean')
      throw mcpServersErrorV2('project_mcp_servers_enabled_invalid');
  }
  return Object.freeze({
    config,
    scope: Object.freeze({ authority: config.mode, tenantId, projectId }),
    args,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
function validateKey(value: unknown): void {
  if (
    typeof value !== 'string' ||
    !value ||
    value.length > 200 ||
    /[\u0000-\u001f\u007f]/u.test(value)
  )
    throw mcpServersErrorV2('local_mcp_idempotency_key_invalid');
}
function validateTransport(
  type: unknown,
  value: unknown,
  mode: DesktopRuntimeConfig['mode'],
  provision: boolean,
): void {
  if (!['stdio', 'http', 'sse', 'websocket'].includes(String(type)) || !mcpServersRecordV2(value))
    throw mcpServersErrorV2('project_mcp_servers_transport_invalid');
  if (type === 'stdio') {
    if (
      !(typeof value.command === 'string' && value.command.length > 0) &&
      !(
        Array.isArray(value.command) &&
        value.command.length > 0 &&
        value.command.every((v) => typeof v === 'string' && v.length > 0)
      )
    )
      throw mcpServersErrorV2('project_mcp_servers_command_invalid');
  } else if (typeof value.url !== 'string' || !value.url)
    throw mcpServersErrorV2('project_mcp_servers_url_invalid');
  for (const key of ['args', 'credential_env_names', 'credential_header_names'])
    if (
      value[key] !== undefined &&
      (!Array.isArray(value[key]) || value[key].some((v) => typeof v !== 'string'))
    )
      throw mcpServersErrorV2('project_mcp_servers_transport_invalid');
  if (value.cwd !== undefined && value.cwd !== null && typeof value.cwd !== 'string')
    throw mcpServersErrorV2('project_mcp_servers_transport_invalid');
  if (
    mode === 'local' &&
    Object.keys(value).some(
      (key) =>
        ![
          'command',
          'args',
          'cwd',
          'url',
          'credential_env_names',
          'credential_header_names',
        ].includes(key),
    )
  )
    throw mcpServersErrorV2('local_mcp_transport_fields_invalid');
  if (
    provision &&
    ['credential_env_names', 'credential_header_names'].some(
      (key) => Array.isArray(value[key]) && value[key].length > 0,
    )
  )
    throw mcpServersErrorV2('local_mcp_credential_config_invalid');
}
