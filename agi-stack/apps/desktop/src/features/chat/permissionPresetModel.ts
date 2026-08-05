import type {
  DesktopApprovalRequest,
  HitlResponseSubmission,
  PermissionRequestContext,
  WorkspacePermissionMode,
} from '../../types';

/**
 * Session-scoped approval autonomy dial (P1-2 "审批即对话").
 *
 * Auto-approval here is a structural category check only: it reads the
 * validated `risk_level` enum and the request `kind` from the permission
 * request contract (Agent First rule — no text/keyword risk heuristics).
 */

export type PermissionPreset = 'default' | 'relaxed' | 'full';

export const PERMISSION_PRESETS: readonly PermissionPreset[] = [
  'default',
  'relaxed',
  'full',
];

export const PERMISSION_PRESET_STORAGE_PREFIX =
  'agistack.desktop.permission-preset:v1';
export const FULL_ACCESS_WARNING_STORAGE_PREFIX =
  'agistack.desktop.permission-preset-full-access-warning:v1';

export function permissionModeForPreset(
  preset: PermissionPreset,
): WorkspacePermissionMode {
  if (preset === 'full') return 'full_access';
  if (preset === 'relaxed') return 'automatic';
  return 'ask';
}

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
 * Low-risk derivation: the backend classifies every permission request into
 * the `risk_level` enum ('low' | 'medium' | 'high'); "relaxed" auto-allows
 * exactly the 'low' membership. No keyword matching on tool names or actions.
 */
export function autoApprovalForPermissionRequest(
  preset: PermissionPreset,
  request: Pick<DesktopApprovalRequest, 'kind'> & {
    permission?: Pick<PermissionRequestContext, 'risk_level'> | null;
  },
): 'allow' | null {
  if (preset === 'default') return null;
  if (request.kind !== 'permission' || !request.permission) return null;
  if (preset === 'full') return 'allow';
  return request.permission.risk_level === 'low' ? 'allow' : null;
}

/**
 * Auto-approvals stay truthful on the wire: the response carries
 * `auto_approved` + `preset` markers (stored in `response_data` alongside the
 * granted flag, exactly like the existing `scope` extra) so the timeline can
 * render a resolved-with-preset marker instead of a silent approval.
 */
export function autoApprovalResponseData(
  preset: PermissionPreset,
): Record<string, unknown> {
  return {
    action: 'allow',
    granted: true,
    scope: 'once',
    auto_approved: true,
    preset,
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
    responseData: autoApprovalResponseData(preset),
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
