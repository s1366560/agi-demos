import { foldHitlResponseTimelineItems } from './hitlResponseEventModel';

import type { AgentTimelineItem, DesktopRuntimeConfig } from '../../types';
import type { PermissionPreset } from './permissionPresetModel';

export type PermissionAutoApprovalEntry = Readonly<{
  requestId: string;
  preset: Exclude<PermissionPreset, 'default'>;
}>;

export type PermissionAutoApprovalHistory = readonly PermissionAutoApprovalEntry[];

type HistoryStorage = Pick<Storage, 'getItem' | 'setItem'>;
type HistoryScopeConfig = Pick<
  DesktopRuntimeConfig,
  'mode' | 'apiBaseUrl' | 'tenantId' | 'projectId' | 'workspaceId'
>;

export const PERMISSION_AUTO_APPROVAL_STORAGE_PREFIX =
  'agistack.desktop.permission-auto-approval:v1';
export const MAX_PERMISSION_AUTO_APPROVAL_HISTORY = 256;

/** Isolate provenance across servers and accounts, including unbound conversations. */
export function permissionAutoApprovalScope(
  config: HistoryScopeConfig,
  conversationId: string,
): string | null {
  const tenant = config.tenantId.trim();
  const project = config.projectId.trim();
  const conversation = conversationId.trim();
  if (!tenant || !project || !conversation) return null;
  if (config.mode !== 'local' && config.mode !== 'cloud') return null;
  try {
    const base = new URL(config.apiBaseUrl);
    // Credential-bearing URLs must never become local-storage keys.
    if (
      !['http:', 'https:'].includes(base.protocol) ||
      base.username ||
      base.password ||
      base.search ||
      base.hash
    )
      return null;
    const apiBase = `${base.origin}${base.pathname.replace(/\/+$/, '')}`;
    return JSON.stringify([
      config.mode,
      apiBase,
      tenant,
      project,
      config.workspaceId.trim(),
      conversation,
    ]);
  } catch {
    return null;
  }
}

export function readPermissionAutoApprovalHistory(
  scope: string | null,
  storage: HistoryStorage | null = browserStorage(),
): PermissionAutoApprovalHistory {
  if (!scope || !storage) return [];
  try {
    const raw: unknown = JSON.parse(
      storage.getItem(`${PERMISSION_AUTO_APPROVAL_STORAGE_PREFIX}:${scope}`) ?? '[]',
    );
    return normalizedEntries(raw);
  } catch {
    return [];
  }
}

/** Call only after the permission response succeeds; a preset alone is not provenance. */
export function recordSuccessfulPermissionAutoApproval(
  scope: string | null,
  requestId: string,
  preset: PermissionPreset,
  storage: HistoryStorage | null = browserStorage(),
): PermissionAutoApprovalHistory {
  const current = readPermissionAutoApprovalHistory(scope, storage);
  if (!scope || !requestId.trim() || (preset !== 'relaxed' && preset !== 'full')) return current;
  const next = normalizedEntries([...current, { requestId: requestId.trim(), preset }]);
  try {
    storage?.setItem(`${PERMISSION_AUTO_APPROVAL_STORAGE_PREFIX}:${scope}`, JSON.stringify(next));
  } catch {
    // Keep confirmed in-memory provenance usable even if persistence is unavailable.
  }
  return next;
}

/** Hide only confirmed automatic permission replies; raw authority remains unchanged. */
export function hideConfirmedAutoApprovedPermissions(
  items: readonly AgentTimelineItem[],
  history: PermissionAutoApprovalHistory,
  pendingAutomaticRequestIds: ReadonlySet<string> = new Set<string>(),
): AgentTimelineItem[] {
  const automaticRequestIds = new Set(history.map((entry) => entry.requestId));
  return foldHitlResponseTimelineItems([...items]).filter((item) => {
    if (item.type !== 'permission_asked') return true;
    const payload =
      item.payload && typeof item.payload === 'object' && !Array.isArray(item.payload)
        ? (item.payload as Record<string, unknown>)
        : null;
    const granted = item.granted ?? payload?.granted;
    if (granted === false) return true;
    const requestId =
      item.requestId ?? item.request_id ?? payload?.requestId ?? payload?.request_id;
    if (item.answered !== true) {
      // Only the caller's in-flight, validated auto-submissions may suppress a
      // pending card. Removing an ID after failure immediately restores fallback.
      return typeof requestId !== 'string' || !pendingAutomaticRequestIds.has(requestId);
    }
    if (granted !== true) return true;
    if (item.autoApprovalPreset === 'full' || item.autoApprovalPreset === 'relaxed') return false;
    return typeof requestId !== 'string' || !automaticRequestIds.has(requestId);
  });
}

function normalizedEntries(raw: unknown): PermissionAutoApprovalHistory {
  if (!Array.isArray(raw)) return [];
  const entries = new Map<string, PermissionAutoApprovalEntry>();
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const { requestId, preset } = item as Record<string, unknown>;
    if (typeof requestId !== 'string' || !requestId.trim()) continue;
    if (preset !== 'relaxed' && preset !== 'full') continue;
    const id = requestId.trim();
    entries.delete(id);
    entries.set(id, { requestId: id, preset });
    if (entries.size > MAX_PERMISSION_AUTO_APPROVAL_HISTORY) {
      const oldest = entries.keys().next().value;
      if (oldest !== undefined) entries.delete(oldest);
    }
  }
  return [...entries.values()];
}

function browserStorage(): HistoryStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}
