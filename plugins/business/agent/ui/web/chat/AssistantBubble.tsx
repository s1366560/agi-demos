import type { ReactNode } from 'react';
import { Bot } from 'lucide-react';
import {
  ASSISTANT_AVATAR_CLASSES,
  ASSISTANT_BUBBLE_CLASSES,
  MESSAGE_MAX_WIDTH_CLASSES,
} from './styles';

export function AssistantBubble({
  timestamp,
  actions,
  children,
}: {
  timestamp?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="group flex items-start gap-3 pb-1">
      <div className={ASSISTANT_AVATAR_CLASSES}>
        <Bot size={18} className="text-primary" />
      </div>
      <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
        {timestamp}
        <div className="relative">
          <div className={ASSISTANT_BUBBLE_CLASSES}>{children}</div>
          {/* Action bar - appears on hover at top-right */}
          {actions}
        </div>
      </div>
    </div>
  );
}
