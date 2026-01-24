import React, { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Spin, Modal, notification } from "antd";
import { useAgentV3Store } from "../../stores/agentV3";
import { useSandboxStore } from "../../stores/sandbox";
import { useSandboxAgentHandlers } from "../../hooks/useSandboxDetection";
import { ChatLayout } from "../../components/agentV3/ChatLayout";
import { MessageList } from "../../components/agentV3/MessageList";
import { InputArea } from "../../components/agentV3/InputArea";
import { ConversationSidebar } from "../../components/agentV3/ConversationSidebar";
import { RightPanel } from "../../components/agentV3/RightPanel";

export const AgentChatV3: React.FC = () => {
  const { projectId, conversation: conversationId } = useParams<{
    projectId: string;
    conversation?: string;
  }>();
  const navigate = useNavigate();

  const {
    conversations,
    activeConversationId,
    messages,
    isLoadingHistory,
    isStreaming,
    // streamStatus, // Available but not currently used
    currentThought,
    activeToolCalls,
    agentState,
    workPlan,
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

  // Load conversations on mount or project change
  useEffect(() => {
    if (projectId) {
      loadConversations(projectId);
    }
  }, [projectId, loadConversations]);

  // Handle URL conversation ID
  useEffect(() => {
    if (projectId && conversationId) {
      // 始终设置活动对话并加载消息（当 URL 中有对话 ID 时）
      setActiveConversation(conversationId);
      loadMessages(conversationId, projectId);
    } else if (projectId && !conversationId) {
      // 清除活动对话（当 URL 中没有对话 ID 时）
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
        cancelText: "Cancel", // Or custom options if available
        onOk: () => respondToDecision(pendingDecision.request_id, "approved"), // Simplified
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

  const handleSelectConversation = (id: string) => {
    navigate(`/project/${projectId}/agent/${id}`);
  };

  const handleNewConversation = async () => {
    if (!projectId) return;

    // Create conversation first, then navigate to it
    const newConversationId = await createNewConversation(projectId);
    if (newConversationId) {
      navigate(`/project/${projectId}/agent/${newConversationId}`);
    }
  };

  const handleDeleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!projectId) return;

    Modal.confirm({
      title: "Delete Conversation",
      content:
        "Are you sure you want to delete this conversation? This action cannot be undone.",
      okText: "Delete",
      okType: "danger",
      cancelText: "Cancel",
      onOk: async () => {
        await deleteConversation(id, projectId);
        // If deleted conversation was active, navigate to root agent page
        if (activeConversationId === id) {
          navigate(`/project/${projectId}/agent`);
        }
      },
    });
  };

  const handleSend = async (content: string) => {
    if (!projectId) return;

    const newConversationId = await sendMessage(content, projectId, {
      onAct,
      onObserve,
    });

    // If we were on the "New Chat" page (no active ID) and got a new ID, navigate
    if (!conversationId && newConversationId) {
      navigate(`/project/${projectId}/agent/${newConversationId}`);
    }
  };

  // Sandbox state and handlers
  const { activeSandboxId, toolExecutions, closePanel: _closeSandboxPanel } = useSandboxStore();
  const { onAct, onObserve } = useSandboxAgentHandlers(activeSandboxId);

  const sidebar = (
    <ConversationSidebar
      conversations={conversations}
      activeId={activeConversationId}
      onSelect={handleSelectConversation}
      onNew={handleNewConversation}
      onDelete={handleDeleteConversation}
    />
  );

  const chatArea = (
    <div className="flex flex-col h-full relative">
      {/* Loading Overlay */}
      {isLoadingHistory && (
        <div className="absolute inset-0 bg-white/50 z-20 flex items-center justify-center">
          <Spin size="large" />
        </div>
      )}

      {/* Message List */}
      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        currentThought={currentThought}
        activeToolCalls={activeToolCalls}
        agentState={agentState}
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
  );

  const rightPanel = (
    <RightPanel
      workPlan={workPlan}
      sandboxId={activeSandboxId}
      toolExecutions={toolExecutions}
      onClose={() => togglePlanPanel()}
    />
  );

  return (
    <ChatLayout sidebar={sidebar} chatArea={chatArea} rightPanel={rightPanel} />
  );
};

export default AgentChatV3;
