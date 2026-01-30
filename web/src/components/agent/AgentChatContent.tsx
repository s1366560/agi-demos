/**
 * AgentChatContent - Reusable Agent Chat Component
 * 
 * This component can be used in both project-level and tenant-level contexts.
 * It receives projectId as a prop instead of extracting it from URL params.
 */

import React, { useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Modal } from 'antd';
import { useAgentV3Store } from '../../stores/agentV3';
import { usePlanModeStore } from '../../stores/agent/planModeStore';
import { useSandboxStore } from '../../stores/sandbox';
import { useSandboxAgentHandlers } from '../../hooks/useSandboxDetection';
import { sandboxService } from '../../services/sandboxService';

// Import design components
import {
  ChatLayout,
  ConversationSidebar,
  MessageArea,
  InputBar,
  RightPanel,
  StatusBar,
} from './index';
import { EmptyState } from './EmptyState';

interface AgentChatContentProps {
  projectId: string;
  basePath?: string; // For navigation, defaults to current location
}

export const AgentChatContent: React.FC<AgentChatContentProps> = ({ 
  projectId,
  basePath: customBasePath 
}) => {
  const { conversation: conversationId } = useParams<{
    conversation?: string;
  }>();
  const navigate = useNavigate();
  const location = window.location;
  
  // Determine base path for navigation
  const basePath = customBasePath || location.pathname.split('/conversation/')[0];

  // Store state
  const {
    conversations,
    activeConversationId,
    timeline,
    messages,
    isLoadingHistory,
    isStreaming,
    workPlan,
    executionPlan,
    isPlanMode,
    showPlanPanel,
    pendingDecision,
    loadConversations,
    loadMessages,
    setActiveConversation,
    createNewConversation,
    sendMessage,
    deleteConversation,
    abortStream,
    togglePlanMode,
    togglePlanPanel,
    respondToDecision,
    clearError,
    error,
  } = useAgentV3Store();

  // Get streaming content from the last assistant message
  const streamingContent = React.useMemo(() => {
    if (!isStreaming || messages.length === 0) return '';
    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.role === 'assistant') {
      return lastMessage.content || '';
    }
    return '';
  }, [messages, isStreaming]);

  // Get streaming thought from store
  const { streamingThought, isThinkingStreaming } = useAgentV3Store();

  const { planModeStatus, exitPlanMode } = usePlanModeStore();
  const { 
    activeSandboxId, 
    toolExecutions, 
    currentTool,
    setSandboxId 
  } = useSandboxStore();
  const { onAct, onObserve } = useSandboxAgentHandlers(activeSandboxId);

  // Local UI state
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false);
  const [panelCollapsed, setPanelCollapsed] = React.useState(!showPlanPanel);

  // Ensure sandbox exists
  const ensureSandbox = useCallback(async () => {
    if (activeSandboxId) return activeSandboxId;
    if (!projectId) return null;

    try {
      const { sandboxes } = await sandboxService.listSandboxes(projectId);
      if (sandboxes.length > 0 && sandboxes[0].status === 'running') {
        setSandboxId(sandboxes[0].id);
        return sandboxes[0].id;
      }
      const { sandbox } = await sandboxService.createSandbox({ project_id: projectId });
      setSandboxId(sandbox.id);
      return sandbox.id;
    } catch (error) {
      console.error('[AgentChat] Failed to ensure sandbox:', error);
      return null;
    }
  }, [activeSandboxId, projectId, setSandboxId]);

  // Load conversations
  useEffect(() => {
    if (projectId) loadConversations(projectId);
  }, [projectId, loadConversations]);

  // Handle URL changes
  useEffect(() => {
    if (projectId && conversationId) {
      setActiveConversation(conversationId);
      loadMessages(conversationId, projectId);
    } else if (projectId && !conversationId) {
      setActiveConversation(null);
    }
  }, [conversationId, projectId, setActiveConversation, loadMessages]);

  // Error handling
  useEffect(() => {
    if (error) {
      console.error('Agent Chat Error:', error);
      clearError();
    }
  }, [error, clearError]);

  // Decision handling
  useEffect(() => {
    if (pendingDecision) {
      Modal.confirm({
        title: pendingDecision.title,
        content: pendingDecision.message,
        onOk: () => respondToDecision(pendingDecision.request_id, 'confirmed'),
        onCancel: () => respondToDecision(pendingDecision.request_id, 'cancelled'),
      });
    }
  }, [pendingDecision, respondToDecision]);

  // Event handlers
  const handleSelectConversation = useCallback((id: string) => {
    navigate(`${basePath}/${id}`);
  }, [navigate, basePath]);

  const handleNewConversation = useCallback(async () => {
    if (!projectId) return;
    const newId = await createNewConversation(projectId);
    if (newId) navigate(`${basePath}/${newId}`);
  }, [projectId, createNewConversation, navigate, basePath]);

  const handleDeleteConversation = useCallback(async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!projectId) return;
    Modal.confirm({
      title: 'Delete Conversation',
      content: 'Are you sure? This action cannot be undone.',
      okText: 'Delete',
      okType: 'danger',
      onOk: async () => {
        await deleteConversation(id, projectId);
        if (activeConversationId === id) navigate(basePath);
      },
    });
  }, [projectId, activeConversationId, deleteConversation, navigate, basePath]);

  const handleSend = useCallback(async (content: string) => {
    if (!projectId) return;
    await ensureSandbox();
    const newId = await sendMessage(content, projectId, { onAct, onObserve });
    if (!conversationId && newId) navigate(`${basePath}/${newId}`);
  }, [projectId, conversationId, sendMessage, onAct, onObserve, navigate, ensureSandbox, basePath]);

  const handleViewPlan = useCallback(() => {
    if (!panelCollapsed) {
      setPanelCollapsed(true);
    }
    togglePlanPanel();
  }, [panelCollapsed, togglePlanPanel]);

  const handleExitPlanMode = useCallback(async () => {
    if (activeConversationId && planModeStatus?.current_plan_id) {
      await exitPlanMode(activeConversationId, planModeStatus.current_plan_id, true);
    }
  }, [exitPlanMode, activeConversationId, planModeStatus]);

  // Render components
  const sidebar = useMemo(() => (
    <ConversationSidebar
      conversations={conversations}
      activeId={activeConversationId}
      onSelect={handleSelectConversation}
      onNew={handleNewConversation}
      onDelete={handleDeleteConversation}
      collapsed={sidebarCollapsed}
      onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
    />
  ), [conversations, activeConversationId, sidebarCollapsed, handleSelectConversation, handleNewConversation, handleDeleteConversation]);

  const messageArea = useMemo(() => (
    timeline.length === 0 && !activeConversationId ? (
      <EmptyState onNewConversation={handleNewConversation} />
    ) : (
      <MessageArea
        timeline={timeline}
        streamingContent={streamingContent}
        streamingThought={streamingThought}
        isStreaming={isStreaming}
        isThinkingStreaming={isThinkingStreaming}
        isLoading={isLoadingHistory}
        planModeStatus={planModeStatus}
        onViewPlan={handleViewPlan}
        onExitPlanMode={handleExitPlanMode}
      />
    )
  ), [timeline, streamingContent, streamingThought, isStreaming, isThinkingStreaming, isLoadingHistory, activeConversationId, planModeStatus, handleViewPlan, handleExitPlanMode, handleNewConversation]);

  const inputBar = useMemo(() => (
    <InputBar
      onSend={handleSend}
      onAbort={abortStream}
      isStreaming={isStreaming}
      isPlanMode={isPlanMode}
      onTogglePlanMode={togglePlanMode}
      disabled={isLoadingHistory}
    />
  ), [handleSend, abortStream, isStreaming, isPlanMode, togglePlanMode, isLoadingHistory]);

  const rightPanel = useMemo(() => (
    <RightPanel
      workPlan={workPlan}
      executionPlan={executionPlan}
      sandboxId={activeSandboxId}
      toolExecutions={toolExecutions}
      currentTool={currentTool}
      onClose={() => {
        setPanelCollapsed(true);
        togglePlanPanel();
      }}
      collapsed={panelCollapsed}
    />
  ), [workPlan, executionPlan, activeSandboxId, toolExecutions, currentTool, panelCollapsed, togglePlanPanel]);

  const statusBar = useMemo(() => (
    <StatusBar
      isStreaming={isStreaming}
      isPlanMode={isPlanMode}
      messageCount={timeline.length}
      sandboxConnected={!!activeSandboxId}
    />
  ), [isStreaming, isPlanMode, timeline.length, activeSandboxId]);

  return (
    <ChatLayout
      sidebar={sidebar}
      messageArea={messageArea}
      inputBar={inputBar}
      rightPanel={rightPanel}
      statusBar={statusBar}
      sidebarCollapsed={sidebarCollapsed}
      panelCollapsed={panelCollapsed}
      onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
      onTogglePanel={() => {
        setPanelCollapsed(!panelCollapsed);
        togglePlanPanel();
      }}
    />
  );
};

export default AgentChatContent;
