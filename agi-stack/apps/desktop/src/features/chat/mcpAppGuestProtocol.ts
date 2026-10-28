/** Serializable messages for the dedicated MCP App renderer, never desktop commands. */
export const MCP_APP_GUEST_CHANNEL = 'agistack:mcp-app-guest';
export const MCP_APP_GUEST_EVENT = 'agistack:mcp-app-guest-event';
export const MCP_APP_GUEST_METHODS = [
  'callTool',
  'readResource',
  'listResources',
  'listResourceTemplates',
  'listPrompts',
  'fallbackRequest',
  'message',
  'openLink',
  'sizeChanged',
  'error',
] as const;
export type McpAppGuestMethod = (typeof MCP_APP_GUEST_METHODS)[number];
export type McpAppGuestIdentity = Readonly<{
  guestId: string;
  frameName: string;
  tabId?: string;
}>;
export type McpAppGuestConfig = Readonly<{
  toolName: string;
  html?: string;
  toolResourceUri?: string;
  toolInput?: Record<string, unknown>;
  toolResult?: unknown;
  sandbox: Readonly<{
    url: string;
    permissions?: string;
    csp?: Readonly<Record<string, readonly string[] | undefined>>;
  }>;
}>;
export type McpAppGuestActivation = McpAppGuestIdentity & { config: McpAppGuestConfig };
export type McpAppGuestRequest = McpAppGuestIdentity & {
  kind: 'request';
  requestId: string;
  method: McpAppGuestMethod;
  params: unknown;
};
export type McpAppGuestHostEvent =
  | McpAppGuestRequest
  | (McpAppGuestIdentity & {
      kind: 'cancel';
      requestId: string;
    })
  | (McpAppGuestIdentity & { kind: 'retired'; reason: string });
export type McpAppGuestEvent =
  | { kind: 'activate'; value: McpAppGuestActivation }
  | { kind: 'retire'; frameName: string };
export type McpAppGuestBridge = Readonly<{
  initialize(): Promise<McpAppGuestActivation>;
  ready(input: McpAppGuestIdentity): Promise<void>;
  request(input: McpAppGuestRequest): Promise<unknown>;
  cancel(input: McpAppGuestIdentity & { requestId: string }): Promise<void>;
  subscribe(listener: (event: McpAppGuestEvent) => void): () => void;
}>;
export type McpAppGuestRect = Readonly<{ x: number; y: number; width: number; height: number }>;

/** Values whose change replaces the App document; tool input/result updates are notifications. */
export function mcpAppGuestDocumentKey(config: McpAppGuestConfig | null): string {
  if (!config) return '';
  return JSON.stringify([config.toolName, config.html, config.toolResourceUri, config.sandbox]);
}
