import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDownIcon,
  ChevronUpIcon,
  Cross2Icon,
  MagnifyingGlassIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import {
  conversationSearchMatches,
  moveConversationSearchIndex,
  resolveConversationSearchIndex,
  type ConversationSearchDirection,
} from './conversationSearchModel';

type ConversationSearchProps = {
  items: readonly AgentTimelineItem[];
  visible: boolean;
  onNavigate: (itemId: string, onLocated: (target: HTMLElement) => void) => () => void;
  onClose: () => void;
};

export function ConversationSearch({
  items,
  visible,
  onNavigate,
  onClose,
}: ConversationSearchProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [selectedAnchor, setSelectedAnchor] = useState<string | null>(null);
  const [navigationRequest, setNavigationRequest] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const navigateRef = useRef(onNavigate);
  useLayoutEffect(() => {
    navigateRef.current = onNavigate;
  }, [onNavigate]);
  const matches = useMemo(() => conversationSearchMatches(items, query), [items, query]);

  useEffect(() => {
    if (!visible) {
      setQuery('');
      setSelectedAnchor(null);
      const previousFocus = previousFocusRef.current;
      previousFocusRef.current = null;
      if (previousFocus?.isConnected) {
        const frame = window.requestAnimationFrame(() => previousFocus.focus({ preventScroll: true }));
        return () => window.cancelAnimationFrame(frame);
      }
      return undefined;
    }

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [visible]);

  const currentIndex = resolveConversationSearchIndex(matches, selectedAnchor, 0);
  const anchorId = matches[currentIndex]?.anchorId ?? null;
  useEffect(() => {
    setSelectedAnchor(anchorId);
  }, [anchorId]);

  useEffect(() => {
    if (!visible || !anchorId) return;
    let highlighted: HTMLElement | null = null;
    const cancel = navigateRef.current(anchorId, (target) => {
      highlighted = target;
      target.classList.add('chat-search-highlight');
    });
    return () => {
      cancel();
      highlighted?.classList.remove('chat-search-highlight');
    };
  }, [anchorId, navigationRequest, query, visible]);

  if (!visible) return null;

  const move = (direction: ConversationSearchDirection) => {
    const nextIndex = moveConversationSearchIndex(currentIndex, matches.length, direction);
    setSelectedAnchor(matches[nextIndex]?.anchorId ?? null);
    setNavigationRequest((request) => request + 1);
  };
  const resultLabel = matches.length
    ? t('chat.search.resultCount', {
        current: currentIndex + 1,
        total: matches.length,
      })
    : t('chat.search.noResults');

  return (
    <section
      className="conversation-search-overlay"
      role="search"
      aria-label={t('chat.search.label')}
    >
      <MagnifyingGlassIcon aria-hidden="true" />
      <input
        ref={inputRef}
        type="search"
        value={query}
        placeholder={t('chat.search.placeholder')}
        aria-label={t('chat.search.placeholder')}
        onChange={(event) => {
          setSelectedAnchor(null);
          setQuery(event.currentTarget.value);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            onClose();
          } else if (event.key === 'Enter') {
            event.preventDefault();
            move(event.shiftKey ? 'previous' : 'next');
          }
        }}
      />
      {query ? (
        <output className="conversation-search-count" aria-live="polite">
          {resultLabel}
        </output>
      ) : null}
      <div className="conversation-search-actions">
        <button
          type="button"
          disabled={!matches.length}
          aria-label={t('chat.search.previousResult')}
          title={t('chat.search.previousResult')}
          onClick={() => move('previous')}
        >
          <ChevronUpIcon />
        </button>
        <button
          type="button"
          disabled={!matches.length}
          aria-label={t('chat.search.nextResult')}
          title={t('chat.search.nextResult')}
          onClick={() => move('next')}
        >
          <ChevronDownIcon />
        </button>
        <button
          type="button"
          aria-label={t('chat.search.close')}
          title={t('chat.search.close')}
          onClick={onClose}
        >
          <Cross2Icon />
        </button>
      </div>
    </section>
  );
}
