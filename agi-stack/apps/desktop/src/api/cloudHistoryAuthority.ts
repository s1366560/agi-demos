import type { DesktopRuntimeConfig } from '../types';
import { desktopVaultBoundCloudRequestBroker, type VaultBoundCloudRequest } from './cloudRequestBroker';

export class CloudHistoryTransportError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(status: number, payload: unknown, message: string) {
    super(message);
    this.name = 'CloudHistoryTransportError';
    this.status = status;
    this.payload = payload;
  }
}

const CONVERSATION_HISTORY =
  /^\/api\/v1\/agent\/conversations(?:\/[^/]+(?:\/(?:messages|events|execution|execution-status|tool-executions))?)?$/;
const SESSION_HISTORY = /^\/api\/v1\/agent\/conversations\/[^/]+\/session$/;
const RUN_REPLAY = /^\/api\/v1\/agent\/runs\/[^/]+\/(?:summary|local-events)$/;
const WORKSPACE_MESSAGES =
  /^\/api\/v1\/tenants\/[^/]+\/projects\/[^/]+\/workspaces\/[^/]+\/messages$/;

export function isCloudHistoryRead(
  method: string,
  path: string,
  includeSession = false,
): boolean {
  if (method.toUpperCase() !== 'GET') return false;
  const pathname = path.split('?', 1)[0] ?? path;
  if (SESSION_HISTORY.test(pathname)) return includeSession;
  return (
    CONVERSATION_HISTORY.test(pathname) ||
    RUN_REPLAY.test(pathname) ||
    WORKSPACE_MESSAGES.test(pathname)
  );
}

export function localHistoryMustUseCloud(
  config: DesktopRuntimeConfig,
  method: string,
  path: string,
  includeSession = false,
): boolean {
  return config.mode === 'local' && isCloudHistoryRead(method, path, includeSession);
}

type HistoryRequest = Readonly<{
  method?: VaultBoundCloudRequest['method'];
  signal?: AbortSignal;
}>;

export async function requestCloudHistory<T>(path: string, options: HistoryRequest = {}): Promise<T> {
  const broker = desktopVaultBoundCloudRequestBroker();
  if (!broker) {
    throw new CloudHistoryTransportError(503, {
      detail: 'cloud_history_unavailable',
      code: 'cloud_history_unavailable',
    }, 'cloud_history_unavailable');
  }
  const response = await broker.requestResponse({
    path,
    method: options.method ?? 'GET',
    signal: options.signal,
  });
  if (response.status < 200 || response.status >= 300) {
    throw new CloudHistoryTransportError(
      response.status,
      response.body,
      cloudHistoryErrorMessage(response.body, response.status),
    );
  }
  return response.body as T;
}

function cloudHistoryErrorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail === 'object') {
      for (const field of ['message', 'detail', 'code']) {
        const value = (detail as Record<string, unknown>)[field];
        if (typeof value === 'string' && value.trim()) return value;
      }
    }
  }
  return `HTTP ${status}`;
}
