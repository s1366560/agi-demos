export type McpAppSummary = {
  id: string;
  name: string;
  status: 'starting' | 'healthy' | 'degraded' | 'stopped' | 'error';
  visible: boolean;
  revision: number;
};

export type McpToolCall = {
  app_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  idempotency_key: string;
};

export type McpAppsClient = {
  listApps(projectId: string, signal?: AbortSignal): Promise<McpAppSummary[]>;
  listTools(projectId: string, appId: string, signal?: AbortSignal): Promise<unknown[]>;
  callTool(projectId: string, input: McpToolCall, signal?: AbortSignal): Promise<unknown>;
  listResources(
    projectId: string,
    appId: string,
    signal?: AbortSignal,
  ): Promise<unknown[]>;
  readResource(
    projectId: string,
    appId: string,
    uri: string,
    signal?: AbortSignal,
  ): Promise<unknown>;
};

export function createMcpAppsClient(authority: McpAppsClient): McpAppsClient {
  return Object.freeze({
    listApps: (projectId: string, signal?: AbortSignal) =>
      authority.listApps(projectId, signal),
    listTools: (projectId: string, appId: string, signal?: AbortSignal) =>
      authority.listTools(projectId, appId, signal),
    callTool: (projectId: string, input: McpToolCall, signal?: AbortSignal) =>
      authority.callTool(projectId, input, signal),
    listResources: (projectId: string, appId: string, signal?: AbortSignal) =>
      authority.listResources(projectId, appId, signal),
    readResource: (
      projectId: string,
      appId: string,
      uri: string,
      signal?: AbortSignal,
    ) => authority.readResource(projectId, appId, uri, signal),
  });
}
