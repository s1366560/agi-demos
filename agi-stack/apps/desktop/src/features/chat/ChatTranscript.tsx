import { isValidElement, memo, useRef } from 'react';
import type { ReactNode } from 'react';
import {
  ActivityLogIcon,
  ChatBubbleIcon,
  ClockIcon,
  CopyIcon,
  DotsHorizontalIcon,
  DrawingPinIcon,
  FileTextIcon,
  PersonIcon,
  Pencil1Icon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';

import { useI18n } from '../../i18n';
import type { WorkspaceMessage } from '../../types';
import { messageActionsForVisibleMessage } from './chatMessageActionModel';
import type { VisibleMessageKind } from './chatMessageActionModel';
import { AssistantArtifactReferences } from './AssistantArtifactReferences';
import { CodeBlockFrame } from './HighlightedCode';
import {
  MarkdownArtifactImage,
  MarkdownArtifactImageProvider,
} from './MarkdownArtifactImage';
import { MermaidBlock } from './MermaidBlock';
import { MessageForcedSkillBadge } from './MessageForcedSkillBadge';
import {
  formatWorkspaceMessageTime,
  workspaceMessageSenderLabel,
} from './messageIdentityModel';
import { shouldRenderMermaidDiagram } from './mermaidDiagramModel';
import { useMarkdownMathPlugins } from './useMarkdownMathPlugins';

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
  onReply,
  onEdit,
  onDelete,
  onRetry,
  isPinned = false,
  onPin,
  onSaveTemplate,
  retryDisabled = false,
}: {
  message: WorkspaceMessage;
  onReply?: () => void;
  onEdit?: () => void;
  onDelete?: (returnFocus: HTMLElement) => void;
  onRetry?: () => void;
  isPinned?: boolean;
  onPin?: () => void;
  onSaveTemplate?: (returnFocus: HTMLElement) => void;
  retryDisabled?: boolean;
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
      timelineItemId={message.id}
      onReply={onReply}
      onEdit={onEdit}
      onDelete={onDelete}
      onRetry={onRetry}
      isPinned={isPinned}
      onPin={onPin}
      onSaveTemplate={onSaveTemplate}
      retryDisabled={retryDisabled}
    >
      <MarkdownArtifactImageProvider carriers={[message]}>
        <MarkdownContent content={message.content} className="transcript-content" />
      </MarkdownArtifactImageProvider>
      {kind === 'user' ? <MessageForcedSkillBadge message={message} /> : null}
      {kind === 'agent' ? <AssistantArtifactReferences metadata={message.metadata} /> : null}
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
  onReply,
  onEdit,
  onDelete,
  onRetry,
  isPinned = false,
  onPin,
  onSaveTemplate,
  retryDisabled = false,
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
  onReply?: () => void;
  onEdit?: () => void;
  onDelete?: (returnFocus: HTMLElement) => void;
  onRetry?: () => void;
  isPinned?: boolean;
  onPin?: () => void;
  onSaveTemplate?: (returnFocus: HTMLElement) => void;
  retryDisabled?: boolean;
  children: ReactNode;
}) {
  const RoleIcon =
    kind === 'user' ? PersonIcon : kind === 'runtime' ? ActivityLogIcon : ChatBubbleIcon;
  return (
    <article
      className={`message transcript-message session-thread-message ${className} ${kind}${
        streaming ? ' is-streaming' : ''
      }${isPinned ? ' is-pinned' : ''}`}
      data-timeline-anchor-id={timelineItemId}
      tabIndex={-1}
    >
      <span className="session-thread-avatar" aria-hidden="true">
        <RoleIcon />
      </span>
      <div className="session-message-body">
        <header className="transcript-meta">
          <span className="session-message-identity">
            <strong className="session-message-label" title={label}>
              {label}
            </strong>
            {badge ? <span className="session-message-badge">{badge}</span> : null}
            {time ? (
              <time className="session-message-time" title={time}>
                <ClockIcon aria-hidden="true" />
                <span>{time}</span>
              </time>
            ) : null}
          </span>
          <MessageActionMenu
            content={content}
            kind={kind}
            streaming={streaming}
            onReply={onReply}
            onEdit={onEdit}
            onDelete={onDelete}
            onRetry={onRetry}
            isPinned={isPinned}
            onPin={onPin}
            onSaveTemplate={onSaveTemplate}
            retryDisabled={retryDisabled}
          />
        </header>
        <div className="session-message-surface">
          {children}
          {streaming ? <span className="streaming-caret" aria-hidden="true" /> : null}
        </div>
      </div>
    </article>
  );
}

const MARKDOWN_COMPONENTS: Components = {
  // Fenced code blocks render as framed, syntax-highlighted blocks with a
  // copy affordance; inline `code` keeps the default renderer and styling.
  pre: MarkdownPreBlock,
  img: MarkdownArtifactImage,
};

export const MarkdownContent = memo(function MarkdownContent({
  content,
  className,
}: {
  content: string;
  className: string;
}) {
  const { remarkPlugins, rehypePlugins } = useMarkdownMathPlugins(content);
  return (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={MARKDOWN_COMPONENTS}
      >
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
  const code = reactNodeToText(codeProps.children);
  if (shouldRenderMermaidDiagram(language)) return <MermaidBlock chart={code} />;
  return <CodeBlockFrame code={code} language={language} />;
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

function MessageActionMenu({
  content,
  kind,
  streaming,
  onReply,
  onEdit,
  onDelete,
  onRetry,
  isPinned,
  onPin,
  onSaveTemplate,
  retryDisabled,
}: {
  content: string;
  kind: VisibleMessageKind;
  streaming: boolean;
  onReply?: () => void;
  onEdit?: () => void;
  onDelete?: (returnFocus: HTMLElement) => void;
  onRetry?: () => void;
  isPinned: boolean;
  onPin?: () => void;
  onSaveTemplate?: (returnFocus: HTMLElement) => void;
  retryDisabled: boolean;
}) {
  const { t } = useI18n();
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const availability = messageActionsForVisibleMessage(kind, streaming);
  const closeMenu = () => detailsRef.current?.removeAttribute('open');

  const copyContent = () => {
    if (navigator.clipboard) void navigator.clipboard.writeText(content);
    closeMenu();
  };
  const invoke = (action: (() => void) | undefined) => {
    action?.();
    closeMenu();
  };
  const invokeWithReturnFocus = (
    action: ((returnFocus: HTMLElement) => void) | undefined,
    fallback: HTMLButtonElement,
  ) => {
    const returnFocus = detailsRef.current?.querySelector<HTMLElement>('summary') ?? fallback;
    closeMenu();
    action?.(returnFocus);
  };

  return (
    <details className="session-message-actions" ref={detailsRef}>
      <summary aria-label={t('chat.messageActions')} title={t('chat.messageActions')}>
        <DotsHorizontalIcon />
      </summary>
      <div>
        <button type="button" aria-label={t('chat.copyMessage')} onClick={copyContent}>
          <CopyIcon aria-hidden="true" />
          {t('chat.copyMessage')}
        </button>
        {availability.reply && onReply ? (
          <button
            type="button"
            aria-label={t('chat.replyMessage')}
            onClick={() => invoke(onReply)}
          >
            <ChatBubbleIcon aria-hidden="true" />
            {t('chat.replyMessage')}
          </button>
        ) : null}
        {availability.edit && onEdit ? (
          <button
            type="button"
            aria-label={t('chat.editMessage')}
            onClick={() => invoke(onEdit)}
          >
            <Pencil1Icon aria-hidden="true" />
            {t('chat.editMessage')}
          </button>
        ) : null}
        {availability.delete && onDelete ? (
          <button
            type="button"
            aria-label={t('chat.deleteMessage')}
            onClick={(event) => invokeWithReturnFocus(onDelete, event.currentTarget)}
          >
            <TrashIcon aria-hidden="true" />
            {t('chat.deleteMessage')}
          </button>
        ) : null}
        {availability.retry && onRetry ? (
          <button
            type="button"
            aria-label={t('chat.retryMessage')}
            disabled={availability.retryDisabled || retryDisabled}
            onClick={() => invoke(onRetry)}
          >
            <ReloadIcon aria-hidden="true" />
            {t('chat.retryMessage')}
          </button>
        ) : null}
        {kind === 'agent' && onPin ? (
          <button
            type="button"
            aria-label={t(isPinned ? 'chat.unpinMessage' : 'chat.pinMessage')}
            aria-pressed={isPinned}
            onClick={() => invoke(onPin)}
          >
            <DrawingPinIcon aria-hidden="true" />
            {t(isPinned ? 'chat.unpinMessage' : 'chat.pinMessage')}
          </button>
        ) : null}
        {availability.saveTemplate && onSaveTemplate ? (
          <button
            type="button"
            aria-label={t('chat.templates.saveAsTemplate')}
            onClick={(event) => invokeWithReturnFocus(onSaveTemplate, event.currentTarget)}
          >
            <FileTextIcon aria-hidden="true" />
            {t('chat.templates.saveAsTemplate')}
          </button>
        ) : null}
      </div>
    </details>
  );
}

function messageSenderLabel(
  message: WorkspaceMessage,
  t: (key: string) => string,
): string {
  return workspaceMessageSenderLabel(message, {
    agent: t('chat.agent'),
    system: t('chat.system'),
    you: t('chat.you'),
  });
}

function messageKind(message: WorkspaceMessage): 'user' | 'agent' | 'runtime' {
  const sender = (message.sender_type ?? '').toLowerCase();
  if (sender === 'human' || sender === 'user') return 'user';
  if (sender === 'runtime' || sender === 'system') return 'runtime';
  return 'agent';
}

function formatTime(value: string | undefined): string {
  return formatWorkspaceMessageTime(value);
}
