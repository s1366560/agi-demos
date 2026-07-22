import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Spin, Empty } from 'antd';
import { useShallow } from 'zustand/react/shallow';

import { useAuthStore } from '@/stores/auth';
import { useWorkspaceStore } from '@/stores/workspace';

import { useLazyMessage } from '@/components/ui/lazyAntd';

import { ChatMessage } from './ChatMessage';
import { MentionInput } from './MentionInput';

export interface ChatPanelProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ tenantId, projectId, workspaceId }) => {
  const { t } = useTranslation();
  const message = useLazyMessage();
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
  const chatContextKey = `${tenantId}:${projectId}:${workspaceId}`;
  const [loadErrorContext, setLoadErrorContext] = useState<string | null>(null);
  const loadError = loadErrorContext === chatContextKey;

  const load = useCallback(async () => {
    setLoadErrorContext(null);
    try {
      await loadMessages(tenantId, projectId, workspaceId);
    } catch {
      setLoadErrorContext(chatContextKey);
    }
  }, [chatContextKey, tenantId, projectId, workspaceId, loadMessages]);

  useEffect(() => {
    let cancelled = false;

    void loadMessages(tenantId, projectId, workspaceId).then(
      () => {
        if (!cancelled) {
          setLoadErrorContext((current) => (current === chatContextKey ? null : current));
        }
      },
      () => {
        if (!cancelled) {
          setLoadErrorContext(chatContextKey);
        }
      }
    );

    return () => {
      cancelled = true;
    };
  }, [chatContextKey, tenantId, projectId, workspaceId, loadMessages]);

  const prevMessageCount = useRef(0);
  useEffect(() => {
    if (messages.length > prevMessageCount.current) {
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      messagesEndRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' });
    }
    prevMessageCount.current = messages.length;
  }, [messages.length]);

  const handleSend = async (content: string, mentions: string[]): Promise<boolean> => {
    if (!content.trim()) {
      return false;
    }
    try {
      await sendMessage(tenantId, projectId, workspaceId, content, mentions);
      return true;
    } catch {
      message?.error(t('workspaceDetail.chat.sendFailed'));
      return false;
    }
  };

  return (
    <div className="flex flex-col h-full min-h-[300px] sm:min-h-[400px] md:min-h-[500px] bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden transition-colors duration-200">
      <div className="flex-1 overflow-y-auto p-4">
        {loading && messages.length === 0 ? (
          <div className="flex justify-center items-center h-full" role="status">
            <Spin />
          </div>
        ) : loadError && messages.length === 0 ? (
          <div className="flex flex-col justify-center items-center h-full gap-2" role="alert">
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {t('workspaceDetail.chat.loadFailed')}
            </span>
            <button
              type="button"
              onClick={() => {
                void load();
              }}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              {t('common.retry')}
            </button>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex justify-center items-center h-full">
            <Empty description={t('workspaceDetail.chat.noMessages')} />
          </div>
        ) : (
          <div className="flex flex-col pb-2" aria-live="polite">
            {messages.map((msg) => (
              <ChatMessage key={msg.id} message={msg} isOwn={msg.sender_id === currentUser?.id} />
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
