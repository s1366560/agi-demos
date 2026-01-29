import React, { useEffect, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Spin, Modal, notification } from "antd";
import { useAgentV3Store } from "../../stores/agentV3";
import { usePlanModeStore } from "../../stores/agent/planModeStore";
import { useSandboxStore } from "../../stores/sandbox";
import { useSandboxAgentHandlers } from "../../hooks/useSandboxDetection";
import {
  ChatLayout,
  VirtualTimelineEventList,
  InputArea,
  ConversationSidebar,
  RightPanel,
  PlanModeIndicator,
} from "../../components/agent";
import { sandboxService } from "../../services/sandboxService";

export const AgentChat: React.FC = () => {
  const { projectId, conversation: conversationId } = useParams<{
    projectId: string;
    conversation?: string;
  }>();
  const navigate = useNavigate();

  // Agent V3 store state
  const {
    conversations,
    activeConversationId,
    timeline,
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

  // Plan Mode store state
  const { planModeStatus, exitPlanMode } = usePlanModeStore();

  // Sandbox state and handlers
  const { activeSandboxId, toolExecutions, setSandboxId } = useSandboxStore();
  const { onAct, onObserve } = useSandboxAgentHandlers(activeSandboxId);

  /**
   * Ensure a sandbox exists for the current project.
   */
  const ensureSandbox = useCallback(async () => {
    if (activeSandboxId) {
      return activeSandboxId;
    }

    if (!projectId) {
      console.warn("[AgentChat] Cannot ensure sandbox: no projectId");
      return null;
    }

    try {
      const { sandboxes } = await sandboxService.listSandboxes(projectId);

      if (sandboxes.length > 0 && sandboxes[0].status === "running") {
        setSandboxId(sandboxes[0].id);
        return sandboxes[0].id;
      }

      const { sandbox } = await sandboxService.createSandbox({ project_id: projectId });
      setSandboxId(sandbox.id);
      return sandbox.id;
    } catch (error) {
      console.error("[AgentChat] Failed to ensure sandbox:", error);
      return null;
    }
  }, [activeSandboxId, projectId, setSandboxId]);

  // Load conversations on mount or project change
  useEffect(() => {
    if (projectId) {
      loadConversations(projectId);
    }
  }, [projectId, loadConversations]);

  // Handle URL conversation ID
  useEffect(() => {
    if (projectId && conversationId) {
      setActiveConversation(conversationId);
      loadMessages(conversationId, projectId);
    } else if (projectId && !conversationId) {
      setActiveConversation(null);
    }
  }, [conversationId, projectId, setActiveConversation, loadMessages]);

  // Handle error notifications
  useEffect(() => {
    if (error) {
      notification.error({
        message: "Agent Error",
        description: error,
        onClose: clearError,
      });
    }
  }, [error, clearError]);

  // Handle Pending Decision
  useEffect(() => {
    if (pendingDecision) {
      Modal.confirm({
        title: "Agent Requests Decision",
        content: pendingDecision.question,
        okText: "Confirm",
        cancelText: "Cancel",
        onOk: () => respondToDecision(pendingDecision.request_id, "approved"),
        onCancel: () =>
          respondToDecision(pendingDecision.request_id, "rejected"),
      });
    }
  }, [pendingDecision, respondToDecision]);

  // Handle Doom Loop
  useEffect(() => {
    if (doomLoopDetected) {
      notification.warning({
        message: "Doom Loop Detected",
        description: `Tool ${doomLoopDetected.tool_name} called ${doomLoopDetected.call_count} times repeatedly. Intervention required.`,
      });
    }
  }, [doomLoopDetected]);

  const handleSelectConversation = useCallback((id: string) => {
    navigate(`/project/${projectId}/agent/${id}`);
  }, [navigate, projectId]);

  const handleNewConversation = useCallback(async () => {
    if (!projectId) return;

    const newConversationId = await createNewConversation(projectId);
    if (newConversationId) {
      navigate(`/project/${projectId}/agent/${newConversationId}`);
    }
  }, [projectId, createNewConversation, navigate]);

  const handleDeleteConversation = useCallback(async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!projectId) return;

    Modal.confirm({
      title: "Delete Conversation",
      content: "Are you sure you want to delete this conversation? This action cannot be undone.",
      okText: "Delete",
      okType: "danger",
      cancelText: "Cancel",
      onOk: async () => {
        await deleteConversation(id, projectId);
        if (activeConversationId === id) {
          navigate(`/project/${projectId}/agent`);
        }
      },
    });
  }, [projectId, activeConversationId, deleteConversation, navigate]);

  const handleSend = useCallback(async (content: string) => {
    if (!projectId) return;

    await ensureSandbox();

    const newConversationId = await sendMessage(content, projectId, {
      onAct,
      onObserve,
    });

    if (!conversationId && newConversationId) {
      navigate(`/project/${projectId}/agent/${newConversationId}`);
    }
  }, [projectId, conversationId, sendMessage, onAct, onObserve, navigate, ensureSandbox]);

  // Memoize panel components
  const sidebar = useMemo(() => (
    <ConversationSidebar
      conversations={conversations}
      activeId={activeConversationId}
      onSelect={handleSelectConversation}
      onNew={handleNewConversation}
      onDelete={handleDeleteConversation}
    />
  ), [conversations, activeConversationId, handleSelectConversation, handleNewConversation, handleDeleteConversation]);

  // Handle View Plan callback
  const handleViewPlan = useCallback(() => {
    if (!showPlanPanel) {
      togglePlanPanel();
    }
  }, [showPlanPanel, togglePlanPanel]);

  // Handle Exit Plan Mode callback
  const handleExitPlanMode = useCallback(async () => {
    if (!activeConversationId || !planModeStatus?.current_plan_id) return;

    try {
      await exitPlanMode(
        activeConversationId,
        planModeStatus.current_plan_id,
        false
      );
      togglePlanMode();
    } catch (error) {
      console.error("[AgentChat] Failed to exit plan mode:", error);
      notification.error({
        message: "Failed to exit Plan Mode",
        description: "Please try again.",
      });
    }
  }, [activeConversationId, planModeStatus, exitPlanMode, togglePlanMode]);

  const chatArea = useMemo(() => (
    <div className="flex flex-col h-full relative">
      {/* Loading Overlay */}
      {isLoadingHistory && (
        <div className="absolute inset-0 bg-white/60 backdrop-blur-sm z-20 flex items-center justify-center">
          <Spin size="large" tip="Loading conversation..." />
        </div>
      )}

      {/* Plan Mode Indicator */}
      {(planModeStatus?.is_in_plan_mode || planModeStatus?.current_mode === "explore") && (
        <div className="flex-shrink-0">
          <PlanModeIndicator
            status={planModeStatus}
            onViewPlan={handleViewPlan}
            onExitPlanMode={handleExitPlanMode}
          />
        </div>
      )}

      {/* Timeline Event List */}
      <VirtualTimelineEventList
        timeline={timeline}
        isStreaming={isStreaming}
      />

      {/* Input Area */}
      <InputArea
        onSend={handleSend}
        onAbort={abortStream}
        isStreaming={isStreaming}
        isPlanMode={isPlanMode}
        onTogglePlanMode={togglePlanMode}
        showPlanPanel={showPlanPanel}
        onTogglePlanPanel={togglePlanPanel}
      />
    </div>
  ), [
    isLoadingHistory,
    timeline,
    isStreaming,
    handleSend,
    abortStream,
    isPlanMode,
    togglePlanMode,
    showPlanPanel,
    togglePlanPanel,
    planModeStatus,
    handleViewPlan,
    handleExitPlanMode,
  ]);

  const rightPanel = useMemo(() => (
    <RightPanel
      workPlan={workPlan}
      executionPlan={executionPlan}
      sandboxId={activeSandboxId}
      toolExecutions={toolExecutions}
      onClose={() => togglePlanPanel()}
    />
  ), [workPlan, executionPlan, activeSandboxId, toolExecutions, togglePlanPanel]);

  return (
    <ChatLayout sidebar={sidebar} chatArea={chatArea} rightPanel={rightPanel} />
  );
};

export default AgentChat;
