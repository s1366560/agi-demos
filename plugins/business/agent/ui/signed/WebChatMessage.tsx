import { useMemo, type ReactNode } from 'react';
import { Modal } from 'antd';
import { useTranslation } from 'react-i18next';
import { MessageActionBar } from '../../../../../web/src/components/agent/chat/MessageActionBar';
import { normalizeExecutionSummary } from '../../../../../web/src/utils/executionSummary';
import { AssistantBubble } from '../web/chat/AssistantBubble';
import { CodeBlock } from '../web/chat/CodeBlock';
import { MarkdownTable } from '../web/chat/MarkdownTable';
import { MessageFileList } from '../web/chat/MessageFileList';
import { MessageTime } from '../web/chat/MessageTime';
import { UserBubble, UserAvatar } from '../web/chat/UserBubble';
import { quoteMessage, stripSubAgentDelegationPrefix } from '../web/chat/messageDraft';
import { MARKDOWN_PROSE_CLASSES } from '../web/chat/styles';
import { ExecutionSummaryPanel } from '../web/transcript/messageBubble/ExecutionSummaryPanel';
import { Answer } from './ChatTranscriptView';
import type { Chat, Message } from './useChat';

/** The turn a user message opens: what answers it can be folded away, as in the original transcript. */
export interface MessageFold {
  folded: boolean;
  hiddenCount: number;
  onToggle: () => void;
}

interface WebChatMessageProps {
  message: Message;
  chat: Chat;
  refill: (value: string) => void;
  openCode: (text: string, language?: string) => void;
  hide: (id: string) => void;
  pinned?: boolean;
  onPin?: () => void;
  fold?: MessageFold;
}

export function WebChatMessage({message, chat, refill, openCode, hide, pinned, onPin, fold}: WebChatMessageProps) {
  const {t} = useTranslation();
  const user = message.role === 'user_message';
  const components = useMemo(() => ({
    pre: ({children}: {children?: ReactNode}) => <CodeBlock onOpenInCanvas={openCode} copyEnabled>{children}</CodeBlock>,
    table: MarkdownTable,
  }), [openCode]);
  const index = chat.messages.findIndex(row => row.id === message.id);
  const previous = !user && chat.messages.slice(0, index).findLast(row => row.role === 'user_message');
  const writable = chat.writable && !chat.busy;
  const edit = writable && user ? () => refill(stripSubAgentDelegationPrefix(message.content)) : undefined;
  const retry = writable && previous ? () => void chat.send(stripSubAgentDelegationPrefix(previous.content)) : undefined;
  const actions = <div className="absolute -top-3 right-2 z-10">
    <MessageActionBar role={user ? 'user' : 'assistant'} content={message.content}
      onEdit={edit} onReply={writable ? () => refill(quoteMessage(message.content)) : undefined}
      onRetry={retry} isPinned={pinned} onPin={onPin}
      onDelete={user ? () => {
        const excerpt = message.content.length > 80 ? message.content.slice(0, 80) + '…' : message.content;
        Modal.confirm({title: t('agent.actions.deleteMessageTitle', 'Delete this message?'),
          content: t('agent.actions.deleteMessageBody', {excerpt, defaultValue: 'Remove "{{excerpt}}" from this conversation view.'}),
          okText: t('common.delete', 'Delete'), okButtonProps: {danger:true}, cancelText: t('common.cancel', 'Cancel'), onOk: () => hide(message.id)});
      } : undefined}
    />
  </div>;
  const timestamp = message.timestamp || (message.eventTimeUs ? message.eventTimeUs / 1000 : undefined);
  const time = timestamp && <div className={'mb-1 flex ' + (user ? 'justify-end pr-1' : 'pl-1')}><MessageTime timestamp={timestamp} /></div>;
  return user ? (
    <div className="group group/turn relative flex flex-col items-end gap-1 pb-1">
      <div className="flex items-end justify-end gap-3 w-full">
        <div className="max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">{time}
          <div className="relative"><UserBubble content={message.content} />{actions}</div>
        </div>
        <UserAvatar />
      </div>
      {!!message.files?.length && <div className="mr-11 mt-0.5"><MessageFileList files={message.files} /></div>}
      {fold && (
        <button
          type="button"
          onClick={fold.onToggle}
          data-testid="turn-fold-toggle"
          className={`absolute -bottom-1 right-2 inline-flex items-center gap-1 rounded-md border border-slate-200/70 bg-slate-50 px-1.5 py-0.5 text-2xs font-medium text-slate-500 transition-opacity hover:text-slate-800 dark:border-slate-700/60 dark:bg-slate-800 dark:text-slate-400 dark:hover:text-slate-100 ${fold.folded ? 'opacity-100' : 'opacity-0 group-hover/turn:opacity-100 focus:opacity-100'}`}
          aria-label={fold.folded ? t('agent.actions.expandTurn', 'Expand turn') : t('agent.actions.collapseTurn', 'Collapse turn')}
        >
          {fold.folded
            ? t('agent.actions.expandTurnWithCount', 'Expand ({{count}})', {count: fold.hiddenCount})
            : t('agent.actions.collapseTurn', 'Collapse turn')}
        </button>
      )}
    </div>
  ) : (
    <AssistantBubble timestamp={time} actions={chat.run && index === chat.messages.length - 1 ? null : actions}>
      <ExecutionSummaryPanel summary={normalizeExecutionSummary(message.summary)} />
      <div className={MARKDOWN_PROSE_CLASSES}><Answer components={components} text={message.content} /></div>
    </AssistantBubble>
  );
}
