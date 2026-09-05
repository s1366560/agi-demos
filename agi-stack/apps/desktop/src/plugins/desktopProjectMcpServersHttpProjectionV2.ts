import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import {
  freezeMcpServersConfigV2,
  prepareMcpServersInputV2,
  mcpServersErrorV2,
  mcpServersRecordV2,
  type DesktopProjectMcpServersAuthorityV2,
  type McpServersMethodV2,
  type McpServersInputV2,
} from './desktopProjectMcpServersOperationContractV2';
import { requireMcpServerSummaryV2 } from './desktopProjectMcpServersResponseContractV2';

export function createDesktopProjectMcpServersHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopProjectMcpServersAuthorityV2 {
  const runtime = freezeMcpServersConfigV2(config);
  return Object.freeze({
    async execute(method: McpServersMethodV2, input: McpServersInputV2) {
      if (
        Object.keys(runtime).some(
          (key) =>
            runtime[key as keyof DesktopRuntimeConfig] !==
            input.config[key as keyof DesktopRuntimeConfig],
        )
      )
        throw mcpServersErrorV2('project_mcp_servers_projection_config_mismatch', 409);
      const p = prepareMcpServersInputV2(method, { ...input, config: runtime });
      const args = p.args;
      if (runtime.mode === 'cloud' && method === 'provisionMCPServerCredential')
        throw mcpServersErrorV2('cloud_mcp_credential_provision_unavailable', 501);
      const itemMutation = ['updateMCPServer', 'setMCPServerEnabled', 'deleteMCPServer'].includes(
        method,
      );
      const itemOperation = itemMutation || method === 'testMCPServer';
      const itemPath = `/api/v1/mcp/${encodeURIComponent(args[0] as string)}`;
      // Cloud writes ignore body.project_id; pin the target to this project before any side effect.
      // Local routes resolve the id through the authenticated active_scope instead.
      if (runtime.mode === 'cloud' && itemOperation) {
        const current = await requestMcpServersJsonV2(runtime, itemPath, { signal: p.signal });
        requireMcpServerSummaryV2(current, p.scope, args[0] as string);
      }
      if (method === 'listMCPServers')
        return requestMcpServersJsonV2(
          runtime,
          `/api/v1/mcp?${new URLSearchParams({ project_id: p.scope.projectId })}`,
          { signal: p.signal },
        );
      if (method === 'testMCPServer')
        return requestMcpServersJsonV2(runtime, itemPath + '/test', {
          method: 'POST',
          signal: p.signal,
        });
      const value = args[itemMutation ? 1 : 0];
      if (!mcpServersRecordV2(value))
        throw mcpServersErrorV2('project_mcp_servers_mutation_invalid');
      const body: Record<string, unknown> = { ...value };
      if (runtime.mode === 'cloud') {
        // Python MCP writes have no optimistic revision contract. Do not invent one on the wire.
        delete body.expected_revision;
        const transport = body.transport_config;
        if (
          mcpServersRecordV2(transport) &&
          ['credential_env_names', 'credential_header_names'].some(
            (key) => Array.isArray(transport[key]) && transport[key].length > 0,
          )
        )
          throw mcpServersErrorV2('cloud_mcp_credential_provision_unavailable', 501);
      }
      const path =
        method === 'provisionMCPServerCredential'
          ? '/api/v1/mcp/credentials/provision'
          : itemMutation
            ? itemPath
            : '/api/v1/mcp';
      return requestMcpServersJsonV2(runtime, path, {
        method: method === 'deleteMCPServer' ? 'DELETE' : itemMutation ? 'PUT' : 'POST',
        body,
        signal: p.signal,
      });
    },
  });
}
async function requestMcpServersJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  options: Readonly<{
    method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
    body?: unknown;
    signal?: AbortSignal;
  }>,
): Promise<unknown> {
  if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  if (!desktopApiAuthenticationAvailable(config))
    throw mcpServersErrorV2('desktop_trusted_session_required', 401);
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launch = desktopLaunchCapability(config);
  if (config.mode === 'local' && !launch)
    throw mcpServersErrorV2('desktop_sidecar_launch_capability_required', 401);
  if (launch) headers.set('X-Agistack-Launch', launch);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  // Keep native Cloud broker authorization and Local application-vault provisioning unchanged.
  const response = await desktopApiFetch(config, path, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  if (response.status === 204) return null;
  const contentType = response.headers.get('content-type') ?? '';
  const raw: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    const payload = safeMcpServersErrorPayloadV2(raw);
    const detail = payload?.detail;
    throw new DesktopApiError(
      typeof detail === 'string' ? detail : `HTTP ${response.status}`,
      response.status,
      payload,
    );
  }
  if (!contentType.includes('application/json'))
    throw mcpServersErrorV2('project_mcp_servers_response_not_json', 502);
  return raw;
}
function safeMcpServersErrorPayloadV2(raw: unknown): Readonly<Record<string, unknown>> | null {
  if (!mcpServersRecordV2(raw)) return null;
  const result: Record<string, unknown> = {};
  // Error envelopes must not retain echoed transport config, credential input or vault references.
  for (const key of [
    'detail',
    'code',
    'reason_code',
    'expected_revision',
    'actual_revision',
    'revision',
    'availability',
    'contract_version',
    'mode',
    'capability',
    'retryable',
  ]) {
    const value = raw[key];
    if (
      typeof value === 'string' ||
      typeof value === 'boolean' ||
      (typeof value === 'number' && Number.isFinite(value)) ||
      value === null
    )
      result[key] = value;
  }
  return Object.freeze(result);
}
