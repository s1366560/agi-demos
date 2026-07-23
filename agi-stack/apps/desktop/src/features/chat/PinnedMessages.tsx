import { memo, useId } from 'react';
import {
  ChevronDownIcon,
  ChevronRightIcon,
  Cross2Icon,
  DrawingPinIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { VisibleMessageForRetry } from './chatMessageActionModel';

export const PinnedMessages = memo(function PinnedMessages({
  messages,
  collapsed,
  onCollapsedChange,
  onJump,
  onUnpin,
}: {
  messages: readonly VisibleMessageForRetry[];
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onJump: (message: VisibleMessageForRetry) => void;
  onUnpin: (message: VisibleMessageForRetry) => void;
}) {
  const { t } = useI18n();
  const listId = useId();
  if (messages.length === 0) return null;

  return (
    <section className="chat-pinned-messages" aria-label={t('chat.pinnedMessages')}>
      <button
        type="button"
        className="chat-pinned-messages-toggle"
        aria-expanded={!collapsed}
        aria-controls={listId}
        onClick={() => onCollapsedChange(!collapsed)}
      >
        {collapsed ? (
          <ChevronRightIcon aria-hidden="true" />
        ) : (
          <ChevronDownIcon aria-hidden="true" />
        )}
        <DrawingPinIcon aria-hidden="true" />
        <span>{t('chat.pinnedMessages')}</span>
        <strong>{messages.length}</strong>
      </button>
      <div className="chat-pinned-message-list" id={listId} hidden={collapsed}>
        {messages.map((message) => (
          <div className="chat-pinned-message" key={message.id}>
            <button
              type="button"
              className="chat-pinned-message-jump"
              aria-label={t('chat.jumpToPinnedMessage')}
              onClick={() => onJump(message)}
            >
              <DrawingPinIcon aria-hidden="true" />
              <span>{message.content.trim()}</span>
            </button>
            <button
              type="button"
              className="chat-pinned-message-remove"
              aria-label={t('chat.unpinMessage')}
              title={t('chat.unpinMessage')}
              onClick={() => onUnpin(message)}
            >
              <Cross2Icon aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </section>
  );
});
