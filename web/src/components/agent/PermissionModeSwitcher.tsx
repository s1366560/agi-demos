import React, { useEffect, useRef } from 'react';

import { PermissionModeSwitcherView } from '@business/agent/ui/web/chat/PermissionModeSwitcherView';

import { useAgentHITLStore } from '@business/agent/ui/web/stores/agent/hitlStore';
import {
  shouldAutoApprovePermission,
  useAgentPermissionModeStore,
} from '@business/agent/ui/web/stores/agent/permissionModeStore';
import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';

import { useConversationApprovalMode } from '@business/agent/ui/web/hooks/useConversationApprovalMode';

export interface PermissionModeSwitcherProps {
  conversationId: string | null;
  projectId?: string | undefined;
  disabled?: boolean | undefined;
}

export const PermissionModeSwitcher: React.FC<PermissionModeSwitcherProps> = ({
  conversationId,
  projectId,
  disabled: disabledProp = false,
}) => {
  const { mode, saving, failed, save } = useConversationApprovalMode(conversationId, projectId);
  const disabled = disabledProp || saving || !conversationId || !projectId;
  const pending = useAgentHITLStore((state) => state.pendingPermission);
  const attempted = useRef(new Set<string>());
  useEffect(() => {
    if (!conversationId || !pending || !shouldAutoApprovePermission(mode, pending)) return;
    const agent = useAgentV3Store.getState();
    if (agent.activeConversationId !== conversationId) return;
    const key = `${conversationId}:${pending.request_id}`;
    if (attempted.current.has(key)) return;
    const permissions = useAgentPermissionModeStore.getState();
    if (!permissions.beginAutoApproval(conversationId, pending.request_id)) return;
    attempted.current.add(key);
    void agent
      .respondToPermission(pending.request_id, true, mode === 'ask' ? undefined : mode)
      .catch(() => {
        permissions.completeAutoApproval(conversationId, pending.request_id, false);
        // Keep the existing card answerable; never retry a failed grant in a render loop.
      });
  }, [conversationId, mode, pending]);

  return <PermissionModeSwitcherView mode={mode} failed={failed} disabled={disabled} save={save} />;
};
