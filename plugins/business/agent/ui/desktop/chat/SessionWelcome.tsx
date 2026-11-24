import * as React from 'react';
import { ActivityLogIcon } from '@radix-ui/react-icons';

export function SessionWelcome({
  title,
  description,
}: {
  title: string;
  description: string;
}): React.JSX.Element {
  return (
    <div className="chat-empty-state session-conversation-empty" role="status">
      <span aria-hidden="true">
        <ActivityLogIcon />
      </span>
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  );
}
