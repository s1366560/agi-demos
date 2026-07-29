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
    idempotencyKey: string,
  ) => Promise<DesktopMCPAppToolCallResponse>;
  callMCPAppToolDirect?: (
    projectId: string,
    serverName: string,
    toolName: string,
    argumentsValue: Record<string, unknown>,
    idempotencyKey: string,
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

type MCPToolCallKeyStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

type MCPToolCallKeyLease = Readonly<{
  storageKey: string;
  idempotencyKey: string;
}>;

export type MCPToolCallKeyStore = Readonly<{
  acquire(
    context: MCPAppHostContext,
    toolName: string,
    argumentsValue: Record<string, unknown>,
  ): Promise<MCPToolCallKeyLease>;
  complete(lease: MCPToolCallKeyLease): void;
}>;

const MCP_TOOL_CALL_STORAGE_PREFIX = 'agistack:mcp-tool-call:v1:';
const MCP_TOOL_CALL_KEY_PREFIX = 'desktop-mcp-tool-call:';
const fallbackToolCallKeys = new Map<string, string>();
let defaultToolCallKeyStore: MCPToolCallKeyStore | null = null;

export function createMCPToolCallKeyStore(
  storage: MCPToolCallKeyStorage | null = browserStorage(),
  generateKey: () => string = secureRandomKey,
): MCPToolCallKeyStore {
  return Object.freeze({
    async acquire(context, toolName, argumentsValue) {
      const signature = canonicalJson({
        project_id: requiredText(context.projectId, 'project id'),
        app_id: context.appId?.trim() || null,
        server_name: context.serverName?.trim() || null,
        original_tool_name: requiredText(context.originalToolName, 'original MCP tool name'),
        tool_name: requiredText(toolName, 'MCP tool name'),
        arguments: argumentsValue,
      });
      const storageKey = `${MCP_TOOL_CALL_STORAGE_PREFIX}${await sha256Hex(signature)}`;
      const persisted = readToolCallKey(storage, storageKey);
      if (persisted) {
        return { storageKey, idempotencyKey: persisted };
      }
      const generated = `${MCP_TOOL_CALL_KEY_PREFIX}${requiredText(
        generateKey(),
        'generated MCP idempotency key',
      )}`;
      if (generated.length > 200 || containsControlCharacter(generated)) {
        throw new Error('generated MCP idempotency key is invalid');
      }
      persistToolCallKey(storage, storageKey, generated);
      return { storageKey, idempotencyKey: generated };
    },
    complete(lease) {
      if (storage) {
        storage.removeItem(lease.storageKey);
      } else {
        fallbackToolCallKeys.delete(lease.storageKey);
      }
    },
  });
}

export async function callMCPAppTool(
  client: MCPAppHostClient,
  context: MCPAppHostContext,
  params: { name: string; arguments?: Record<string, unknown> },
  keyStore: MCPToolCallKeyStore = getDefaultToolCallKeyStore(),
): Promise<MCPAppCallToolResult> {
  const toolName = requiredText(params.name, 'MCP tool name');
  const argumentsValue = params.arguments ?? {};
  const keyLease = await keyStore.acquire(context, toolName, argumentsValue);
  const appId = context.appId?.trim() ?? '';
  if (appId && !appId.startsWith('_synthetic_')) {
    if (!client.callMCPAppTool) throw new Error('MCP App tool proxy is unavailable');
    const result = normalizeToolResult(
      await client.callMCPAppTool(
        appId,
        toolName,
        argumentsValue,
        keyLease.idempotencyKey,
      ),
    );
    keyStore.complete(keyLease);
    return result;
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
    const result = normalizeToolResult(
      await client.callMCPAppTool(
        matchingApp.id,
        toolName,
        argumentsValue,
        keyLease.idempotencyKey,
      ),
    );
    keyStore.complete(keyLease);
    return result;
  }

  if (!client.callMCPAppToolDirect) throw new Error('MCP App direct tool proxy is unavailable');
  const serverName = requiredText(context.serverName ?? '', 'MCP server name');
  const result = normalizeToolResult(
    await client.callMCPAppToolDirect(
      projectId,
      serverName,
      toolName,
      argumentsValue,
      keyLease.idempotencyKey,
    ),
  );
  keyStore.complete(keyLease);
  return result;
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
  if (!client.listMCPAppResources) {
    throw new Error('MCP App resource proxy is unavailable');
  }
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

function getDefaultToolCallKeyStore(): MCPToolCallKeyStore {
  defaultToolCallKeyStore ??= createMCPToolCallKeyStore();
  return defaultToolCallKeyStore;
}

function browserStorage(): MCPToolCallKeyStorage | null {
  try {
    return typeof globalThis.localStorage === 'undefined' ? null : globalThis.localStorage;
  } catch {
    return null;
  }
}

function readToolCallKey(
  storage: MCPToolCallKeyStorage | null,
  storageKey: string,
): string | null {
  const value = storage ? storage.getItem(storageKey) : (fallbackToolCallKeys.get(storageKey) ?? null);
  if (
    value?.startsWith(MCP_TOOL_CALL_KEY_PREFIX) &&
    value.length <= 200 &&
    !containsControlCharacter(value)
  ) {
    return value;
  }
  if (value !== null) {
    if (storage) storage.removeItem(storageKey);
    else fallbackToolCallKeys.delete(storageKey);
  }
  return null;
}

function persistToolCallKey(
  storage: MCPToolCallKeyStorage | null,
  storageKey: string,
  value: string,
): void {
  if (storage) storage.setItem(storageKey, value);
  else fallbackToolCallKeys.set(storageKey, value);
}

function secureRandomKey(): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (!randomUUID) throw new Error('secure MCP idempotency key generation is unavailable');
  return randomUUID.call(globalThis.crypto);
}

function containsControlCharacter(value: string): boolean {
  return Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint < 0x20 || codePoint === 0x7f;
  });
}

async function sha256Hex(value: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new Error('secure MCP action persistence is unavailable');
  const digest = await subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalValue(value));
}

function canonicalValue(value: unknown): unknown {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item));
  const record = recordValue(value);
  if (record) {
    return Object.fromEntries(
      Object.entries(record)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
        .map(([key, item]) => [key, canonicalValue(item)]),
    );
  }
  throw new Error('MCP tool arguments must be JSON serializable');
}
