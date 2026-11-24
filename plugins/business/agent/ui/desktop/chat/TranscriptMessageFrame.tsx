import * as React from 'react';
import type { ReactNode } from 'react';

export function TranscriptMessageFrame({
  kind,
  label,
  time,
  badge,
  className,
  timelineItemId,
  streaming = false,
  isPinned = false,
  actions,
  children,
}: {
  kind: 'agent' | 'user' | 'runtime';
  label?: string | undefined;
  time?: string | undefined;
  badge?: string | null | undefined;
  className: string;
  timelineItemId?: string | undefined;
  streaming?: boolean;
  isPinned?: boolean;
  actions?: ReactNode;
  children: ReactNode;
}): React.JSX.Element {
  return (
    <article
      className={`message transcript-message session-thread-message ${className} ${kind}${
        streaming ? ' is-streaming' : ''
      }${isPinned ? ' is-pinned' : ''}`}
      data-timeline-anchor-id={timelineItemId}
      tabIndex={-1}
      data-has-identity={Boolean(label || badge)}
    >
      <div className="session-message-body">
        <header className="transcript-meta">
          <span className="session-message-identity">
            {label ? (
              <strong className="session-message-label" title={label}>
                {label}
              </strong>
            ) : null}
            {badge ? <span className="session-message-badge">{badge}</span> : null}
            {time ? (
              <time className="session-message-time" title={time}>
                <span>{time}</span>
              </time>
            ) : null}
          </span>
          {actions}
        </header>
        <div className="session-message-surface">{children}</div>
      </div>
    </article>
  );
}
