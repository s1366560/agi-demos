/**
 * ThreadView - Inline thread view showing replies to a message
 */
import { memo, useState, useEffect } from 'react';


import { useTranslation } from 'react-i18next';

import { MessageSquare, ChevronDown, ChevronRight, Send, Loader2 } from 'lucide-react';

import { getAuthToken } from '@/utils/tokenResolver';

interface ThreadReply {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

interface ThreadViewProps {
  messageId: string;
  conversationId: string;
  replyCount: number;
  onSendReply: (content: string, replyToId: string) => void;
}

export const ThreadView = memo<ThreadViewProps>(
  ({ messageId, conversationId, replyCount, onSendReply }) => {
    const { t } = useTranslation();
    const [expanded, setExpanded] = useState(false);
    const [replies, setReplies] = useState<ThreadReply[]>([]);
    const [loading, setLoading] = useState(false);
    const [replyText, setReplyText] = useState('');

    useEffect(() => {
      if (!expanded || !conversationId || !messageId) return;
      const abortController = new AbortController();
      setLoading(true);
      fetch(
        `/api/v1/agent/conversations/${conversationId}/messages/${messageId}/replies`,
        {
          headers: {
            Authorization: `Bearer ${getAuthToken()}`,
          },
          signal: abortController.signal,
        }
      )
        .then((res) => res.json())
        .then((data) => {
          if (!abortController.signal.aborted) {
            setReplies(data);
            setLoading(false);
          }
        })
        .catch((err) => {
          if (!abortController.signal.aborted) {
            console.error('Failed to fetch thread replies:', err);
            setLoading(false);
          }
        });
      return () => abortController.abort();
    }, [expanded, conversationId, messageId]);

    if (replyCount === 0 && !expanded) return null;

    return (
      <div className="ml-10 mt-1 mb-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 text-xs text-primary hover:text-primary-600 transition-colors"
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <MessageSquare size={12} />
          <span>
            {replyCount > 0
              ? t('agent.thread.replies', '{{count}} replies', {
                  count: replyCount,
                })
              : t('agent.thread.reply', 'Reply')}
          </span>
        </button>

        {expanded && (
          <div className="mt-2 pl-3 border-l-2 border-primary/20">
            {loading ? (
              <div className="py-2">
                <Loader2
                  size={14}
                  className="animate-spin text-slate-400"
                />
              </div>
            ) : (
              <>
                {replies.map((reply) => (
                  <div
                    key={reply.id}
                    className={`mb-2 flex ${reply.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[90%] px-3 py-1.5 rounded-lg text-xs ${
                        reply.role === 'user'
                          ? 'bg-primary/10 text-slate-700 dark:text-slate-300'
                          : 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300'
                      }`}
                    >
                      {reply.content}
                    </div>
                  </div>
                ))}
                <div className="flex items-center gap-2 mt-2">
                  <input
                    value={replyText}
                    onChange={(e) => setReplyText(e.target.value)}
                    placeholder={t(
                      'agent.thread.replyPlaceholder',
                      'Write a reply...'
                    )}
                    className="flex-1 px-2.5 py-1.5 text-xs bg-transparent border border-slate-200 dark:border-slate-600 rounded-lg"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && replyText.trim()) {
                        onSendReply(replyText, messageId);
                        setReplyText('');
                      }
                    }}
                  />
                  <button
                    onClick={() => {
                      if (replyText.trim()) {
                        onSendReply(replyText, messageId);
                        setReplyText('');
                      }
                    }}
                    disabled={!replyText.trim()}
                    className="p-1.5 rounded-lg bg-primary text-white disabled:opacity-50"
                  >
                    <Send size={12} />
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    );
  }
);
ThreadView.displayName = 'ThreadView';
