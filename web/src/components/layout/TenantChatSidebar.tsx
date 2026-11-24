import { useShallow } from 'zustand/react/shallow';
import { PluginSlotOutlet } from '@/components/plugins/PluginSlotOutlet';
import { useWebTopNavigationItemsV2 } from '@/routes/v2/webNavigationAuthorityStateV2';
import type { Conversation } from '@/types/agent';
import {
  TenantSidebarView,
  type TenantChatSidebarProps,
  type SidebarData,
} from './TenantSidebarView';
import { useConversationsStore } from '@business/agent/ui/web/stores/agent/conversationsStore';
import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';
import {
  useCurrentWorkspace,
  useWorkspaceActions,
  useWorkspaceTasks,
  useWorkspaces,
} from '@business/workspace/ui/web/stores/workspace';

export type { TenantChatSidebarProps } from './TenantSidebarView';
function useLegacySidebar(): SidebarData {
  const {
    activeConversationId,
    setActiveConversation,
    loadConversations,
    loadMoreConversations,
    createNewConversation,
    deleteConversation,
  } = useAgentV3Store(
    useShallow((state) => ({
      activeConversationId: state.activeConversationId,
      setActiveConversation: state.setActiveConversation,
      loadConversations: state.loadConversations,
      loadMoreConversations: state.loadMoreConversations,
      createNewConversation: state.createNewConversation,
      deleteConversation: state.deleteConversation,
    }))
  );
  const currentWorkspace = useCurrentWorkspace();
  const workspaceTasks = useWorkspaceTasks();
  const workspaces = useWorkspaces();
  const { loadWorkspaceSurface } = useWorkspaceActions();

  const {
    conversations,
    conversationsLoading,
    hasMoreConversations,
    reset: resetConversations,
    removeConversationLocal,
    restoreConversationLocal,
  } = useConversationsStore(
    useShallow((state) => ({
      conversations: state.conversations,
      conversationsLoading: state.conversationsLoading,
      hasMoreConversations: state.hasMoreConversations,
      reset: state.reset,
      removeConversationLocal: state.removeConversationLocal,
      restoreConversationLocal: state.restoreConversationLocal,
    }))
  );

  const renameConversation = useAgentV3Store((state) => state.renameConversation);
  return {
    activeConversationId,
    setActiveConversation,
    loadConversations,
    loadMoreConversations,
    createNewConversation,
    deleteConversation,
    currentWorkspace,
    workspaceTasks,
    workspaces,
    loadWorkspaceSurface,
    conversations,
    conversationsLoading,
    hasMoreConversations,
    resetConversations,
    removeConversationLocal,
    restoreConversationLocal: (row) => restoreConversationLocal(row as Conversation),
    renameConversation,
    canDelete: true,
    canCreate: true,
    canRename: true,
  };
}
export function TenantChatSidebar(props: TenantChatSidebarProps) {
  return (
    <TenantSidebarView
      {...props}
      useSidebarData={useLegacySidebar}
      useNavigationItems={useWebTopNavigationItemsV2}
      NavigationSlot={PluginSlotOutlet}
    />
  );
}
export default TenantChatSidebar;
