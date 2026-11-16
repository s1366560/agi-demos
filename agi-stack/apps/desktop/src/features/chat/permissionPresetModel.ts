import type {
  DesktopApprovalRequest,
  HitlResponseSubmission,
  PermissionRequestContext,
} from '../../types';

/**
 * Session-scoped approval autonomy dial (P1-2 "审批即对话").
 *
 * Auto-approval reads the structured request kind and native grant binding.
 * No text/keyword risk or permission-category inference is performed.
 */

export type PermissionPreset = 'default' | 'relaxed' | 'full';

const AUTO_EDIT_PERMISSIONS = new Set(['write', 'workspace_file_write', 'workspace_task_write']);

export const PERMISSION_PRESETS: readonly PermissionPreset[] = [
  'default',
  'relaxed',
  'full',
];

export const PERMISSION_PRESET_STORAGE_PREFIX =
  'agistack.desktop.permission-preset:v1';
export const FULL_ACCESS_WARNING_STORAGE_PREFIX =
  'agistack.desktop.permission-preset-full-access-warning:v1';

type PermissionPresetStorage = Pick<Storage, 'getItem' | 'setItem'>;

export function parsePermissionPreset(raw: string | null): PermissionPreset {
  return raw === 'relaxed' || raw === 'full' ? raw : 'default';
}

/**
 * Presets persist per conversation+workspace so revisiting a conversation
 * restores the dial the user set for it.
 */
export function permissionPresetScope(
  workspaceId: string,
  conversationId: string,
): string | null {
  const workspace = workspaceId.trim();
  const conversation = conversationId.trim();
  if (!workspace || !conversation) return null;
  return [workspace, conversation].join('\u0000');
}

export function readPermissionPreset(
  scope: string,
  storage: PermissionPresetStorage | null = browserStorage(),
): PermissionPreset {
  if (!storage) return 'default';
  try {
    return parsePermissionPreset(
      storage.getItem(`${PERMISSION_PRESET_STORAGE_PREFIX}:${scope}`),
    );
  } catch {
    return 'default';
  }
}

export function writePermissionPreset(
  scope: string,
  preset: PermissionPreset,
  storage: PermissionPresetStorage | null = browserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(`${PERMISSION_PRESET_STORAGE_PREFIX}:${scope}`, preset);
  } catch {
    // The in-memory preset remains authoritative when storage is unavailable.
  }
}

/**
 * The full-access warning is acknowledged once per workspace, not per
 * conversation: enabling the broadest autonomy dial anywhere in a workspace
 * the user has already warned about does not re-prompt.
 */
export function fullAccessWarningScope(workspaceId: string): string {
  return workspaceId.trim() || 'default';
}

export function readFullAccessWarningAcknowledged(
  workspaceId: string,
  storage: PermissionPresetStorage | null = browserStorage(),
): boolean {
  if (!storage) return false;
  try {
    return (
      storage.getItem(
        `${FULL_ACCESS_WARNING_STORAGE_PREFIX}:${fullAccessWarningScope(workspaceId)}`,
      ) === 'acknowledged'
    );
  } catch {
    return false;
  }
}

export function acknowledgeFullAccessWarning(
  workspaceId: string,
  storage: PermissionPresetStorage | null = browserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(
      `${FULL_ACCESS_WARNING_STORAGE_PREFIX}:${fullAccessWarningScope(workspaceId)}`,
      'acknowledged',
    );
  } catch {
    // The in-memory acknowledgement remains authoritative when storage is unavailable.
  }
}

/**
 * Relaxed mode approves declared workspace write categories only. Missing
 * declarations remain explicit; risk and tool names never imply authority.
 */
export function autoApprovalForPermissionRequest(
  preset: PermissionPreset,
  request: Pick<DesktopApprovalRequest, 'kind'> & {
    permission?: Pick<PermissionRequestContext, 'risk_level' | 'permission'> | null;
    decision?: DesktopApprovalRequest['decision'];
    native_binding?: unknown;
  },
): 'allow' | null {
  if (preset === 'default') return null;
  if (request.kind !== 'permission' || !request.permission) return null;
  // Device application and MCP grants require explicit approval. A malformed
  // native binding must not fall back to ordinary runtime tool auto-approval.
  if (
    request.decision?.target?.kind === 'computer_app' ||
    request.decision?.target?.kind === 'device_mcp_tool' ||
    Object.hasOwn(request, 'native_binding')
  )
    return null;
  if (preset === 'full') return 'allow';
  // Only the tool's declared permission category authorizes automatic edits.
  const permission = request.permission.permission;
  return permission != null && AUTO_EDIT_PERMISSIONS.has(permission) ? 'allow' : null;
}

/**
 * The HITL respond contract for permission asks accepts exactly
 * `{action, granted, scope}` — any extra field is rejected with 400. The
 * resolved-with-preset timeline marker is therefore folded locally by the
 * caller after the submission succeeds, never sent on the wire.
 */
export function autoApprovalResponseData(): Record<string, unknown> {
  return {
    action: 'allow',
    granted: true,
    scope: 'once',
  };
}

export function autoApprovalSubmission(
  request: DesktopApprovalRequest,
  preset: PermissionPreset,
): HitlResponseSubmission | null {
  if (autoApprovalForPermissionRequest(preset, request) !== 'allow')
    return null;
  const revision =
    typeof request.authority_revision === 'number' &&
    Number.isFinite(request.authority_revision)
      ? request.authority_revision
      : undefined;
  return {
    requestId: request.id,
    hitlType: 'permission',
    responseData: autoApprovalResponseData(),
    ...(revision === undefined ? {} : { expectedRevision: revision }),
    idempotencyKey: [
      request.id,
      revision ?? 'unversioned',
      'preset-auto',
      preset,
    ].join(':'),
  };
}

/** Denial payload; feedback rides the existing `feedback` response field. */
export function permissionDenialResponseData(
  feedback?: string,
): Record<string, unknown> {
  const trimmed = feedback?.trim();
  return {
    action: 'deny',
    granted: false,
    scope: 'once',
    ...(trimmed ? { feedback: trimmed } : {}),
  };
}

function browserStorage(): PermissionPresetStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}
