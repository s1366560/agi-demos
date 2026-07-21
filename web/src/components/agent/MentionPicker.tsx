/**
 * MentionPicker — Track B P2-3 phase-2 (b-fe-mention).
 *
 * Reads the roster via ``useConversationParticipants`` and renders a
 * keyboard-navigable @mention dropdown. Selection fires
 * ``onMentionSelected(agentId)`` so the host input can insert the token.
 *
 * Agent First note: this is a *structural* UI — it only presents the
 * current roster and never parses free-form text to guess who is
 * meant. The chosen agent ID is later sent as ``message.mentions`` to
 * the backend; the ConversationAwareRouter resolves by set-membership
 * against the roster.
 */

import {
  memo,
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';

import { useTranslation } from 'react-i18next';

import { useMentionCandidates } from '../../hooks/useMentionCandidates';

import type { MentionPopoverHandle } from './chat/MentionPopover';

export interface MentionPickerProps {
  conversationId: string | null;
  query: string;
  open: boolean;
  onMentionSelected: (agentId: string) => void;
  onDismiss: () => void;
  className?: string;
  /** Controlled active index (shared with the host textarea keyboard flow). */
  selectedIndex?: number | undefined;
  onSelectedIndexChange?: ((index: number) => void) | undefined;
}

export const MentionPicker = memo(
  forwardRef<MentionPopoverHandle, MentionPickerProps>(
    (
      {
        conversationId,
        query,
        open,
        onMentionSelected,
        onDismiss,
        className,
        selectedIndex,
        onSelectedIndexChange,
      },
      ref
    ) => {
      const { t } = useTranslation();
      const listboxId = useId();
      const { candidates: roster } = useMentionCandidates(conversationId, { enabled: open });
      const [activeState, setActiveState] = useState<{ trigger: string; index: number }>({
        trigger: `${String(open)}|${query}`,
        index: 0,
      });
      const listRef = useRef<HTMLUListElement>(null);
      const trigger = `${String(open)}|${query}`;
      const isControlled = selectedIndex !== undefined;
      const internalIndex = activeState.trigger === trigger ? activeState.index : 0;
      const setInternalIndex = useCallback(
        (next: number | ((prev: number) => number)) => {
          setActiveState((prev) => {
            const base = prev.trigger === trigger ? prev.index : 0;
            const resolved = typeof next === 'function' ? next(base) : next;
            return { trigger, index: resolved };
          });
        },
        [trigger]
      );
      const setActiveIndex = useCallback(
        (next: number | ((prev: number) => number)) => {
          if (isControlled) {
            const base = selectedIndex;
            onSelectedIndexChange?.(typeof next === 'function' ? next(base) : next);
          } else {
            setInternalIndex(next);
          }
        },
        [isControlled, selectedIndex, onSelectedIndexChange, setInternalIndex]
      );

      const candidates = useMemo(() => {
        if (!roster.length) return [];
        const q = query.toLowerCase();
        // Substring filter over the bounded set — Agent-First: never a
        // free-form classifier, always a structural match.
        return roster.filter((c) => {
          const id = c.agent_id.toLowerCase();
          const name = (c.display_name ?? '').toLowerCase();
          const label = (c.label ?? '').toLowerCase();
          return id.includes(q) || name.includes(q) || label.includes(q);
        });
      }, [roster, query]);

      // Clamp the (possibly host-driven) index into the visible range.
      const activeIndex =
        candidates.length > 0
          ? Math.min(
              Math.max(isControlled ? selectedIndex : internalIndex, 0),
              candidates.length - 1
            )
          : 0;

      // Let the host textarea commit the highlighted item on Enter/Tab,
      // mirroring MentionPopover's imperative handle.
      useImperativeHandle(
        ref,
        () => ({
          getSelectedItem: () => {
            const selected = candidates[activeIndex];
            return selected
              ? { id: selected.agent_id, name: selected.agent_id, type: 'participant' as const }
              : null;
          },
        }),
        [candidates, activeIndex]
      );

      useEffect(() => {
        const item = listRef.current?.children[activeIndex];
        item?.scrollIntoView({ block: 'nearest' });
      }, [activeIndex]);

      const handleKey = useCallback(
        (event: KeyboardEvent<HTMLDivElement>) => {
          if (!open || candidates.length === 0) return;
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            setActiveIndex((i) => (i + 1) % candidates.length);
          } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setActiveIndex((i) => (i - 1 + candidates.length) % candidates.length);
          } else if (event.key === 'Enter' || event.key === 'Tab') {
            event.preventDefault();
            const selected = candidates[activeIndex];
            if (selected) onMentionSelected(selected.agent_id);
          } else if (event.key === 'Escape') {
            event.preventDefault();
            onDismiss();
          }
        },
        [candidates, activeIndex, open, onMentionSelected, onDismiss, setActiveIndex]
      );

      if (!open || !conversationId || candidates.length === 0) {
        return null;
      }

      return (
        <div
          role="listbox"
          data-testid="mention-picker"
          aria-label={t('agent.mention.label', { defaultValue: 'Mention an agent' })}
          aria-activedescendant={`${listboxId}-option-${String(activeIndex)}`}
          tabIndex={-1}
          onKeyDown={handleKey}
          className={
            className ??
            'absolute bottom-full left-0 z-20 mb-1 w-60 overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-800 dark:bg-slate-900'
          }
        >
          <ul ref={listRef} className="max-h-60 overflow-auto py-1">
            {candidates.map((candidate, idx) => (
              <li
                key={candidate.agent_id}
                id={`${listboxId}-option-${String(idx)}`}
                role="option"
                aria-selected={idx === activeIndex}
                onMouseEnter={() => {
                  setActiveIndex(idx);
                }}
                onClick={() => {
                  onMentionSelected(candidate.agent_id);
                }}
                className={`flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 text-sm ${
                  idx === activeIndex
                    ? 'bg-slate-50 text-primary dark:bg-slate-800 dark:text-primary-400'
                    : 'text-slate-900 dark:text-slate-100'
                }`}
              >
                <span className="truncate">
                  @{candidate.agent_id}
                  {candidate.display_name ? (
                    <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
                      {candidate.display_name}
                    </span>
                  ) : null}
                </span>
                {candidate.label ? (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-900 dark:bg-slate-800 dark:text-slate-100">
                    {candidate.label}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      );
    }
  )
);

MentionPicker.displayName = 'MentionPicker';
