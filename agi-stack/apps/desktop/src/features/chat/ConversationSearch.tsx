import { useEffect, useMemo, useRef, useState } from 'react';
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
  getViewport: () => HTMLElement | null;
  onRevealItem?: (itemId: string) => boolean;
  onClose: () => void;
};

export function ConversationSearch({
  items,
  visible,
  getViewport,
  onRevealItem,
  onClose,
}: ConversationSearchProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [currentIndex, setCurrentIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const selectedAnchorRef = useRef<string | null>(null);
  const matches = useMemo(() => conversationSearchMatches(items, query), [items, query]);

  useEffect(() => {
    if (!visible) {
      clearSearchHighlights(getViewport());
      setQuery('');
      setCurrentIndex(0);
      selectedAnchorRef.current = null;
      const previousFocus = previousFocusRef.current;
      previousFocusRef.current = null;
      if (previousFocus?.isConnected) {
        window.requestAnimationFrame(() => previousFocus.focus());
      }
      return undefined;
    }

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [getViewport, visible]);

  useEffect(() => {
    if (!matches.length) {
      selectedAnchorRef.current = null;
      setCurrentIndex(0);
      return;
    }
    setCurrentIndex((index) => {
      const nextIndex = resolveConversationSearchIndex(
        matches,
        selectedAnchorRef.current,
        index,
      );
      selectedAnchorRef.current = matches[nextIndex]?.anchorId ?? null;
      return nextIndex;
    });
  }, [matches]);

  useEffect(() => {
    const viewport = getViewport();
    clearSearchHighlights(viewport);
    if (!visible || !viewport || !matches.length) return undefined;

    const match = matches[currentIndex];
    if (!match) return undefined;
    selectedAnchorRef.current = match.anchorId;
    let firstFrame: number | null = null;
    let secondFrame: number | null = null;
    let target: HTMLElement | null = null;
    const scrollToMatch = () => {
      const anchors = Array.from(
        viewport.querySelectorAll<HTMLElement>('[data-timeline-anchor-id]'),
      );
      target =
        anchors.find((anchor) => anchor.dataset.timelineAnchorId === match.anchorId) ??
        anchors.find((anchor) => anchorContainsSearchMember(anchor, match.anchorId)) ??
        null;
      if (!target) return;

      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      target.scrollIntoView({
        behavior: reducedMotion ? 'auto' : 'smooth',
        block: 'center',
      });
      target.classList.add('chat-search-highlight');
    };
    if (onRevealItem?.(match.anchorId)) {
      firstFrame = window.requestAnimationFrame(() => {
        secondFrame = window.requestAnimationFrame(scrollToMatch);
      });
    } else {
      scrollToMatch();
    }
    return () => {
      if (firstFrame !== null) window.cancelAnimationFrame(firstFrame);
      if (secondFrame !== null) window.cancelAnimationFrame(secondFrame);
      target?.classList.remove('chat-search-highlight');
    };
  }, [currentIndex, getViewport, matches, onRevealItem, visible]);

  if (!visible) return null;

  const move = (direction: ConversationSearchDirection) => {
    setCurrentIndex((index) => {
      const nextIndex = moveConversationSearchIndex(index, matches.length, direction);
      selectedAnchorRef.current = matches[nextIndex]?.anchorId ?? null;
      return nextIndex;
    });
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
          selectedAnchorRef.current = null;
          setCurrentIndex(0);
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

function clearSearchHighlights(viewport: HTMLElement | null) {
  viewport
    ?.querySelectorAll('.chat-search-highlight')
    .forEach((element) => element.classList.remove('chat-search-highlight'));
}

function anchorContainsSearchMember(anchor: HTMLElement, memberId: string): boolean {
  const serialized = anchor.getAttribute('data-timeline-anchor-members');
  if (!serialized) return false;
  try {
    const members: unknown = JSON.parse(serialized);
    return Array.isArray(members) && members.includes(memberId);
  } catch {
    return false;
  }
}
