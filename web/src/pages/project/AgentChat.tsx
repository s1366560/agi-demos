/**
 * AgentChat page component
 *
 * Page for interacting with the React-mode Agent.
 * Refactored to use modular components and custom hooks.
 */

import React, { memo, useMemo } from "react";
import { Modal, Input, Form } from "antd";
import { useAgentChat } from "../../hooks/useAgentChat";
import { ChatArea } from "../../components/agent/chat/ChatArea";
import { FloatingInputBar } from "../../components/agent/chat/FloatingInputBar";
import {
  ChatHistorySidebar,
  type Conversation as SidebarConversation,
} from "../../components/agent/layout/ChatHistorySidebar";

const AgentChatInternal: React.FC = () => {
  const {
    projectId,
    currentConversation,
    conversations,
    messages,
    messagesLoading,
    isStreaming,
    inputValue,
    setInputValue,
    historySidebarOpen,
    setHistorySidebarOpen,
    searchQuery,
    setSearchQuery,
    showPlanEditor,
    showEnterPlanModal,
    setShowEnterPlanModal,
    planForm,

    currentWorkPlan,
    currentStepNumber,
    currentThought,
    currentToolCall,
    executionTimeline,
    toolExecutionHistory,
    matchedPattern,
    currentPlan,
    planModeStatus,
    planLoading,
    // Typewriter streaming state
    assistantDraftContent,
    isTextStreaming,

    messagesEndRef,
    scrollContainerRef,

    handleSend,
    handleStop,
    handleTileClick,
    handleSelectConversation,
    handleNewChat,
    handleViewPlan,
    handleExitPlanMode,
    handleUpdatePlan,
    handleEnterPlanMode,
    handleEnterPlanSubmit,
  } = useAgentChat();

  // Transform conversations for sidebar
  const sidebarConversations: SidebarConversation[] = useMemo(
    () =>
      conversations.map((conv) => ({
        id: conv.id,
        title: conv.title || "New Conversation",
        status:
          conv.id === currentConversation?.id && isStreaming
            ? "running"
            : conv.status === "deleted"
            ? "failed"
            : "done",
        messageCount: conv.message_count,
        timestamp: conv.updated_at
          ? new Date(conv.updated_at).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
            })
          : undefined,
      })),
    [conversations, currentConversation?.id, isStreaming]
  );

  if (!projectId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white mb-2">
            Invalid Project
          </h2>
          <p className="text-slate-500">
            Please select a valid project to access the agent.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full relative">
      {/* Conversation History Sidebar */}
      {historySidebarOpen && (
        <ChatHistorySidebar
          conversations={sidebarConversations}
          selectedConversationId={currentConversation?.id}
          onSelectConversation={handleSelectConversation}
          onNewChat={handleNewChat}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col overflow-hidden relative">
        {/* History Toggle Button */}
        {!historySidebarOpen && (
          <button
            onClick={() => setHistorySidebarOpen(true)}
            className="absolute left-0 top-1/2 -translate-y-1/2 w-8 h-16 bg-white dark:bg-surface-dark border border-r-0 rounded-r-lg shadow-lg flex items-center justify-center hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors z-10 animate-fade-in-left"
            title="Show chat history"
          >
            <span className="material-symbols-outlined text-slate-500">
              chevron_right
            </span>
          </button>
        )}

        {/* Hide History Button (when sidebar is open) */}
        {historySidebarOpen && (
          <button
            onClick={() => setHistorySidebarOpen(false)}
            className="absolute left-0 top-4 w-6 h-6 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-r-lg flex items-center justify-center shadow-sm hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors z-10"
            title="Hide chat history"
          >
            <span className="material-symbols-outlined text-slate-500 text-sm">
              chevron_left
            </span>
          </button>
        )}

        <ChatArea
          messages={messages}
          currentConversation={currentConversation}
          isStreaming={isStreaming}
          messagesLoading={messagesLoading}
          currentWorkPlan={currentWorkPlan}
          currentStepNumber={currentStepNumber}
          currentThought={currentThought}
          currentToolCall={currentToolCall}
          executionTimeline={executionTimeline}
          toolExecutionHistory={toolExecutionHistory}
          matchedPattern={matchedPattern}
          planModeStatus={planModeStatus}
          showPlanEditor={showPlanEditor}
          currentPlan={currentPlan}
          planLoading={planLoading}
          scrollContainerRef={scrollContainerRef}
          messagesEndRef={messagesEndRef}
          onViewPlan={handleViewPlan}
          onExitPlanMode={handleExitPlanMode}
          onUpdatePlan={handleUpdatePlan}
          onSend={handleSend}
          onTileClick={handleTileClick}
          assistantDraftContent={assistantDraftContent}
          isTextStreaming={isTextStreaming}
        />

        {/* Input Area */}
        <div className="flex-shrink-0 border-t border-slate-200 dark:border-border-dark bg-white dark:bg-surface-dark">
          <div className="max-w-4xl mx-auto px-6 py-4">
            <FloatingInputBar
              value={inputValue}
              onChange={setInputValue}
              onSend={handleSend}
              onStop={handleStop}
              disabled={isStreaming}
              placeholder={
                isStreaming
                  ? "Agent is thinking..."
                  : "Message the Agent or type '/' for commands..."
              }
              showFooter={true}
              onPlanMode={currentConversation ? handleEnterPlanMode : undefined}
              isInPlanMode={planModeStatus?.is_in_plan_mode ?? false}
              planModeDisabled={planLoading}
            />
          </div>
        </div>
      </div>

      {/* Enter Plan Mode Modal */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-purple-600">
              architecture
            </span>
            <span>Enter Plan Mode</span>
          </div>
        }
        open={showEnterPlanModal}
        onOk={handleEnterPlanSubmit}
        onCancel={() => {
          setShowEnterPlanModal(false);
          planForm.resetFields();
        }}
        okText="Enter Plan Mode"
        okButtonProps={{ loading: planLoading }}
        cancelText="Cancel"
        destroyOnHidden
      >
        <div className="py-4">
          <p className="text-slate-600 dark:text-slate-400 mb-4">
            Plan Mode allows you to create and refine implementation plans
            before execution. The Agent will focus on planning without making
            actual changes.
          </p>
          <Form form={planForm} layout="vertical">
            <Form.Item
              name="title"
              label="Plan Title"
              rules={[{ required: true, message: "Please enter a plan title" }]}
            >
              <Input
                placeholder="e.g., Implement user authentication"
                maxLength={200}
              />
            </Form.Item>
            <Form.Item name="description" label="Description (Optional)">
              <Input.TextArea
                placeholder="Describe what you want to plan..."
                rows={3}
                maxLength={1000}
              />
            </Form.Item>
          </Form>
        </div>
      </Modal>
    </div>
  );
};

export const AgentChat = memo(AgentChatInternal);
export default AgentChat;
