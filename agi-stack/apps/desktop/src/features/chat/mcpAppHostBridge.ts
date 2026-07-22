import type { AppRendererProps } from '@mcp-ui/client';

import type {
  DesktopMCPAppResourceListResponse,
  DesktopMCPAppResourceReadResponse,
  DesktopMCPAppSummary,
  DesktopMCPAppToolCallResponse,
} from '../../api/client';

type MCPAppCallToolResult = NonNullable<AppRendererProps['toolResult']>;

export type MCPAppHostContext = Readonly<{
  projectId: string;
  appId: string | null;
  serverName: string | null;
  originalToolName: string;
}>;

export type MCPAppHostClient = {
  listMCPApps?: (projectId: string) => Promise<DesktopMCPAppSummary[]>;
  callMCPAppTool?: (
    appId: string,
    toolName: string,
    argumentsValue: Record<string, unknown>,
  ) => Promise<DesktopMCPAppToolCallResponse>;
  callMCPAppToolDirect?: (
    projectId: string,
    serverName: string,
    toolName: string,
    argumentsValue: Record<string, unknown>,
  ) => Promise<DesktopMCPAppToolCallResponse>;
  readMCPAppResource?: (
    projectId: string,
    uri: string,
    serverName?: string | null,
  ) => Promise<DesktopMCPAppResourceReadResponse>;
  listMCPAppResources?: (
    projectId: string,
    serverName?: string | null,
  ) => Promise<DesktopMCPAppResourceListResponse>;
};

export type MCPAppResourceListResult = {
  resources: Array<{
    uri: string;
    name: string;
    mimeType?: string;
    description?: string;
  }>;
};

export async function callMCPAppTool(
  client: MCPAppHostClient,
  context: MCPAppHostContext,
  params: { name: string; arguments?: Record<string, unknown> },
): Promise<MCPAppCallToolResult> {
  const toolName = requiredText(params.name, 'MCP tool name');
  const argumentsValue = params.arguments ?? {};
  const appId = context.appId?.trim() ?? '';
  if (appId && !appId.startsWith('_synthetic_')) {
    if (!client.callMCPAppTool) throw new Error('MCP App tool proxy is unavailable');
    return normalizeToolResult(await client.callMCPAppTool(appId, toolName, argumentsValue));
  }

  const projectId = requiredText(context.projectId, 'project id');
  const apps = client.listMCPApps ? await client.listMCPApps(projectId) : [];
  const matchingApp = apps.find(
    (app) =>
      (!context.serverName || app.server_name === context.serverName) &&
      (app.tool_name === toolName || app.tool_name === context.originalToolName),
  );
  if (matchingApp) {
    if (!client.callMCPAppTool) throw new Error('MCP App tool proxy is unavailable');
    return normalizeToolResult(
      await client.callMCPAppTool(matchingApp.id, toolName, argumentsValue),
    );
  }

  if (!client.callMCPAppToolDirect) throw new Error('MCP App direct tool proxy is unavailable');
  const serverName = requiredText(context.serverName ?? '', 'MCP server name');
  return normalizeToolResult(
    await client.callMCPAppToolDirect(projectId, serverName, toolName, argumentsValue),
  );
}

export async function readMCPAppResource(
  client: MCPAppHostClient,
  context: MCPAppHostContext,
  uri: string,
): Promise<DesktopMCPAppResourceReadResponse> {
  if (!client.readMCPAppResource) throw new Error('MCP App resource proxy is unavailable');
  return client.readMCPAppResource(
    requiredText(context.projectId, 'project id'),
    requiredText(uri, 'MCP resource URI'),
    context.serverName,
  );
}

export async function listMCPAppResources(
  client: MCPAppHostClient,
  context: MCPAppHostContext,
): Promise<MCPAppResourceListResult> {
  if (!client.listMCPAppResources) return { resources: [] };
  try {
    const result = await client.listMCPAppResources(
      requiredText(context.projectId, 'project id'),
      context.serverName,
    );
    return {
      resources: result.resources.map((resource) => ({
        ...resource,
        name: resource.name ?? resource.uri,
      })),
    };
  } catch {
    return { resources: [] };
  }
}

export function mcpAppMessageText(params: unknown): string | null {
  const record = recordValue(params);
  const content = record?.content;
  const blocks = Array.isArray(content) ? content : [content];
  for (const block of blocks) {
    const candidate = recordValue(block);
    if (candidate?.type === 'text' && typeof candidate.text === 'string') {
      const text = candidate.text.trim();
      if (text) return text;
    }
  }
  return null;
}

export function safeMCPAppExternalUrl(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  return ['https:', 'http:', 'mailto:'].includes(url.protocol) ? url.toString() : null;
}

function normalizeToolResult(response: DesktopMCPAppToolCallResponse): MCPAppCallToolResult {
  return {
    content: response.content as MCPAppCallToolResult['content'],
    isError: response.is_error,
  };
}

function requiredText(value: string, label: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${label} is required`);
  return normalized;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
