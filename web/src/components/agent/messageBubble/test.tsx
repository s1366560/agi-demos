/**
 * Minimal test version of MessageBubble
 */

import React, { memo } from 'react';

const UserMessage: React.FC<{ content: string }> = memo(({ content }) => {
  return <div>{content}</div>;
});

const AssistantMessage: React.FC<{ content: string }> = memo(({ content }) => {
  return <div>{content}</div>;
});

const MessageBubbleRoot: React.FC<{ event: any }> = memo(({ event }) => {
  if (event?.type === 'user_message') {
    return <UserMessage content={event.content || ''} />;
  }
  return <AssistantMessage content={event?.content || ''} />;
});

// Compound component pattern
export const MessageBubble = MessageBubbleRoot as any;
MessageBubble.User = UserMessage;
MessageBubble.Assistant = AssistantMessage;
MessageBubble.Root = MessageBubbleRoot;
