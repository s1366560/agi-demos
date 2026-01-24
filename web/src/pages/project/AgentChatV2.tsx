/**
 * Agent Chat V2 Page
 *
 * Main page for the Agent Chat interface.
 * Completely rewritten based on backend API analysis.
 */

import { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { ChatLayout } from "../../components/agentV2/layout/ChatLayout";
import { ConversationSidebar } from "../../components/agentV2/layout/ConversationSidebar";
import { HeaderBar } from "../../components/agentV2/layout/HeaderBar";
import { MessageList } from "../../components/agentV2/chat/MessageList";
import { MessageInput } from "../../components/agentV2/chat/MessageInput";
import { ExecutionSummary } from "../../components/agentV2/execution/ExecutionSummary";
import { HumanInteractions } from "../../components/agentV2/interactions/HumanInteractions";
import { CostSummary } from "../../components/agentV2/cost/CostSummary";
import { ThinkingBubble } from "../../components/agentV2/chat/ThinkingBubble";
import { useAgentV2Store } from "../../stores/agentV2";

export function AgentChatV2() {
  const { projectId } = useParams<{ projectId: string }>();
  const scrollRef = useRef<HTMLDivElement>(null);
  const {
    sidebarOpen: _sidebarOpen,
    toggleSidebar,
    listConversations,
    createConversation,
    currentConversation,
  } = useAgentV2Store();

  // Load conversations on mount
  useEffect(() => {
    if (projectId) {
      listConversations(projectId);
    }
  }, [projectId, listConversations]);

  // Create conversation if none exists
  useEffect(() => {
    if (projectId && !currentConversation) {
      createConversation(projectId, "New Conversation");
    }
  }, [projectId, currentConversation, createConversation]);

  return (
    <ChatLayout sidebar={<ConversationSidebar />}>
      {/* Header */}
      <HeaderBar onToggleSidebar={toggleSidebar} />

      {/* Messages Area */}
      <MessageList scrollRef={scrollRef} />

      {/* Execution Summary - displayed between messages and input */}
      <div className="max-w-4xl mx-auto px-4">
        <ExecutionSummary />
        <ThinkingBubble thoughts={[]} />
      </div>

      {/* Input Area */}
      <MessageInput />

      {/* Cost Summary - floating at bottom right */}
      <div className="fixed bottom-20 right-4">
        <CostSummary variant="detailed" />
      </div>

      {/* Human Interaction Dialogs */}
      <HumanInteractions />
    </ChatLayout>
  );
}

export default AgentChatV2;
