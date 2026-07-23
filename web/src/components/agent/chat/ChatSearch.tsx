/**
 * ChatSearch - In-conversation search overlay (Cmd+F)
 *
 * Provides search-within-chat functionality with match highlighting,
 * result count, and next/prev navigation.
 */

import { memo, useState, useCallback, useRef, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { Search, X, ChevronUp, ChevronDown } from 'lucide-react';

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
    parts.push(JSON.stringify(event.toolInput));
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
      // eslint-disable-next-line react-hooks/set-state-in-effect
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
      // eslint-disable-next-line react-hooks/set-state-in-effect
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
        if (start > 0) preview = '…' + preview;
        if (end < text.length) preview = preview + '…';

        found.push({
          eventIndex: idx,
          eventId: event.id || `event-${String(idx)}`,
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

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const behavior: ScrollBehavior = reducedMotion ? 'auto' : 'smooth';

    // Timeline order per event id, used to locate the nearest mounted row
    // when the exact match is virtualized away or inside a folded turn.
    const orderById = new Map<string, number>();
    timeline.forEach((event, idx) => {
      if (event.id) orderById.set(event.id, idx);
    });

    const mountedEls = Array.from(container.querySelectorAll('[data-msg-id]'));

    // Primary: exact match by event id (React keys never reach the DOM, but
    // MessageArea renders data-msg-id on every message row).
    const exact = mountedEls.find((el) => el.getAttribute('data-msg-id') === match.eventId);
    if (exact) {
      exact.scrollIntoView({ behavior, block: 'center' });
      exact.classList.add('chat-search-highlight');
      return;
    }

    // Fallback: the matched row is not mounted (virtualized list or folded
    // turn). Jump to the mounted message nearest in timeline order so
    // next/prev still moves instead of sticking on the first text match.
    let nearest: Element | undefined;
    let nearestDistance = Number.POSITIVE_INFINITY;
    for (const el of mountedEls) {
      const id = el.getAttribute('data-msg-id');
      const idx = id ? orderById.get(id) : undefined;
      if (idx === undefined) continue;
      const distance = Math.abs(idx - match.eventIndex);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = el;
      }
    }
    nearest?.scrollIntoView({ behavior, block: 'center' });
  }, [currentIndex, matches, visible, timeline]);

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
    <div className="absolute top-2 right-4 z-50 flex items-center gap-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg shadow-slate-200/40 dark:shadow-slate-950/20 px-3 py-2 animate-fade-in-up focus-within:ring-2 focus-within:ring-primary/50">
      <Search size={14} className="text-slate-400 flex-shrink-0" aria-hidden="true" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
        }}
        onKeyDown={handleKeyDown}
        placeholder={t('agent.search.placeholder', 'Search in conversation…')}
        aria-label={t('agent.search.placeholder', 'Search in conversation…')}
        className="w-48 bg-transparent text-sm text-slate-700 dark:text-slate-200 placeholder:text-slate-400 focus:outline-none"
      />
      {query && (
        <span className="text-xs text-slate-400 whitespace-nowrap" aria-live="polite">
          {matches.length > 0
            ? `${String(currentIndex + 1)}/${String(matches.length)}`
            : t('agent.search.noResults', '0 results')}
        </span>
      )}
      <div className="flex items-center gap-0.5">
        <button
          type="button"
          onClick={goPrev}
          disabled={matches.length === 0}
          aria-label={t('agent.search.previousResult', 'Previous result')}
          title={t('agent.search.previousResult', 'Previous result')}
          className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 disabled:opacity-30 transition-colors"
        >
          <ChevronUp size={14} />
        </button>
        <button
          type="button"
          onClick={goNext}
          disabled={matches.length === 0}
          aria-label={t('agent.search.nextResult', 'Next result')}
          title={t('agent.search.nextResult', 'Next result')}
          className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 disabled:opacity-30 transition-colors"
        >
          <ChevronDown size={14} />
        </button>
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label={t('agent.search.closeSearch', 'Close search')}
        title={t('agent.search.closeSearch', 'Close search')}
        className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
});
ChatSearch.displayName = 'ChatSearch';
