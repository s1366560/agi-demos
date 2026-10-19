import type { DesktopRuntimeConfig } from '../../types';

type WorkspaceSelectionScope = Pick<
  DesktopRuntimeConfig,
  'mode' | 'apiBaseUrl' | 'tenantId' | 'projectId'
>;

type WorkspaceSelectionStorage = Pick<Storage, 'getItem' | 'setItem'>;

const STORAGE_PREFIX = 'agistack.desktop.workspace-selection:v1:';

/** A local sidecar endpoint changes on restart; its profile is isolated by localStorage. */
export function workspaceSelectionPreferenceKey(
  config: WorkspaceSelectionScope,
  userId: string | null | undefined,
): string | null {
  const user = nonemptyIdentifier(userId);
  const tenant = nonemptyIdentifier(config.tenantId);
  const project = nonemptyIdentifier(config.projectId);
  if (!user || !tenant || !project) return null;

  const backend =
    config.mode === 'local'
      ? 'native-local'
      : config.mode === 'cloud'
        ? canonicalCloudBackend(config.apiBaseUrl)
        : null;
  if (!backend) return null;

  return `${STORAGE_PREFIX}${encodeURIComponent(
    JSON.stringify([config.mode, backend, user, tenant, project]),
  )}`;
}

/** null means no saved choice; an empty string explicitly selects unbound conversations. */
export function readWorkspaceSelectionPreference(
  config: WorkspaceSelectionScope,
  userId: string | null | undefined,
  storage: WorkspaceSelectionStorage | null = browserStorage(),
): string | null {
  const key = workspaceSelectionPreferenceKey(config, userId);
  if (!storage || !key) return null;
  try {
    const raw = storage.getItem(key);
    if (raw === null) return null;
    const value: unknown = JSON.parse(raw);
    if (
      !value ||
      typeof value !== 'object' ||
      Array.isArray(value) ||
      Object.keys(value).length !== 2 ||
      !('version' in value) ||
      value.version !== 1 ||
      !('workspaceId' in value) ||
      typeof value.workspaceId !== 'string' ||
      value.workspaceId !== value.workspaceId.trim()
    ) {
      return null;
    }
    return value.workspaceId;
  } catch {
    return null;
  }
}

export function writeWorkspaceSelectionPreference(
  config: WorkspaceSelectionScope,
  userId: string | null | undefined,
  workspaceId: string,
  storage: WorkspaceSelectionStorage | null = browserStorage(),
): void {
  const key = workspaceSelectionPreferenceKey(config, userId);
  if (!storage || !key || typeof workspaceId !== 'string') return;
  try {
    storage.setItem(key, JSON.stringify({ version: 1, workspaceId: workspaceId.trim() }));
  } catch {
    // Selection remains usable in memory when profile storage is denied or full.
  }
}

function nonemptyIdentifier(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function canonicalCloudBackend(apiBaseUrl: string): string | null {
  try {
    const url = new URL(apiBaseUrl);
    if (
      (url.protocol !== 'http:' && url.protocol !== 'https:') ||
      url.username ||
      url.password
    ) {
      return null;
    }
    // Auth query parameters and fragments must never enter a preference key.
    return `${url.origin}${url.pathname.replace(/\/+$/, '')}`;
  } catch {
    return null;
  }
}

function browserStorage(): WorkspaceSelectionStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}
