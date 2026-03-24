/**
 * AgentMessageIndicator Component
 *
 * Shows inter-agent message communication in the timeline.
 * Renders a pill showing sender -> receiver with a message preview.
 */

import type { FC } from 'react';

import { Tooltip } from 'antd';
import { ArrowRight, Bot, MessageSquare, Inbox } from 'lucide-react';

export interface AgentMessageIndicatorProps {
  direction: 'sent' | 'received';
  fromAgentName: string;
  toAgentName?: string | undefined;
  messagePreview: string;
}

const SENT_COLOR = '#3B82F6';
const RECEIVED_COLOR = '#8B5CF6';

export const AgentMessageIndicator: FC<AgentMessageIndicatorProps> = ({
  direction,
  fromAgentName,
  toAgentName,
  messagePreview,
}) => {
  const isSent = direction === 'sent';
  const color = isSent ? SENT_COLOR : RECEIVED_COLOR;
  const backgroundColor = `${color}20`;
  const borderColor = `${color}40`;

  return (
    <div
      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm"
      style={{ backgroundColor, borderColor, color }}
      data-testid="agent-message-indicator"
    >
      <div className="flex items-center gap-1.5">
        {isSent ? <MessageSquare size={14} /> : <Inbox size={14} />}
        <span className="font-medium">{fromAgentName}</span>
        {isSent && toAgentName && (
          <>
            <ArrowRight size={12} className="opacity-60" />
            <span className="font-medium">{toAgentName}</span>
          </>
        )}
      </div>

      <Tooltip
        title={
          <div className="space-y-1">
            <div>
              <strong>From:</strong> {fromAgentName}
            </div>
            {toAgentName && (
              <div>
                <strong>To:</strong> {toAgentName}
              </div>
            )}
            <div>
              <strong>Message:</strong> {messagePreview}
            </div>
          </div>
        }
      >
        <div className="flex items-center gap-1 opacity-70 cursor-help text-xs max-w-[200px] truncate">
          <Bot size={12} />
          <span className="truncate">{messagePreview}</span>
        </div>
      </Tooltip>
    </div>
  );
};

export default AgentMessageIndicator;
