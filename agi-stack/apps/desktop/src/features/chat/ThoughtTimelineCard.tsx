import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import {
  ChevronDownIcon,
  ChevronRightIcon,
  ChevronUpIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import {
  formatToolCallDuration,
  thoughtTimelineDurationMs,
} from '@business/agent/ui/desktop/chat/chatTimelineModel';

/* Web conversation parity 2026-12 (ThinkingBlock): the thought card uses the
   web's Brain glyph. @radix-ui/react-icons ships no brain/lightbulb icon, so
   the lucide "Brain" path set the web renders is inlined here. */
function ThoughtBrainIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" />
      <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" />
      <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" />
      <path d="M17.599 6.5a3 3 0 0 0 .399-1.375" />
      <path d="M6.003 5.125A3 3 0 0 0 6.401 6.5" />
      <path d="M3.477 10.896a4 4 0 0 1 .585-.396" />
      <path d="M19.938 10.5a4 4 0 0 1 .585.396" />
      <path d="M6 18a4 4 0 0 1-1.967-.516" />
      <path d="M19.967 17.484A4 4 0 0 1 18 18" />
    </svg>
  );
}

type ThoughtTimelineCardProps = {
  item: AgentTimelineItem;
  expanded: boolean;
  onToggle: () => void;
};

export function ThoughtTimelineCard({
  item,
  expanded,
  onToggle,
}: ThoughtTimelineCardProps) {
  const { t } = useI18n();
  const contentId = useId();
  const labelId = useId();
  const streaming = Boolean(item.metadata?.streaming);
  /* Web conversation parity 2026-12 (ThinkingBlock): the header carries a
     duration badge (now − start while streaming, end − start once complete),
     ticking once per second during streaming — never a wall-clock time. */
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!streaming) return undefined;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [streaming]);
  const durationMs = thoughtTimelineDurationMs(item, nowMs);
  const duration = durationMs !== null ? formatToolCallDuration(durationMs) : '';
  const content = item.content ?? '';
  const previewContent = content.trim();
  const preview = previewContent
    ? previewContent.slice(0, 100).replace(/\n/g, ' ') + (previewContent.length > 100 ? '…' : '')
    : t('chat.thoughtAnalyzing');

  // Preserve the inner viewport on completion. Removing its height limit
  // would expand a long trace into the transcript and discard its scroll offset.
  const wasStreaming = useRef(streaming);
  useLayoutEffect(() => {
    if (streaming) wasStreaming.current = true;
  }, [streaming]);
  const contentRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);
  const previousScrollTop = useRef(0);
  useLayoutEffect(() => {
    const viewport = contentRef.current;
    if (wasStreaming.current && expanded && followRef.current && viewport) {
      viewport.scrollTop = viewport.scrollHeight;
      previousScrollTop.current = viewport.scrollTop;
    }
  }, [content, expanded, streaming]);

  if (!streaming && !previewContent) return null;

  return (
    <article
      className={`thought-timeline-card${streaming ? ' is-streaming' : ''}`}
      data-timeline-anchor-id={item.id}
      data-live-origin={streaming || wasStreaming.current || undefined}
      aria-busy={streaming}
      tabIndex={-1}
    >
      <span
        className={`thought-timeline-icon${streaming ? ' is-streaming' : ''}`}
        aria-hidden="true"
      >
        <ThoughtBrainIcon />
      </span>
      <div className="thought-timeline-surface">
        <button
          type="button"
          className="thought-timeline-toggle"
          aria-label={t(expanded ? 'chat.collapseItem' : 'chat.expandItem', {
            item: t('chat.thought'),
          })}
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={onToggle}
          onKeyDown={(event) => {
            if (streaming && expanded && event.key === 'Escape') {
              event.stopPropagation();
              onToggle();
            }
          }}
        >
          {streaming && (expanded ? <ChevronDownIcon /> : <ChevronRightIcon />)}
          <span id={labelId} className="thought-timeline-title">
            {t('chat.thought')}
          </span>
          {streaming ? (
            <span className="thought-timeline-streaming-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          ) : null}
          {!expanded && streaming ? (
            <span className="thought-timeline-preview">{preview}</span>
          ) : null}
          {duration ? (
            <span className="thought-timeline-duration">{duration}</span>
          ) : null}
          {!streaming && (
            <span className="thought-history-chevron">
              {expanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
            </span>
          )}
        </button>
        <div
          id={contentId}
          className="thought-timeline-disclosure"
          aria-hidden={!expanded}
          data-expanded={expanded}
          hidden={!expanded && !streaming}
        >
          <div
            ref={contentRef}
            onWheel={(event) => {
              if (event.deltaY < 0 && event.currentTarget.scrollHeight > event.currentTarget.clientHeight) {
                followRef.current = false;
              }
            }}
            onScroll={(event) => {
              const viewport = event.currentTarget;
              if (viewport.scrollTop < previousScrollTop.current) followRef.current = false;
              else if (viewport.scrollTop > previousScrollTop.current) {
                followRef.current = viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop <= 24;
              }
              previousScrollTop.current = viewport.scrollTop;
            }}
            role="region"
            aria-labelledby={labelId}
            className="thought-timeline-content"
          >
            {/* Web parity: reasoning content renders as plain pre-wrap text, not
                italic markdown (ThinkingBlock text-xs whitespace-pre-wrap). */}
            <div className="thought-content">{content}</div>
          </div>
        </div>
      </div>
    </article>
  );
}
