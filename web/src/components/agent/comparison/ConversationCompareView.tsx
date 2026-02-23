/**
 * ConversationCompareView - Side-by-side conversation comparison
 *
 * Shows two conversations side-by-side for easy comparison.
 * Only renders user and assistant messages in a simplified view.
 */
import { memo, useState, useEffect, useRef, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { GitCompareArrows, X, MessageSquare } from 'lucide-react';

import { agentService } from '@/services/agentService';

import type { Conversation, TimelineEvent } from '@/types/agent';

interface SimpleMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

interface ConversationCompareViewProps {
  projectId: string;
  leftConversationId: string;
  rightConversationId: string | null;
  conversations: Conversation[];
  onClose: () => void;
  onSelectRight: () => void;
}

function extractMessages(timeline: TimelineEvent[]): SimpleMessage[] {
  const messages: SimpleMessage[] = [];
  for (const event of timeline) {
    if (event.type === 'user_message' || event.type === 'assistant_message') {
      const typed = event as { id: string; content: string; timestamp: number; type: string };
      messages.push({
        id: typed.id,
        role: event.type === 'user_message' ? 'user' : 'assistant',
        content: typed.content,
        timestamp: typed.timestamp,
      });
    }
  }
  return messages;
}

const SimpleMessageBubble = memo(
  ({ role, content }: { role: 'user' | 'assistant'; content: string }) => (
    <div className={`mb-3 flex ${role === 'user' ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] px-3 py-2 rounded-xl text-sm whitespace-pre-wrap break-words ${
          role === 'user'
            ? 'bg-primary/10 text-primary-700 dark:text-primary-300'
            : 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300'
        }`}
      >
        {content}
      </div>
    </div>
  )
);

SimpleMessageBubble.displayName = 'SimpleMessageBubble';

interface PanelProps {
  title: string;
  messages: SimpleMessage[];
  loading: boolean;
  placeholder?: React.ReactNode;
}

const ComparePanel = memo(({ title, messages, loading, placeholder }: PanelProps) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  return (
    <div className="flex-1 min-w-0 flex flex-col h-full border-r last:border-r-0 border-slate-200/60 dark:border-slate-700/50">
      <div className="flex-shrink-0 px-4 py-2.5 border-b border-slate-200/60 dark:border-slate-700/50 bg-slate-50/80 dark:bg-slate-800/50">
        <div className="flex items-center gap-2">
          <MessageSquare size={14} className="text-slate-400" />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
            {title}
          </span>
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex items-center justify-center h-32 text-slate-400 text-sm">
            Loading...
          </div>
        ) : placeholder ? (
          placeholder
        ) : messages.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-slate-400 text-sm">
            No messages
          </div>
        ) : (
          messages.map((msg) => (
            <SimpleMessageBubble key={msg.id} role={msg.role} content={msg.content} />
          ))
        )}
      </div>
    </div>
  );
});

ComparePanel.displayName = 'ComparePanel';

export const ConversationCompareView = memo(
  ({
    projectId,
    leftConversationId,
    rightConversationId,
    conversations,
    onClose,
    onSelectRight,
  }: ConversationCompareViewProps) => {
    const { t } = useTranslation();

    const [leftMessages, setLeftMessages] = useState<SimpleMessage[]>([]);
    const [rightMessages, setRightMessages] = useState<SimpleMessage[]>([]);
    const [leftLoading, setLeftLoading] = useState(true);
    const [rightLoading, setRightLoading] = useState(false);

    const leftConv = conversations.find((c) => c.id === leftConversationId);
    const rightConv = rightConversationId
      ? conversations.find((c) => c.id === rightConversationId)
      : null;

    const loadConversationMessages = useCallback(
      async (conversationId: string) => {
        const response = await agentService.getConversationMessages(conversationId, projectId, 200);
        return extractMessages(response.timeline);
      },
      [projectId]
    );

    useEffect(() => {
      let cancelled = false;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLeftLoading(true);
      loadConversationMessages(leftConversationId)
        .then((msgs) => {
          if (!cancelled) setLeftMessages(msgs);
        })
        .catch(() => {
          if (!cancelled) setLeftMessages([]);
        })
        .finally(() => {
          if (!cancelled) setLeftLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }, [leftConversationId, loadConversationMessages]);

    useEffect(() => {
      if (!rightConversationId) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setRightMessages([]);
        return;
      }
      let cancelled = false;
      setRightLoading(true);
      loadConversationMessages(rightConversationId)
        .then((msgs) => {
          if (!cancelled) setRightMessages(msgs);
        })
        .catch(() => {
          if (!cancelled) setRightMessages([]);
        })
        .finally(() => {
          if (!cancelled) setRightLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }, [rightConversationId, loadConversationMessages]);

    return (
      <div className="flex flex-col h-full w-full bg-white dark:bg-slate-900">
        {/* Header */}
        <div className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 border-b border-slate-200/60 dark:border-slate-700/50 bg-slate-50/80 dark:bg-slate-800/50">
          <div className="flex items-center gap-2">
            <GitCompareArrows size={16} className="text-slate-500" />
            <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('comparison.title', 'Compare Conversations')}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title={t('comparison.exitCompare', 'Exit comparison')}
          >
            <X size={16} />
          </button>
        </div>

        {/* Side-by-side panels */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          <ComparePanel
            title={leftConv?.title || leftConversationId}
            messages={leftMessages}
            loading={leftLoading}
          />
          <ComparePanel
            title={
              rightConv?.title ||
              t('comparison.selectConversation', 'Select conversation to compare')
            }
            messages={rightMessages}
            loading={rightLoading}
            placeholder={
              !rightConversationId ? (
                <div className="flex flex-col items-center justify-center h-full gap-3">
                  <GitCompareArrows size={32} className="text-slate-300 dark:text-slate-600" />
                  <p className="text-sm text-slate-400 dark:text-slate-500">
                    {t('comparison.selectConversation', 'Select conversation to compare')}
                  </p>
                  <button
                    type="button"
                    onClick={onSelectRight}
                    className="px-3 py-1.5 text-sm rounded-md bg-primary/10 text-primary-600 dark:text-primary-400 hover:bg-primary/20 transition-colors"
                  >
                    {t('comparison.selectConversation', 'Select conversation to compare')}
                  </button>
                </div>
              ) : undefined
            }
          />
        </div>
      </div>
    );
  }
);

ConversationCompareView.displayName = 'ConversationCompareView';
