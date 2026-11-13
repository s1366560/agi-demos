import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function toCallToolResult(value: unknown): CallToolResult {
  if (isRecord(value) && Array.isArray(value.content)) {
    return value as CallToolResult;
  }

  const text =
    typeof value === 'string'
      ? value
      : (() => {
          try {
            return JSON.stringify(value, null, 2);
          } catch {
            return String(value);
          }
        })();

  return {
    content: [{ type: 'text', text }],
  };
}

export function getMessageText(params: unknown): string | undefined {
  if (!isRecord(params)) return undefined;

  const content = params.content;
  if (Array.isArray(content)) {
    const contentBlocks = content as unknown[];
    const textBlock = contentBlocks.find((block) => {
      return isRecord(block) && block.type === 'text' && typeof block.text === 'string';
    });
    return isRecord(textBlock) && typeof textBlock.text === 'string' ? textBlock.text : undefined;
  }

  if (isRecord(content) && typeof content.text === 'string') {
    return content.text;
  }

  return undefined;
}

export function getMessageRole(params: unknown): string {
  if (!isRecord(params) || typeof params.role !== 'string') {
    return 'user';
  }
  return params.role;
}

export function getSandboxProxyUrl(): URL {
  const SANDBOX_PROXY_VERSION = '20260310-csp-open';
  // Accept both host-only (localhost:8000) and full URL forms
  // (http://localhost:8000/api/v1) from env configs.
  const envApiTarget =
    import.meta.env.VITE_API_HOST ||
    (import.meta.env as { VITE_API_URL?: string | undefined }).VITE_API_URL ||
    (window.location.host.includes(':3000') ? 'localhost:8000' : window.location.host);
  const apiHost = envApiTarget.replace(/^[a-z]+:\/\//i, '').split('/')[0] || 'localhost:8000';
  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
  const url = new URL(`${protocol}//${apiHost}/static/sandbox_proxy.html`);
  url.searchParams.set('v', SANDBOX_PROXY_VERSION);
  return url;
}

const renderKeys = new WeakMap<object, number>();
let renderSerial = 0;
/** Local React identity only; authorization remains in the operation context. */
export function getMcpAppRenderKeyV2(operation: object): number {
  let key = renderKeys.get(operation);
  if (key === undefined) {
    key = ++renderSerial;
    renderKeys.set(operation, key);
  }
  return key;
}
