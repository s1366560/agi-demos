/**
 * ConversationPickerModal - Select a conversation for comparison
 *
 * Shows a searchable list of conversations (excluding the current one)
 * so the user can pick which conversation to compare with.
 */
import { memo, useState, useMemo, useCallback, useEffect, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { Search, MessageSquare, X } from 'lucide-react';

import type { Conversation } from '@/types/agent';

interface ConversationPickerModalProps {
  visible: boolean;
  currentConversationId: string;
  conversations: Conversation[];
  onSelect: (conversationId: string) => void;
  onClose: () => void;
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '';
  try {
    return new Date(dateStr).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

export const ConversationPickerModal = memo(
  ({
    visible,
    currentConversationId,
    conversations,
    onSelect,
    onClose,
  }: ConversationPickerModalProps) => {
    const { t } = useTranslation();
    const [search, setSearch] = useState('');
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
      if (visible) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setSearch('');
        setTimeout(() => inputRef.current?.focus(), 100);
      }
    }, [visible]);

    const filteredConversations = useMemo(() => {
      const available = conversations.filter((c) => c.id !== currentConversationId);
      if (!search.trim()) return available;
      const lower = search.toLowerCase();
      return available.filter(
        (c) => c.title.toLowerCase().includes(lower) || c.id.toLowerCase().includes(lower)
      );
    }, [conversations, currentConversationId, search]);

    const handleSelect = useCallback(
      (id: string) => {
        onSelect(id);
        onClose();
      },
      [onSelect, onClose]
    );

    // Close on Escape
    useEffect(() => {
      if (!visible) return;
      const handleKey = (e: KeyboardEvent) => {
        if (e.key === 'Escape') onClose();
      };
      window.addEventListener('keydown', handleKey);
      return () => window.removeEventListener('keydown', handleKey);
    }, [visible, onClose]);

    if (!visible) return null;

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
        <div className="w-full max-w-md mx-4 bg-white dark:bg-slate-800 rounded-xl shadow-2xl border border-slate-200/60 dark:border-slate-700/50 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/50">
            <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('comparison.selectConversation', 'Select conversation to compare')}
            </h3>
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <X size={16} />
            </button>
          </div>

          {/* Search */}
          <div className="px-4 py-2 border-b border-slate-200/60 dark:border-slate-700/50">
            <div className="relative">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                ref={inputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('comparison.search', 'Search conversations...')}
                className="w-full pl-8 pr-3 py-1.5 text-sm rounded-md border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/50 text-slate-700 dark:text-slate-200 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-primary/50"
              />
            </div>
          </div>

          {/* List */}
          <div className="max-h-80 overflow-y-auto">
            {filteredConversations.length === 0 ? (
              <div className="flex items-center justify-center py-8 text-sm text-slate-400">
                {t('comparison.noResults', 'No conversations found')}
              </div>
            ) : (
              filteredConversations.map((conv) => (
                <button
                  key={conv.id}
                  type="button"
                  onClick={() => handleSelect(conv.id)}
                  className="w-full text-left px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors border-b border-slate-100 dark:border-slate-700/30 last:border-b-0"
                >
                  <div className="flex items-start gap-2.5">
                    <MessageSquare size={14} className="mt-0.5 flex-shrink-0 text-slate-400" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
                        {conv.title}
                      </p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-slate-400">
                        <span>
                          {conv.message_count} {conv.message_count === 1 ? 'message' : 'messages'}
                        </span>
                        {conv.updated_at && (
                          <>
                            <span className="text-slate-300 dark:text-slate-600">|</span>
                            <span>{formatDate(conv.updated_at)}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    );
  }
);

ConversationPickerModal.displayName = 'ConversationPickerModal';
