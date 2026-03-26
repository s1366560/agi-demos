import React, { useEffect, useRef } from 'react';

import { Spin, Empty } from 'antd';
import { useShallow } from 'zustand/react/shallow';

import { useAuthStore } from '@/stores/auth';
import { useWorkspaceStore } from '@/stores/workspace';

import { ChatMessage } from './ChatMessage';
import { MentionInput } from './MentionInput';


export interface ChatPanelProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ tenantId, projectId, workspaceId }) => {
  const { messages, loading, members, agents, loadMessages, sendMessage } = useWorkspaceStore(
    useShallow((state) => ({
      messages: state.chatMessages,
      loading: state.chatLoading,
      members: state.members,
      agents: state.agents,
      loadMessages: state.loadChatMessages,
      sendMessage: state.sendChatMessage,
    }))
  );

  const currentUser = useAuthStore((state) => state.user);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadMessages(tenantId, projectId, workspaceId);
  }, [tenantId, projectId, workspaceId, loadMessages]);

  useEffect(() => {
    if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const handleSend = (content: string) => {
    if (content.trim()) {
      sendMessage(tenantId, projectId, workspaceId, content);
    }
  };

  return (
    <div className="flex flex-col h-full bg-gray-50 border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex-1 overflow-y-auto p-4 scroll-smooth">
        {loading && messages.length === 0 ? (
          <div className="flex justify-center items-center h-full">
            <Spin />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex justify-center items-center h-full">
            <Empty description="No messages yet. Start the conversation!" />
          </div>
        ) : (
          <div className="flex flex-col pb-2">
            {messages.map((msg) => (
              <ChatMessage
                key={msg.id}
                message={msg}
                isOwn={msg.sender_id === currentUser?.id}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>
      <div className="p-3 bg-white border-t border-gray-200">
        <MentionInput onSend={handleSend} members={members} agents={agents} disabled={loading} />
      </div>
    </div>
  );
};
