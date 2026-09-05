import type { DesktopMCPAppSummary } from '../api/client';
import {
  freezeMcpAppsJsonV2,
  mcpAppsErrorV2,
  mcpAppsRecordV2,
  type McpAppsInputV2,
  type McpAppsMethodV2,
  type McpAppsResultsV2,
  type McpAppsScopeV2,
} from './desktopProjectMcpAppsOperationContractV2';

function invalid(): never {
  throw mcpAppsErrorV2('project_mcp_apps_response_invalid', 502);
}
export function requireMcpAppIdentityV2(
  raw: unknown,
  scope: McpAppsScopeV2,
  id?: string,
): DesktopMCPAppSummary {
  if (
    !mcpAppsRecordV2(raw) ||
    typeof raw.id !== 'string' ||
    !raw.id ||
    raw.tenant_id !== scope.tenantId ||
    raw.project_id !== scope.projectId ||
    (id !== undefined && raw.id !== id)
  )
    invalid();
  for (const key of ['server_name', 'tool_name']) {
    if (raw[key] !== undefined && raw[key] !== null && typeof raw[key] !== 'string') invalid();
  }
  return Object.freeze({
    id: raw.id,
    ...(raw.server_name === undefined ? {} : { server_name: raw.server_name as string | null }),
    ...(raw.tool_name === undefined ? {} : { tool_name: raw.tool_name as string | null }),
  });
}
export function requireMcpAppsResultV2<K extends McpAppsMethodV2>(
  method: K,
  raw: unknown,
  input: McpAppsInputV2<K>,
): McpAppsResultsV2[K] {
  let result: unknown;
  if (method === 'listMCPApps') {
    if (!Array.isArray(raw)) invalid();
    const ids = new Set<string>();
    result = raw.map((item) => {
      const app = requireMcpAppIdentityV2(item, input.scope);
      if (ids.has(app.id)) invalid();
      ids.add(app.id);
      return app;
    });
  } else {
    if (!mcpAppsRecordV2(raw)) invalid();
    if (method === 'callMCPAppTool' || method === 'callMCPAppToolDirect') {
      if (!Array.isArray(raw.content) || typeof raw.is_error !== 'boolean') invalid();
      optionalString(raw.error_message);
      if (
        raw.error_code !== undefined &&
        raw.error_code !== null &&
        typeof raw.error_code !== 'string' &&
        !(typeof raw.error_code === 'number' && Number.isFinite(raw.error_code))
      )
        invalid();
      if (raw.duplicate !== undefined && typeof raw.duplicate !== 'boolean') invalid();
      result = {
        content: raw.content,
        is_error: raw.is_error,
        ...optional(raw, 'error_message'),
        ...optional(raw, 'error_code'),
        ...optional(raw, 'duplicate'),
      };
    } else if (method === 'callMCPToolByServerId') {
      if (
        !Object.hasOwn(raw, 'result') ||
        typeof raw.is_error !== 'boolean' ||
        typeof raw.execution_time_ms !== 'number' ||
        !Number.isFinite(raw.execution_time_ms) ||
        raw.execution_time_ms < 0
      )
        invalid();
      optionalString(raw.error_message);
      if (raw.duplicate !== undefined && typeof raw.duplicate !== 'boolean') invalid();
      result = {
        result: raw.result,
        is_error: raw.is_error,
        execution_time_ms: raw.execution_time_ms,
        ...optional(raw, 'error_message'),
        ...optional(raw, 'duplicate'),
      };
    } else if (method === 'readMCPAppResource') {
      if (!Array.isArray(raw.contents)) invalid();
      if (raw._meta !== undefined && !mcpAppsRecordV2(raw._meta)) invalid();
      for (const item of raw.contents) {
        if (
          !mcpAppsRecordV2(item) ||
          typeof item.uri !== 'string' ||
          !item.uri ||
          (item._meta !== undefined && !mcpAppsRecordV2(item._meta)) ||
          (item.mimeType !== undefined && typeof item.mimeType !== 'string') ||
          (item.text !== undefined && typeof item.text !== 'string') ||
          (item.blob !== undefined && typeof item.blob !== 'string') ||
          (typeof item.text !== 'string' && typeof item.blob !== 'string')
        )
          invalid();
      }
      // MCP ResourceContents is extensible: preserve text/blob and standard _meta fields.
      result = { contents: raw.contents, ...optional(raw, '_meta') };
    } else {
      if (!Array.isArray(raw.resources)) invalid();
      if (raw._meta !== undefined && !mcpAppsRecordV2(raw._meta)) invalid();
      for (const item of raw.resources) {
        if (!mcpAppsRecordV2(item) || typeof item.uri !== 'string' || !item.uri) invalid();
        if (item._meta !== undefined && !mcpAppsRecordV2(item._meta)) invalid();
        for (const key of ['name', 'mimeType', 'description'])
          if (item[key] !== undefined && typeof item[key] !== 'string') invalid();
      }
      // Cloud lists all project resources; server_name is not a server-filter guarantee.
      result = { resources: raw.resources, ...optional(raw, '_meta') };
    }
  }
  try {
    return freezeMcpAppsJsonV2(result) as McpAppsResultsV2[K];
  } catch {
    return invalid();
  }
}
function optionalString(value: unknown): void {
  if (value !== undefined && value !== null && typeof value !== 'string') invalid();
}
function optional(value: Record<string, unknown>, key: string): Record<string, unknown> {
  return value[key] === undefined ? {} : { [key]: value[key] };
}
