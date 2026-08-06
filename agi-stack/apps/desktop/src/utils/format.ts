import type {
  AuthState,
  DesktopRuntimeConfig,
  ProjectSummary,
  WorkspaceAuthorityCollection,
} from '../types';

export function compactArtifactValue(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > 180 ? `${text.slice(0, 177)}...` : text;
}

export function formatArtifactTime(sortTime: number): string {
  const date = new Date(sortTime);
  if (!Number.isFinite(date.getTime())) return 'unknown';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function timestampFromIso(value: string | null | undefined): number {
  if (!value) return 0;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

export function formatRunTime(value: string | null | undefined): string {
  const timestamp = timestampFromIso(value);
  if (!timestamp) return 'now';
  return formatArtifactTime(timestamp);
}

export function normalizeTimestamp(
  value: number | string | null | undefined,
): number {
  if (typeof value === 'string') {
    const parsed = timestampFromIso(value);
    return parsed || Date.now();
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) return Date.now();
  return value < 10_000_000_000 ? value * 1000 : value;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
}

export function arrayField(
  payload: Record<string, unknown>,
  key: string,
): unknown[] {
  const value = payload[key];
  return Array.isArray(value) ? value : [];
}

export function asRecordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function isRecordValue(
  value: unknown,
): value is Record<string, unknown> {
  return Boolean(asRecordValue(value));
}

export function readStringField(
  payload: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = payload[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
}

export function readTextField(
  payload: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = payload[key];
  return typeof value === 'string' ? value : undefined;
}

export function objectField(
  payload: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = payload[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function numberField(
  payload: Record<string, unknown>,
  key: string,
): number | null {
  const value = payload[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function waitForAbortableDelay(
  delayMs: number,
  signal: AbortSignal,
): Promise<boolean> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', cancel);
      resolve(true);
    }, delayMs);
    const cancel = () => {
      window.clearTimeout(timer);
      resolve(false);
    };
    signal.addEventListener('abort', cancel, { once: true });
  });
}

export function unavailableWorkspaceAuthority<
  T,
>(): WorkspaceAuthorityCollection<T> {
  return { status: 'unavailable', items: [], error: null };
}

export function loadingWorkspaceAuthority<
  T,
>(): WorkspaceAuthorityCollection<T> {
  return { status: 'loading', items: [], error: null };
}

export function failLoadingWorkspaceAuthority<T>(
  collection: WorkspaceAuthorityCollection<T>,
  error: string,
): WorkspaceAuthorityCollection<T> {
  return collection.status === 'loading'
    ? { status: 'error', items: [], error }
    : collection;
}

export async function resolveWorkspaceAuthority<T>(
  request: Promise<T[]>,
): Promise<WorkspaceAuthorityCollection<T>> {
  try {
    return { status: 'ready', items: await request, error: null };
  } catch (error) {
    return { status: 'error', items: [], error: formatError(error) };
  }
}

export function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export function formatConnectionError(
  error: unknown,
  apiBaseUrl: string,
): string {
  const message = formatError(error);
  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return `Cannot reach ${apiBaseUrl}. Start the agi-stack server or update the Server URL.`;
  }
  return message;
}

export function formatLoginError(error: unknown, apiBaseUrl: string): string {
  return formatConnectionError(error, apiBaseUrl);
}

export function workspaceLabel(
  workspace: { id: string; name?: string; title?: string } | undefined,
): string {
  return workspace?.name ?? workspace?.title ?? workspace?.id ?? 'No workspace';
}

export function desktopMCPAppSandboxProxyUrl(apiBaseUrl: string): string {
  try {
    return new URL('/static/sandbox_proxy.html', apiBaseUrl).toString();
  } catch {
    return window.location.href;
  }
}

export function projectSummaryFromConfig(
  config: DesktopRuntimeConfig,
): ProjectSummary | null {
  const projectId = config.projectId.trim();
  if (!projectId) return null;
  return {
    id: projectId,
    tenant_id: config.tenantId.trim(),
    name: projectId,
  };
}

export function resolveSidebarProjects(
  config: DesktopRuntimeConfig,
  authStatus: AuthState['status'],
  projects: ProjectSummary[],
): ProjectSummary[] {
  if (authStatus === 'signed_in') return projects;
  const configured = projectSummaryFromConfig(config);
  return configured ? [configured] : [];
}
