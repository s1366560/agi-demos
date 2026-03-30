import React, { useEffect, useRef } from 'react';

import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation();
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
    void loadMessages(tenantId, projectId, workspaceId);
  }, [tenantId, projectId, workspaceId, loadMessages]);

  const prevMessageCount = useRef(0);
  useEffect(() => {
    if (messages.length > prevMessageCount.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevMessageCount.current = messages.length;
  }, [messages.length]);

  const handleSend = (content: string) => {
    if (content.trim()) {
      void sendMessage(tenantId, projectId, workspaceId, content);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-[300px] sm:min-h-[400px] md:min-h-[500px] bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden transition-colors duration-200">
      <div className="flex-1 overflow-y-auto p-4 scroll-smooth">
        {loading && messages.length === 0 ? (
          <div className="flex justify-center items-center h-full">
            <Spin />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex justify-center items-center h-full">
            <Empty description={t('workspaceDetail.chat.noMessages')} />
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
      <div className="p-3 bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700 transition-colors duration-200">
        <MentionInput onSend={handleSend} members={members} agents={agents} disabled={loading} />
      </div>
    </div>
  );
};
