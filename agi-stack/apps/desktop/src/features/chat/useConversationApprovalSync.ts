import { useCallback, useEffect, useRef, useState } from 'react';
import type { AgentConversation, DesktopRuntimeConfig } from '../../types';
import type { DesktopConversationConfigOperationsV2 } from '../../plugins/desktopConversationConfigAuthorityModuleV2';
import { approvalMode, createConversationApprovalSync } from './conversationApprovalSyncModel';
import type { PermissionPreset } from './permissionPresetModel';

export function useConversationApprovalSync({
  config,
  conversation,
  scope,
  operations,
  onError,
}: {
  config: DesktopRuntimeConfig;
  conversation: AgentConversation | null;
  scope: string | null;
  operations: DesktopConversationConfigOperationsV2;
  onError: (error: unknown) => void;
}) {
  const [state, setState] = useState<{
    scope: string | null;
    preset: PermissionPreset;
    pending: boolean;
  }>({ scope: null, preset: 'default', pending: true });
  const controller = useRef<{
    scope: string;
    sync: ReturnType<typeof createConversationApprovalSync>;
  } | null>(null);
  const input = useRef({ config, conversation, onError });
  input.current = { config, conversation, onError };
  useEffect(() => {
    const { config, conversation } = input.current;
    if (!scope || !conversation) return;
    const sync = createConversationApprovalSync({
      read: () => operations.readApprovalMode({ config, conversation }),
      update: (preset) =>
        operations.updateApprovalMode({
          config,
          conversation,
          approvalMode: approvalMode(preset),
        }),
      publish: (next) =>
        setState((previous) =>
          previous.scope === scope &&
          previous.preset === next.preset &&
          previous.pending === next.pending
            ? previous
            : { scope, ...next },
        ),
      onError: (error) => input.current.onError(error),
    });
    controller.current = { scope, sync };
    setState({ scope, preset: 'default', pending: true });
    const refresh = () => {
      if (document.visibilityState !== 'hidden') void sync.refresh();
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      sync.dispose();
      controller.current = null;
      window.clearInterval(timer);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [scope, operations, conversation?.id]);
  const save = useCallback(
    (preset: PermissionPreset) => {
      if (controller.current?.scope === scope) return controller.current.sync.save(preset);
    },
    [scope],
  );
  return {
    preset: state.scope === scope ? state.preset : ('default' as PermissionPreset),
    pending: state.scope !== scope || state.pending,
    save,
  };
}
