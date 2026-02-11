/**
 * ChatSearch - In-conversation search overlay (Cmd+F)
 *
 * Provides search-within-chat functionality with match highlighting,
 * result count, and next/prev navigation.
 */

import { memo, useState, useCallback, useRef, useEffect } from 'react';

import { Search, X, ChevronUp, ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { TimelineEvent } from '@/types/agent';

interface ChatSearchProps {
  timeline: TimelineEvent[];
  onClose: () => void;
  visible: boolean;
}

interface SearchMatch {
  eventIndex: number;
  eventId: string;
  preview: string;
}

/**
 * Extract searchable text content from a timeline event
 */
function getEventText(event: TimelineEvent): string {
  const parts: string[] = [];

  if (event.type === 'user_message') {
    parts.push(event.content || '');
  } else if (event.type === 'assistant_message') {
    parts.push(event.content || '');
  } else if (event.type === 'thought') {
    parts.push(event.content || '');
  } else if (event.type === 'act') {
    parts.push(event.toolName || '');
    if (event.toolInput) {
      parts.push(JSON.stringify(event.toolInput));
    }
  } else if (event.type === 'observe') {
    parts.push(event.toolOutput || '');
  }

  return parts.join(' ');
}

export const ChatSearch = memo<ChatSearchProps>(({ timeline, onClose, visible }) => {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus on open, clear highlights on close
  useEffect(() => {
    if (visible) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQuery('');
      setMatches([]);
      document.querySelectorAll('.chat-search-highlight').forEach((el) => {
        el.classList.remove('chat-search-highlight');
      });
    }
  }, [visible]);

  // Search logic
  useEffect(() => {
    if (!query.trim()) {
      setMatches([]);
      setCurrentIndex(0);
      return;
    }

    const q = query.toLowerCase();
    const found: SearchMatch[] = [];

    timeline.forEach((event, idx) => {
      const text = getEventText(event);
      if (text.toLowerCase().includes(q)) {
        const matchIdx = text.toLowerCase().indexOf(q);
        const start = Math.max(0, matchIdx - 30);
        const end = Math.min(text.length, matchIdx + query.length + 30);
        let preview = text.slice(start, end);
        if (start > 0) preview = '...' + preview;
        if (end < text.length) preview = preview + '...';

        found.push({
          eventIndex: idx,
          eventId: event.id || `event-${idx}`,
          preview,
        });
      }
    });

    setMatches(found);
    setCurrentIndex(0);
  }, [query, timeline]);

  // Scroll to match and highlight
  useEffect(() => {
    // Clear previous highlights
    document.querySelectorAll('.chat-search-highlight').forEach((el) => {
      el.classList.remove('chat-search-highlight');
    });

    if (matches.length === 0 || !visible) return;
    const match = matches[currentIndex];
    if (!match) return;

    const container = document.querySelector(`[data-testid="message-container"]`);
    if (!container) return;

    // Find the message element by data-msg-index or by iterating event keys
    const allMsgEls = container.querySelectorAll('[data-msg-index]');
    for (const el of allMsgEls) {
      const key = el.getAttribute('key') || '';
      // Match by searching through child message bubble content
      if (key === match.eventId) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('chat-search-highlight');
        return;
      }
    }

    // Fallback: scroll by index in the grouped list. The eventIndex maps to timeline,
    // but data-msg-index maps to grouped items. Find by scanning text content.
    for (const el of allMsgEls) {
      const text = el.textContent || '';
      if (query && text.toLowerCase().includes(query.toLowerCase())) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('chat-search-highlight');
        return;
      }
    }
  }, [currentIndex, matches, query, visible]);

  const goNext = useCallback(() => {
    setCurrentIndex((i) => (i + 1) % Math.max(matches.length, 1));
  }, [matches.length]);

  const goPrev = useCallback(() => {
    setCurrentIndex((i) => (i - 1 + matches.length) % Math.max(matches.length, 1));
  }, [matches.length]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'Enter') {
        if (e.shiftKey) {
          goPrev();
        } else {
          goNext();
        }
      }
    },
    [onClose, goNext, goPrev]
  );

  if (!visible) return null;

  return (
    <div className="absolute top-2 right-4 z-50 flex items-center gap-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl px-3 py-2 animate-fade-in-up">
      <Search size={14} className="text-slate-400 flex-shrink-0" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t('agent.search.placeholder', 'Search in conversation...')}
        className="w-48 bg-transparent text-sm text-slate-700 dark:text-slate-200 placeholder:text-slate-400 focus:outline-none"
      />
      {query && (
        <span className="text-xs text-slate-400 whitespace-nowrap">
          {matches.length > 0
            ? `${currentIndex + 1}/${matches.length}`
            : t('agent.search.noResults', '0 results')}
        </span>
      )}
      <div className="flex items-center gap-0.5">
        <button
          type="button"
          onClick={goPrev}
          disabled={matches.length === 0}
          className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 disabled:opacity-30 transition-colors"
        >
          <ChevronUp size={14} />
        </button>
        <button
          type="button"
          onClick={goNext}
          disabled={matches.length === 0}
          className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 disabled:opacity-30 transition-colors"
        >
          <ChevronDown size={14} />
        </button>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
});
ChatSearch.displayName = 'ChatSearch';
