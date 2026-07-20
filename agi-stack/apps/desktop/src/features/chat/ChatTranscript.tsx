import { isValidElement, memo, useRef } from 'react';
import type { ReactNode } from 'react';
import {
  ActivityLogIcon,
  CodeIcon,
  CopyIcon,
  DotsHorizontalIcon,
  PersonIcon,
} from '@radix-ui/react-icons';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useI18n } from '../../i18n';
import type { WorkspaceMessage } from '../../types';
import { CodeBlockFrame } from './HighlightedCode';

export function SessionEmptyState() {
  const { t } = useI18n();
  return (
    <div className="chat-empty-state session-conversation-empty" role="status">
      <span aria-hidden="true">
        <ActivityLogIcon />
      </span>
      <strong>{t('session.emptyTitle')}</strong>
      <p>{t('session.emptyDescription')}</p>
    </div>
  );
}

// Memoized on message identity (stable in `dataset.messages`): any ChatPanel
// re-render — e.g. every rAF-batched socket flush during streaming — used to
// reconcile the entire transcript; now unchanged rows bail out immediately.
export const WorkspaceTranscriptMessage = memo(function WorkspaceTranscriptMessage({
  message,
}: {
  message: WorkspaceMessage;
}) {
  const { t } = useI18n();
  const kind = messageKind(message);
  return (
    <NarrativeMessageFrame
      kind={kind}
      label={messageSenderLabel(message, t)}
      time={formatTime(message.created_at)}
      content={message.content}
      badge={
        message.mentions?.length
          ? t('chat.mentionCount', { count: message.mentions.length })
          : kind === 'agent'
            ? t('session.workspaceAgent')
            : null
      }
      className="workspace-message"
    >
      <MarkdownContent content={message.content} className="transcript-content" />
    </NarrativeMessageFrame>
  );
});

export function NarrativeMessageFrame({
  kind,
  label,
  time,
  content,
  badge,
  className,
  timelineItemId,
  streaming = false,
  children,
}: {
  kind: 'user' | 'agent' | 'runtime';
  label: string;
  time: string;
  content: string;
  badge: string | null;
  className: string;
  timelineItemId?: string;
  streaming?: boolean;
  children: ReactNode;
}) {
  return (
    <article
      className={`message transcript-message session-thread-message ${className} ${kind}${
        streaming ? ' is-streaming' : ''
      }`}
      data-timeline-anchor-id={timelineItemId}
    >
      <span className="session-thread-avatar" aria-hidden="true">
        {kind === 'user' ? (
          <PersonIcon />
        ) : kind === 'agent' ? (
          <CodeIcon />
        ) : (
          <ActivityLogIcon />
        )}
      </span>
      <div className="session-message-body">
        <header className="transcript-meta">
          <span className="transcript-author">
            <strong>{label}</strong>
            {badge ? <em>{badge}</em> : null}
          </span>
          <time>{time}</time>
          <MessageActionMenu content={content} />
        </header>
        {children}
        {streaming ? <span className="streaming-caret" aria-hidden="true" /> : null}
      </div>
    </article>
  );
}

const REMARK_PLUGINS = [remarkGfm];

const MARKDOWN_COMPONENTS: Components = {
  // Fenced code blocks render as framed, syntax-highlighted blocks with a
  // copy affordance; inline `code` keeps the default renderer and styling.
  pre: MarkdownPreBlock,
};

export const MarkdownContent = memo(function MarkdownContent({
  content,
  className,
}: {
  content: string;
  className: string;
}) {
  return (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={MARKDOWN_COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  );
});

function MarkdownPreBlock({ children }: { children?: ReactNode }) {
  const codeElement = isValidElement(children) ? children : null;
  const codeProps = (codeElement?.props ?? {}) as {
    className?: unknown;
    children?: ReactNode;
  };
  const className = typeof codeProps.className === 'string' ? codeProps.className : '';
  const language = /language-([\w-]+)/.exec(className)?.[1] ?? 'text';
  return <CodeBlockFrame code={reactNodeToText(codeProps.children)} language={language} />;
}

function reactNodeToText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(reactNodeToText).join('');
  if (isValidElement(node)) {
    return reactNodeToText((node.props as { children?: ReactNode }).children);
  }
  return '';
}

function MessageActionMenu({ content }: { content: string }) {
  const { t } = useI18n();
  const detailsRef = useRef<HTMLDetailsElement>(null);

  const copyContent = () => {
    if (navigator.clipboard) void navigator.clipboard.writeText(content);
    detailsRef.current?.removeAttribute('open');
  };

  return (
    <details className="session-message-actions" ref={detailsRef}>
      <summary aria-label={t('chat.messageActions')} title={t('chat.messageActions')}>
        <DotsHorizontalIcon />
      </summary>
      <div>
        <button type="button" onClick={copyContent}>
          <CopyIcon aria-hidden="true" />
          {t('chat.copyMessage')}
        </button>
      </div>
    </details>
  );
}

function messageSenderLabel(
  message: WorkspaceMessage,
  t: (key: string) => string,
): string {
  const sender = (message.sender_type ?? '').toLowerCase();
  if (sender === 'human' || sender === 'user') return t('chat.you');
  if (sender === 'runtime' || sender === 'system') return t('chat.system');
  return message.sender_type ?? t('chat.agent');
}

function messageKind(message: WorkspaceMessage): 'user' | 'agent' | 'runtime' {
  const sender = (message.sender_type ?? '').toLowerCase();
  if (sender === 'human' || sender === 'user') return 'user';
  if (sender === 'runtime' || sender === 'system') return 'runtime';
  return 'agent';
}

function formatTime(value: string | undefined): string {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
