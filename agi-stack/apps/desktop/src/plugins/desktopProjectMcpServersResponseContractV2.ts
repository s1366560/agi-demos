import type { DesktopMCPServerSummary } from '../api/client';
import {
  freezeMcpServersJsonV2,
  mcpServersErrorV2,
  mcpServersRecordV2,
  type McpServersScopeV2,
  type McpServersMethodV2,
  type McpServersInputV2,
  type McpServersResultsV2,
} from './desktopProjectMcpServersOperationContractV2';

export function requireMcpServerSummaryV2(
  raw: unknown,
  scope: McpServersScopeV2,
  serverId?: string,
): DesktopMCPServerSummary {
  if (
    !mcpServersRecordV2(raw) ||
    typeof raw.id !== 'string' ||
    !raw.id ||
    typeof raw.name !== 'string' ||
    !raw.name ||
    !['stdio', 'http', 'sse', 'websocket'].includes(String(raw.server_type)) ||
    typeof raw.enabled !== 'boolean' ||
    typeof raw.runtime_status !== 'string'
  )
    throw mcpServersErrorV2('project_mcp_servers_response_invalid', 502);
  if (
    raw.tenant_id !== scope.tenantId ||
    raw.project_id !== scope.projectId ||
    (serverId !== undefined && raw.id !== serverId)
  )
    throw mcpServersErrorV2('project_mcp_servers_response_scope_invalid', 502);
  if (
    raw.description !== undefined &&
    raw.description !== null &&
    typeof raw.description !== 'string'
  )
    throw mcpServersErrorV2('project_mcp_servers_response_invalid', 502);
  if (raw.transport_config !== undefined) {
    const transport = raw.transport_config;
    if (!mcpServersRecordV2(transport))
      throw mcpServersErrorV2('project_mcp_servers_transport_response_invalid', 502);
    // Local redacts argv and emits explicit null for transport fields that do not apply.
    if (
      transport.command !== undefined &&
      transport.command !== null &&
      typeof transport.command !== 'string' &&
      !(Array.isArray(transport.command) && transport.command.every((v) => typeof v === 'string'))
    )
      throw mcpServersErrorV2('project_mcp_servers_transport_response_invalid', 502);
    for (const key of ['url', 'cwd'])
      if (
        transport[key] !== undefined &&
        transport[key] !== null &&
        typeof transport[key] !== 'string'
      )
        throw mcpServersErrorV2('project_mcp_servers_transport_response_invalid', 502);
    for (const key of [
      'args',
      'credential_env_names',
      'credential_header_names',
      'vault_env_names',
      'vault_header_names',
    ])
      if (
        transport[key] !== undefined &&
        (!Array.isArray(transport[key]) || transport[key].some((v) => typeof v !== 'string'))
      )
        throw mcpServersErrorV2('project_mcp_servers_transport_response_invalid', 502);
    if (
      transport.arguments_redacted !== undefined &&
      typeof transport.arguments_redacted !== 'boolean'
    )
      throw mcpServersErrorV2('project_mcp_servers_transport_response_invalid', 502);
  }
  if (raw.runtime_metadata !== undefined && !mcpServersRecordV2(raw.runtime_metadata))
    throw mcpServersErrorV2('project_mcp_servers_metadata_invalid', 502);
  if (
    mcpServersRecordV2(raw.runtime_metadata) &&
    raw.runtime_metadata.reason_code !== undefined &&
    raw.runtime_metadata.reason_code !== null &&
    typeof raw.runtime_metadata.reason_code !== 'string'
  )
    throw mcpServersErrorV2('project_mcp_servers_metadata_invalid', 502);
  const revision = mcpServersRecordV2(raw.runtime_metadata)
    ? raw.runtime_metadata.revision
    : undefined;
  if (
    (scope.authority === 'local' || revision !== undefined) &&
    (!Number.isSafeInteger(revision) || Number(revision) < 1)
  )
    throw mcpServersErrorV2('project_mcp_servers_revision_response_invalid', 502);
  if (
    raw.discovered_tools !== undefined &&
    (!Array.isArray(raw.discovered_tools) ||
      raw.discovered_tools.some(
        (v) => !mcpServersRecordV2(v) || (v.name !== undefined && typeof v.name !== 'string'),
      ))
  )
    throw mcpServersErrorV2('project_mcp_servers_tools_response_invalid', 502);
  const transport = mcpServersRecordV2(raw.transport_config) ? raw.transport_config : undefined;
  const safeTransport =
    transport === undefined
      ? undefined
      : pickSafeFields(transport, [
          'command',
          'args',
          'cwd',
          'url',
          'arguments_redacted',
          'vault_env_names',
          'vault_header_names',
        ]);
  if (safeTransport) {
    for (const key of ['command', 'cwd', 'url']) {
      if (safeTransport[key] === null) delete safeTransport[key];
    }
  }
  const safeMetadata = mcpServersRecordV2(raw.runtime_metadata)
    ? pickSafeFields(raw.runtime_metadata, ['reason_code', 'revision'])
    : undefined;
  return freezeMcpServersJsonV2({
    id: raw.id,
    tenant_id: raw.tenant_id,
    project_id: raw.project_id,
    name: raw.name,
    description: raw.description,
    server_type: raw.server_type,
    enabled: raw.enabled,
    runtime_status: raw.runtime_status,
    ...(safeTransport === undefined ? {} : { transport_config: safeTransport }),
    ...(safeMetadata === undefined ? {} : { runtime_metadata: safeMetadata }),
    ...(Array.isArray(raw.discovered_tools)
      ? { discovered_tools: raw.discovered_tools.map((tool) => pickSafeFields(tool, ['name'])) }
      : {}),
  }) as unknown as DesktopMCPServerSummary;
}
export function requireMcpServersResultV2<K extends McpServersMethodV2>(
  method: K,
  raw: unknown,
  input: McpServersInputV2<K>,
): McpServersResultsV2[K] {
  let result: unknown;
  switch (method) {
    case 'listMCPServers':
      if (!Array.isArray(raw))
        throw mcpServersErrorV2('project_mcp_servers_list_response_invalid', 502);
      result = raw.map((item) => requireMcpServerSummaryV2(item, input.scope));
      break;
    case 'createMCPServer':
      result = requireMcpServerSummaryV2(raw, input.scope);
      break;
    case 'updateMCPServer':
    case 'setMCPServerEnabled':
      result = requireMcpServerSummaryV2(raw, input.scope, input.args[0] as string);
      break;
    case 'provisionMCPServerCredential': {
      const request: unknown = input.args[0];
      if (
        !mcpServersRecordV2(request) ||
        !mcpServersRecordV2(raw) ||
        Object.keys(raw).length !== 4 ||
        raw.stored !== true ||
        raw.credential_kind !== request.credential_kind ||
        raw.credential_name !== request.credential_name ||
        typeof raw.duplicate !== 'boolean'
      )
        throw mcpServersErrorV2('project_mcp_servers_credential_response_invalid', 502);
      result = raw;
      break;
    }
    case 'testMCPServer':
      if (
        !mcpServersRecordV2(raw) ||
        typeof raw.success !== 'boolean' ||
        typeof raw.message !== 'string' ||
        !Number.isSafeInteger(raw.tools_discovered) ||
        Number(raw.tools_discovered) < 0 ||
        typeof raw.connection_time_ms !== 'number' ||
        !Number.isFinite(raw.connection_time_ms) ||
        raw.connection_time_ms < 0 ||
        !Array.isArray(raw.errors) ||
        raw.errors.some((v) => typeof v !== 'string')
      )
        throw mcpServersErrorV2('project_mcp_servers_test_response_invalid', 502);
      result = pickSafeFields(raw, [
        'success',
        'message',
        'tools_discovered',
        'connection_time_ms',
        'errors',
      ]);
      break;
    case 'deleteMCPServer':
      if (
        input.scope.authority === 'cloud'
          ? raw !== null
          : !mcpServersRecordV2(raw) ||
            raw.deleted !== true ||
            raw.id !== input.args[0] ||
            !Number.isSafeInteger(raw.revision) ||
            Number(raw.revision) < 1 ||
            typeof raw.duplicate !== 'boolean'
      )
        throw mcpServersErrorV2('project_mcp_servers_delete_response_invalid', 502);
      result = undefined;
      break;
  }
  return (
    result === undefined ? undefined : freezeMcpServersJsonV2(result)
  ) as McpServersResultsV2[K];
}

function pickSafeFields(
  value: Record<string, unknown>,
  keys: readonly string[],
): Record<string, unknown> {
  return Object.fromEntries(
    keys.filter((key) => value[key] !== undefined).map((key) => [key, value[key]]),
  );
}
