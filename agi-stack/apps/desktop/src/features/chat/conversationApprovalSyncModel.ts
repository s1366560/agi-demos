import type { AgentConversation } from '../../types';
import type { DesktopConversationApprovalModeV2 } from '../../plugins/desktopConversationConfigAuthorityModuleV2';
import type { PermissionPreset } from './permissionPresetModel';

export function approvalPreset(conversation: AgentConversation): PermissionPreset {
  const mode = conversation.agent_config?.approval_mode;
  return mode === 'full_access' ? 'full' : mode === 'auto_edit' ? 'relaxed' : 'default';
}

export function approvalMode(preset: PermissionPreset): DesktopConversationApprovalModeV2 {
  return preset === 'full' ? 'full_access' : preset === 'relaxed' ? 'auto_edit' : 'ask';
}

/** One scope owns its requests. Writes invalidate every earlier read. */
export function createConversationApprovalSync({
  read,
  update,
  publish,
  onError,
}: {
  read: () => Promise<AgentConversation>;
  update: (preset: PermissionPreset) => Promise<AgentConversation>;
  publish: (state: { preset: PermissionPreset; pending: boolean }) => void;
  onError: (error: unknown) => void;
}) {
  let active = true;
  let revision = 0;
  let reading = false;
  let writing = false;
  let preset: PermissionPreset = 'default';
  let readErrorReported = false;
  const emit = (pending: boolean) => {
    if (active) publish({ preset, pending });
  };
  return {
    async refresh() {
      if (!active || reading || writing) return;
      reading = true;
      const requestRevision = revision;
      try {
        const result = await read();
        if (!active || requestRevision !== revision) return;
        preset = approvalPreset(result);
        readErrorReported = false;
        emit(false);
      } catch (error) {
        if (!active || requestRevision !== revision) return;
        preset = 'default';
        emit(false);
        if (!readErrorReported) onError(error);
        readErrorReported = true;
      } finally {
        reading = false;
      }
    },
    async save(next: PermissionPreset) {
      if (!active || writing) return;
      const requestRevision = ++revision;
      writing = true;
      // Revoke automatic approval while the canonical mutation is unresolved.
      preset = 'default';
      emit(true);
      try {
        const result = await update(next);
        if (!active || requestRevision !== revision) return;
        preset = approvalPreset(result);
      } catch (error) {
        if (active && requestRevision === revision) onError(error);
      } finally {
        writing = false;
        if (active && requestRevision === revision) emit(false);
      }
    },
    dispose() {
      active = false;
      revision++;
    },
  };
}
