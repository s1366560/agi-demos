import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import {
  freezeMcpAppsConfigV2,
  prepareMcpAppsInputV2,
  mcpAppsErrorV2,
  mcpAppsRecordV2,
  type DesktopProjectMcpAppsAuthorityV2,
  type McpAppsMethodV2,
  type McpAppsInputV2,
} from './desktopProjectMcpAppsOperationContractV2';
import { requireMcpAppIdentityV2 } from './desktopProjectMcpAppsResponseContractV2';

export function createDesktopProjectMcpAppsHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopProjectMcpAppsAuthorityV2 {
  const runtime = freezeMcpAppsConfigV2(config);
  return Object.freeze({
    async execute(method: McpAppsMethodV2, input: McpAppsInputV2) {
      if (
        Object.keys(runtime).some(
          (key) =>
            runtime[key as keyof DesktopRuntimeConfig] !==
            input.config[key as keyof DesktopRuntimeConfig],
        )
      )
        throw mcpAppsErrorV2('project_mcp_apps_projection_config_mismatch', 409);
      const p = prepareMcpAppsInputV2(method, { ...input, config: runtime });
      const args = p.args;
      const appPath = `/api/v1/mcp/apps/${encodeURIComponent(args[0] as string)}`;
      // Cloud id endpoints authorize the target's project, so prove the frozen lease scope first.
      // Local has no App GET: its original call handler enforces active_scope and App visibility.
      if (
        runtime.mode === 'cloud' &&
        (method === 'callMCPAppTool' || method === 'callMCPToolByServerId')
      ) {
        const path =
          method === 'callMCPAppTool'
            ? appPath
            : `/api/v1/mcp/${encodeURIComponent(args[0] as string)}`;
        const current = await requestMcpAppsJsonV2(runtime, path, { signal: p.signal });
        requireMcpAppIdentityV2(current, p.scope, args[0] as string);
      }
      if (method === 'listMCPApps')
        return requestMcpAppsJsonV2(
          runtime,
          `/api/v1/mcp/apps?${new URLSearchParams({ project_id: p.scope.projectId })}`,
          { signal: p.signal },
        );
      let path: string;
      let body: Record<string, unknown>;
      if (method === 'callMCPAppTool' || method === 'callMCPToolByServerId') {
        path = method === 'callMCPAppTool' ? appPath + '/tool-call' : '/api/v1/mcp/tools/call';
        body = {
          ...(method === 'callMCPToolByServerId' ? { server_id: args[0] } : {}),
          tool_name: args[1],
          arguments: args[2],
          idempotency_key: args[3],
        };
      } else if (method === 'callMCPAppToolDirect') {
        path = '/api/v1/mcp/apps/proxy/tool-call';
        body = {
          project_id: p.scope.projectId,
          server_name: args[1],
          tool_name: args[2],
          arguments: args[3],
          idempotency_key: args[4],
        };
      } else {
        const read = method === 'readMCPAppResource';
        path = `/api/v1/mcp/apps/resources/${read ? 'read' : 'list'}`;
        const name = args[read ? 2 : 1];
        body = {
          project_id: p.scope.projectId,
          ...(read ? { uri: args[1] } : {}),
          ...(typeof name === 'string' && name.trim() ? { server_name: name.trim() } : {}),
        };
      }
      return requestMcpAppsJsonV2(runtime, path, { method: 'POST', body, signal: p.signal });
    },
  });
}
async function requestMcpAppsJsonV2(
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
    throw mcpAppsErrorV2('desktop_trusted_session_required', 401);
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launch = desktopLaunchCapability(config);
  if (config.mode === 'local' && !launch)
    throw mcpAppsErrorV2('desktop_sidecar_launch_capability_required', 401);
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
    const payload = safeMcpAppsErrorPayloadV2(raw);
    const detail = payload?.detail;
    const message = mcpAppsRecordV2(detail) ? detail.message : detail;
    throw new DesktopApiError(
      typeof message === 'string' ? message : `HTTP ${response.status}`,
      response.status,
      payload,
    );
  }
  if (!contentType.includes('application/json'))
    throw mcpAppsErrorV2('project_mcp_apps_response_not_json', 502);
  return raw;
}
function safeMcpAppsErrorPayloadV2(raw: unknown): Readonly<Record<string, unknown>> | null {
  if (!mcpAppsRecordV2(raw)) return null;
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
  if (mcpAppsRecordV2(raw.detail)) {
    const detail: Record<string, unknown> = {};
    for (const key of ['reason_code', 'code', 'message', 'retryable']) {
      if (typeof raw.detail[key] === 'string' || typeof raw.detail[key] === 'boolean')
        detail[key] = raw.detail[key];
    }
    result.detail = Object.freeze(detail);
  }
  return Object.freeze(result);
}
