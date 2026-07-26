import { useId } from 'react';
import {
  ChevronDownIcon,
  ChevronRightIcon,
  StarIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import { formatTimelineTime } from './chatTimelinePresentation';
import { MarkdownContent } from './ChatTranscript';

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
  const time = formatTimelineTime(item);
  const content = item.content ?? '';

  return (
    <article
      className={`thought-timeline-card${streaming ? ' is-streaming' : ''}`}
      data-timeline-anchor-id={item.id}
      aria-busy={streaming}
      tabIndex={-1}
    >
      <span
        className={`thought-timeline-icon${streaming ? ' is-streaming' : ''}`}
        aria-hidden="true"
      >
        <StarIcon />
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
        >
          {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
          <span id={labelId} className="thought-timeline-title">
            {t('chat.thought')}
          </span>
          {streaming ? (
            <>
              <span className="thought-timeline-live">{t('session.live')}</span>
              <span className="thought-timeline-streaming-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
            </>
          ) : null}
          {!expanded && content ? (
            <span className="thought-timeline-preview">{content}</span>
          ) : null}
          {time ? <time className="thought-timeline-time">{time}</time> : null}
        </button>
        <div
          id={contentId}
          role="region"
          aria-labelledby={labelId}
          className="thought-timeline-content"
          hidden={!expanded}
        >
          <MarkdownContent
            content={item.content ?? ''}
            className="transcript-content thought-content"
          />
        </div>
      </div>
    </article>
  );
}
