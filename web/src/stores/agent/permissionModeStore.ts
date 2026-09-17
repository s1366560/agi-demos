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

export type AgentPermissionMode = 'ask' | 'auto_edit' | 'full_access';

export const PERMISSION_MODES: readonly AgentPermissionMode[] = [
  'ask',
  'auto_edit',
  'full_access',
] as const;

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
  setPermissionMode: (conversationId: string, mode: AgentPermissionMode) => void;
  clearConversation: (conversationId: string) => void;
  getPermissionMode: (conversationId: string) => AgentPermissionMode;
}

export const useAgentPermissionModeStore = create<PermissionModeState>()(
  devtools(
    persist(
      (set, get) => ({
        modesByConversation: {},

        setPermissionMode: (conversationId, mode) =>
          set(
            (state) => ({
              modesByConversation: { ...state.modesByConversation, [conversationId]: mode },
            }),
            false,
            'permissionMode/set'
          ),

        clearConversation: (conversationId) =>
          set((state) => {
            if (!(conversationId in state.modesByConversation)) return state;
            const { [conversationId]: _removed, ...rest } = state.modesByConversation;
            return { modesByConversation: rest };
          }),

        getPermissionMode: (conversationId) =>
          get().modesByConversation[conversationId] ?? 'ask',
      }),
      {
        name: 'agent-permission-mode',
        merge: (persisted, current) => {
          const merged = { ...current };
          if (persisted && typeof persisted === 'object') {
            const stored = persisted as { modesByConversation?: unknown };
            if (stored.modesByConversation && typeof stored.modesByConversation === 'object') {
              const sanitized: Record<string, AgentPermissionMode> = {};
              for (const [conversationId, mode] of Object.entries(
                stored.modesByConversation as Record<string, unknown>
              )) {
                if (isAgentPermissionMode(mode)) {
                  sanitized[conversationId] = mode;
                }
              }
              merged.modesByConversation = sanitized;
            }
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
  }
): boolean {
  if (mode === 'full_access') return true;
  if (mode !== 'auto_edit') return false;
  const permissionName = data.permission ?? data.permission_type;
  if (permissionName && EDIT_PERMISSION_NAMES.has(permissionName)) return true;
  return false;
}
