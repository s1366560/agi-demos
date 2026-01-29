/**
 * AgentChat - Agent Chat Page
 * 
 * Main Agent Chat interface with modern design.
 */

import React, { useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Modal, notification } from 'antd';
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
} from '../../components/agent';
import { EmptyState } from '../../components/agent/EmptyState';

const AgentChat: React.FC = () => {
  const { projectId, conversation: conversationId } = useParams<{
    projectId: string;
    conversation?: string;
  }>();
  const navigate = useNavigate();

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
    doomLoopDetected,
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

  // Handle errors
  useEffect(() => {
    if (error) {
      notification.error({ message: 'Agent Error', description: error, onClose: clearError });
    }
  }, [error, clearError]);

  // Handle pending decisions
  useEffect(() => {
    if (pendingDecision) {
      Modal.confirm({
        title: 'Agent Requests Decision',
        content: pendingDecision.question,
        okText: 'Confirm',
        cancelText: 'Cancel',
        onOk: () => respondToDecision(pendingDecision.request_id, 'approved'),
        onCancel: () => respondToDecision(pendingDecision.request_id, 'rejected'),
      });
    }
  }, [pendingDecision, respondToDecision]);

  // Handle doom loop
  useEffect(() => {
    if (doomLoopDetected) {
      notification.warning({
        message: 'Doom Loop Detected',
        description: `Tool ${doomLoopDetected.tool_name} called ${doomLoopDetected.call_count} times repeatedly.`,
      });
    }
  }, [doomLoopDetected]);

  // Handlers
  const handleSelectConversation = useCallback((id: string) => {
    navigate(`/project/${projectId}/agent/${id}`);
  }, [navigate, projectId]);

  const handleNewConversation = useCallback(async () => {
    if (!projectId) return;
    const newId = await createNewConversation(projectId);
    if (newId) navigate(`/project/${projectId}/agent/${newId}`);
  }, [projectId, createNewConversation, navigate]);

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
        if (activeConversationId === id) navigate(`/project/${projectId}/agent-new`);
      },
    });
  }, [projectId, activeConversationId, deleteConversation, navigate]);

  const handleSend = useCallback(async (content: string) => {
    if (!projectId) return;
    await ensureSandbox();
    const newId = await sendMessage(content, projectId, { onAct, onObserve });
    if (!conversationId && newId) navigate(`/project/${projectId}/agent-new/${newId}`);
  }, [projectId, conversationId, sendMessage, onAct, onObserve, navigate, ensureSandbox]);

  const handleViewPlan = useCallback(() => {
    setPanelCollapsed(false);
    togglePlanPanel();
  }, [togglePlanPanel]);

  const handleExitPlanMode = useCallback(async () => {
    if (!activeConversationId || !planModeStatus?.current_plan_id) return;
    try {
      await exitPlanMode(activeConversationId, planModeStatus.current_plan_id, false);
      togglePlanMode();
    } catch (error) {
      notification.error({ message: 'Failed to exit Plan Mode', description: 'Please try again.' });
    }
  }, [activeConversationId, planModeStatus, exitPlanMode, togglePlanMode]);

  // Memoized components
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

export default AgentChat;
