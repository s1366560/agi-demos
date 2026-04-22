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
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';

import { useMentionCandidates } from '../../hooks/useMentionCandidates';

export interface MentionPickerProps {
  conversationId: string | null;
  query: string;
  open: boolean;
  onMentionSelected: (agentId: string) => void;
  onDismiss: () => void;
  className?: string;
}

export const MentionPicker = memo<MentionPickerProps>(
  ({ conversationId, query, open, onMentionSelected, onDismiss, className }) => {
    const { t } = useTranslation();
    const { candidates: roster } = useMentionCandidates(conversationId, { enabled: open });
    const [activeState, setActiveState] = useState<{ trigger: string; index: number }>({
      trigger: `${open}|${query}`,
      index: 0,
    });
    const listRef = useRef<HTMLUListElement>(null);
    const trigger = `${open}|${query}`;
    const activeIndex = activeState.trigger === trigger ? activeState.index : 0;
    const setActiveIndex = useCallback(
      (next: number | ((prev: number) => number)) => {
        setActiveState((prev) => {
          const base = prev.trigger === trigger ? prev.index : 0;
          const resolved = typeof next === 'function' ? next(base) : next;
          return { trigger, index: resolved };
        });
      },
      [trigger]
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
        tabIndex={-1}
        onKeyDown={handleKey}
        className={
          className ??
          'absolute z-20 w-60 overflow-hidden rounded-md border border-[rgba(0,0,0,0.08)] bg-white shadow-[0_4px_8px_rgba(0,0,0,0.04),0_16px_24px_rgba(0,0,0,0.06)]'
        }
      >
        <ul ref={listRef} className="max-h-60 overflow-auto py-1">
          {candidates.map((candidate, idx) => (
            <li
              key={candidate.agent_id}
              role="option"
              aria-selected={idx === activeIndex}
              onMouseEnter={() => setActiveIndex(idx)}
              onClick={() => onMentionSelected(candidate.agent_id)}
              className={`flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 text-sm ${
                idx === activeIndex ? 'bg-[#fafafa] text-[#0070f3]' : 'text-[#171717]'
              }`}
            >
              <span className="truncate">
                @{candidate.agent_id}
                {candidate.display_name ? (
                  <span className="ml-2 text-xs text-[#666]">{candidate.display_name}</span>
                ) : null}
              </span>
              {candidate.label ? (
                <span className="rounded-full bg-[#ebebeb] px-2 py-0.5 text-[11px] text-[#171717]">
                  {candidate.label}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    );
  }
);

MentionPicker.displayName = 'MentionPicker';

/**
 * extractMentionQuery — helper for host input components.
 *
 * Given the raw text up to the caret, returns the mention trigger query
 * (characters after the last ``@`` that is either at start or preceded
 * by whitespace) or ``null`` if no active mention.
 *
 * Pure structural tokenizer — no NL interpretation. The *selection* of
 * which agent the user means is driven by their explicit click/enter
 * from the picker; this helper merely detects that a mention is being
 * typed.
 */
export function extractMentionQuery(textBeforeCaret: string): string | null {
  if (!textBeforeCaret) return null;
  const atIdx = textBeforeCaret.lastIndexOf('@');
  if (atIdx < 0) return null;
  const isAtBoundary = atIdx === 0 || /\s/.test(textBeforeCaret[atIdx - 1] ?? '');
  if (!isAtBoundary) return null;
  const query = textBeforeCaret.slice(atIdx + 1);
  // A whitespace in the query means the mention already ended.
  if (/\s/.test(query)) return null;
  return query;
}
