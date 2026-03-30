import { memo } from 'react';

import { Bot } from 'lucide-react';
/**
 * TextItems - Streaming text delta and text end event rendering
 */


import {
  ASSISTANT_AVATAR_CLASSES,
  ASSISTANT_BUBBLE_CLASSES,
  MARKDOWN_PROSE_CLASSES,
} from '../styles';

import { MarkdownWithSuspense, TimeBadge } from './shared';

import type { TimelineEvent } from '../../../types/agent';

interface TextDeltaItemProps {
  event: TimelineEvent;
}

export const TextDeltaItem = memo(
  function TextDeltaItem({ event }: TextDeltaItemProps) {
    if (event.type !== 'text_delta') return null;

    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-start gap-3 my-3.5">
          <div className={ASSISTANT_AVATAR_CLASSES}>
            <Bot size={18} className="text-primary" />
          </div>
          <div
            className={`${ASSISTANT_BUBBLE_CLASSES} ${MARKDOWN_PROSE_CLASSES} break-words [overflow-wrap:anywhere]`}
          >
            <MarkdownWithSuspense>{event.content}</MarkdownWithSuspense>
          </div>
        </div>
        <div className="pl-11">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return (
      prev.event.id === next.event.id &&
      prev.event.type === next.event.type &&
      (prev.event.type === 'text_delta' && next.event.type === 'text_delta'
        ? prev.event.content === next.event.content
        : true)
    );
  }
);

interface TextEndItemProps {
  event: TimelineEvent;
}

export const TextEndItem = memo(
  function TextEndItem({ event }: TextEndItemProps) {
    if (event.type !== 'text_end') return null;

    const fullText = event.fullText || '';
    if (!fullText || !fullText.trim()) return null;

    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-start gap-3 my-3.5">
          <div className={ASSISTANT_AVATAR_CLASSES}>
            <Bot size={18} className="text-primary" />
          </div>
          <div
            className={`${ASSISTANT_BUBBLE_CLASSES} ${MARKDOWN_PROSE_CLASSES} break-words [overflow-wrap:anywhere]`}
          >
            <MarkdownWithSuspense>{fullText}</MarkdownWithSuspense>
          </div>
        </div>
        <div className="pl-11">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return (
      prev.event.id === next.event.id &&
      prev.event.type === next.event.type &&
      (prev.event.type === 'text_end' && next.event.type === 'text_end'
        ? prev.event.fullText === next.event.fullText
        : true)
    );
  }
);
