import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';

import {
  useAgentPermissionModeStore,
  isAgentPermissionMode,
  type AgentPermissionMode,
} from '@/stores/agent/permissionModeStore';

import { agentService } from '@/services/agentService';

import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
} from '@/plugins/webOperationAdmissionV2';

/** Sync only the active conversation, independently of streaming token renders. */
export function useConversationApprovalMode(conversationId: string | null, projectId?: string) {
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );
  const isCurrentOwner = useCallback(
    () =>
      getWebOperationAvailabilityV2().owner === availability.owner &&
      getWebOperationAvailabilityV2().available,
    [availability.owner]
  );
  const identity = `${projectId ?? ''}:${conversationId ?? ''}`;
  const [loadedOwner, setLoadedOwner] = useState<object | null>(null);
  const [loadedIdentity, setLoadedIdentity] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const revision = useRef(0);
  const savingRef = useRef(false);
  const mode = useAgentPermissionModeStore(
    (state) => (conversationId ? state.modesByConversation[conversationId] : undefined) ?? 'ask'
  );

  useEffect(() => {
    let disposed = false;
    let reading = false;
    revision.current += 1;
    savingRef.current = false;
    setSaving(false);
    setFailed(false);
    if (!conversationId || !projectId) return;
    // Until this client has read canonical config, it cannot auto-approve requests.
    const store = useAgentPermissionModeStore.getState();
    store.setPermissionMode(conversationId, 'ask');
    if (!availability.available) return;
    const refresh = async () => {
      if (disposed || reading || savingRef.current || document.visibilityState === 'hidden') return;
      reading = true;
      const requestRevision = revision.current;
      try {
        const conversation = await agentService.getConversation(conversationId, projectId);
        if (disposed || requestRevision !== revision.current || !isCurrentOwner()) return;
        if (
          !conversation ||
          conversation.id !== conversationId ||
          conversation.project_id !== projectId
        ) {
          throw new Error('Unexpected conversation response');
        }
        setLoadedIdentity(identity);
        setLoadedOwner(availability.owner);
        setFailed(false);
        const value = conversation.agent_config?.approval_mode;
        store.setPermissionMode(conversationId, isAgentPermissionMode(value) ? value : 'ask');
      } catch {
        if (!disposed && requestRevision === revision.current && isCurrentOwner()) {
          store.setPermissionMode(conversationId, 'ask');
          setFailed(true);
        }
      } finally {
        reading = false;
      }
    };
    const onFocus = () => {
      void refresh();
    };
    void refresh();
    const interval = window.setInterval(onFocus, 5000);
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      disposed = true;
      revision.current += 1;
      window.clearInterval(interval);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [conversationId, projectId, identity, availability, isCurrentOwner]);

  const save = useCallback(
    async (next: AgentPermissionMode) => {
      if (!conversationId || !projectId || savingRef.current || !isCurrentOwner()) return;
      const requestRevision = ++revision.current;
      savingRef.current = true;
      setSaving(true);
      setFailed(false);
      try {
        const conversation = await agentService.updateConversationConfig(
          conversationId,
          projectId,
          {
            approval_mode: next,
          }
        );
        if (requestRevision !== revision.current || !isCurrentOwner()) return;
        const value = conversation.agent_config?.approval_mode;
        if (
          conversation.id !== conversationId ||
          conversation.project_id !== projectId ||
          value !== next
        ) {
          throw new Error('Approval mode was not acknowledged');
        }
        setLoadedIdentity(identity);
        setLoadedOwner(availability.owner);
        useAgentPermissionModeStore
          .getState()
          .setPermissionMode(conversationId, isAgentPermissionMode(value) ? value : 'ask');
      } catch {
        if (requestRevision === revision.current && isCurrentOwner()) setFailed(true);
      } finally {
        if (requestRevision === revision.current) {
          savingRef.current = false;
          setSaving(false);
        }
      }
    },
    [conversationId, projectId, identity, availability, isCurrentOwner]
  );

  return {
    mode:
      availability.available && loadedOwner === availability.owner && loadedIdentity === identity
        ? mode
        : ('ask' as AgentPermissionMode),
    saving,
    failed,
    save,
  };
}
