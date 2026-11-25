/**
 * Per-conversation agent permission mode.
 *
 * Controls how incoming `permission_asked` requests are handled in the web
 * client: ask every time (default), auto-approve edit/write permissions, or
 * auto-approve everything. The mode only automates the user's own Allow click
 * on requests the backend already classified as ASK; it never bypasses DENY
 * rules enforced server-side.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import { PERMISSION_MODES, type AgentPermissionMode } from '../../chat/composerOptions';
export { PERMISSION_MODES, type AgentPermissionMode } from '../../chat/composerOptions';

export function isAgentPermissionMode(value: unknown): value is AgentPermissionMode {
  return typeof value === 'string' && PERMISSION_MODES.includes(value as AgentPermissionMode);
}

/**
 * Permission names (static metadata declared on tool definitions) that count as
 * file/workspace edits for the `auto_edit` mode. Set membership on declared
 * permission names only - no text matching on tool arguments.
 */
const EDIT_PERMISSION_NAMES = new Set<string>([
  'write',
  'workspace_file_write',
  'workspace_task_write',
]);

interface PermissionModeState {
  modesByConversation: Record<string, AgentPermissionMode>;
  autoApprovedRequestIds: Record<string, string[]>;
  pendingAutoApprovalIds: Record<string, string[]>;
  beginAutoApproval: (conversationId: string, requestId: string) => boolean;
  completeAutoApproval: (
    conversationId: string,
    requestId: string,
    granted: boolean,
    explicitAutomatic?: boolean
  ) => void;
  setPermissionMode: (conversationId: string, mode: AgentPermissionMode) => void;
  clearConversation: (conversationId: string) => void;
  getPermissionMode: (conversationId: string) => AgentPermissionMode;
}

export const useAgentPermissionModeStore = create<PermissionModeState>()(
  devtools(
    persist(
      (set, get) => ({
        modesByConversation: {},
        autoApprovedRequestIds: {},
        pendingAutoApprovalIds: {},
        beginAutoApproval: (conversationId, requestId) => {
          const pending = get().pendingAutoApprovalIds[conversationId] ?? [];
          if (!conversationId || !requestId || pending.includes(requestId)) return false;
          set((state) => ({
            pendingAutoApprovalIds: {
              ...state.pendingAutoApprovalIds,
              [conversationId]: [...pending, requestId],
            },
          }));
          return true;
        },
        completeAutoApproval: (conversationId, requestId, granted, explicitAutomatic = false) => {
          if (!conversationId || !requestId) return;
          const pending = get().pendingAutoApprovalIds[conversationId] ?? [];
          const approved = get().autoApprovedRequestIds[conversationId] ?? [];
          const automatic = explicitAutomatic;
          const nextApproved =
            granted && automatic
              ? [...new Set([...approved, requestId])]
              : granted
                ? approved
                : approved.filter((id) => id !== requestId);
          set((state) => ({
            pendingAutoApprovalIds: {
              ...state.pendingAutoApprovalIds,
              [conversationId]: pending.filter((id) => id !== requestId),
            },
            autoApprovedRequestIds: {
              ...state.autoApprovedRequestIds,
              [conversationId]: nextApproved,
            },
          }));
        },

        setPermissionMode: (conversationId, mode) =>
          set(
            (state) =>
              state.modesByConversation[conversationId] === mode
                ? state
                : {
                    modesByConversation: { ...state.modesByConversation, [conversationId]: mode },
                  },
            false,
            'permissionMode/set'
          ),

        clearConversation: (conversationId) =>
          set((state) => {
            if (
              !(conversationId in state.modesByConversation) &&
              !(conversationId in state.autoApprovedRequestIds) &&
              !(conversationId in state.pendingAutoApprovalIds)
            )
              return state;
            const { [conversationId]: _removed, ...rest } = state.modesByConversation;
            const { [conversationId]: _approved, ...approved } = state.autoApprovedRequestIds;
            const { [conversationId]: _pending, ...pending } = state.pendingAutoApprovalIds;
            return {
              modesByConversation: rest,
              autoApprovedRequestIds: approved,
              pendingAutoApprovalIds: pending,
            };
          }),

        getPermissionMode: (conversationId) => get().modesByConversation[conversationId] ?? 'ask',
      }),
      {
        name: 'agent-permission-mode',
        version: 1,
        // Earlier versions inferred automatic origin from a local pending send.
        migrate: () => ({ autoApprovedRequestIds: {} }),
        // Only confirmed automatic verdicts survive reload. Pending sends are not approvals.
        partialize: ({ autoApprovedRequestIds }) => ({
          autoApprovedRequestIds,
        }),
        merge: (persisted, current) => {
          const merged = { ...current };
          if (persisted && typeof persisted === 'object') {
            const stored = persisted as {
              modesByConversation?: unknown;
              autoApprovedRequestIds?: unknown;
            };
            if (
              stored.autoApprovedRequestIds &&
              typeof stored.autoApprovedRequestIds === 'object'
            ) {
              merged.autoApprovedRequestIds = Object.fromEntries(
                Object.entries(stored.autoApprovedRequestIds)
                  .filter(([, ids]) => Array.isArray(ids))
                  .map(([conversationId, ids]) => [
                    conversationId,
                    (ids as unknown[]).filter(
                      (id): id is string => typeof id === 'string' && id.length > 0
                    ),
                  ])
              );
            }
            // Modes are server-owned. Legacy browser preferences must never grant authority.
          }
          return merged;
        },
      }
    ),
    { name: 'agent-permission-mode-store' }
  )
);

/**
 * Whether a permission request should be auto-approved under the given mode.
 *
 * `fullAccess` approves every ASK request. `autoEdit` approves only requests
 * whose declared permission name is an edit/write permission. The raw wire data
 * is passed through because the processor event and the persisted HITL request
 * projection carry the permission name under different keys.
 */
export function shouldAutoApprovePermission(
  mode: AgentPermissionMode,
  data: {
    permission?: string | undefined;
    permission_type?: string | undefined;
    tool_name?: string | undefined;
    metadata?: Record<string, unknown> | undefined;
    native_binding?: unknown;
    decision?: unknown;
  }
): boolean {
  const metadata = data.metadata;
  const decision = data.decision ?? metadata?.decision;
  const target =
    decision && typeof decision === 'object' && 'target' in decision
      ? (decision as { target?: unknown }).target
      : undefined;
  const kind =
    target && typeof target === 'object' && 'kind' in target
      ? (target as { kind?: unknown }).kind
      : undefined;
  // Native application/device grants always require an explicit user action.
  if (
    data.permission === 'computer_use' ||
    data.permission_type === 'computer_use' ||
    Object.hasOwn(data, 'native_binding') ||
    (metadata && Object.hasOwn(metadata, 'native_binding')) ||
    kind === 'computer_app' ||
    kind === 'device_mcp_tool'
  )
    return false;
  if (mode === 'full_access') return true;
  if (mode !== 'auto_edit') return false;
  const permissionName = data.permission ?? data.permission_type;
  if (permissionName && EDIT_PERMISSION_NAMES.has(permissionName)) return true;
  return false;
}
