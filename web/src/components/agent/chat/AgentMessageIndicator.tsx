/**
 * AgentMessageIndicator Component
 *
 * Shows inter-agent message communication in the timeline.
 * Renders a pill showing sender -> receiver with a message preview.
 */

import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Tooltip } from 'antd';
import { ArrowRight, Bot, MessageSquare, Inbox } from 'lucide-react';

export interface AgentMessageIndicatorProps {
  direction: 'sent' | 'received';
  fromAgentName: string;
  toAgentName?: string | undefined;
  messagePreview: string;
}

const directionClasses = {
  sent: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800/40 dark:bg-blue-950/20 dark:text-blue-300',
  received:
    'border-teal-200 bg-teal-50 text-teal-700 dark:border-teal-800/40 dark:bg-teal-950/20 dark:text-teal-300',
} as const;

export const AgentMessageIndicator: FC<AgentMessageIndicatorProps> = ({
  direction,
  fromAgentName,
  toAgentName,
  messagePreview,
}) => {
  const { t } = useTranslation();
  const isSent = direction === 'sent';

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm ${directionClasses[direction]}`}
      data-testid="agent-message-indicator"
    >
      <div className="flex items-center gap-1.5">
        {isSent ? (
          <MessageSquare size={14} aria-hidden="true" />
        ) : (
          <Inbox size={14} aria-hidden="true" />
        )}
        <span className="sr-only">
          {isSent
            ? t('agent.agentMessageIndicator.directionSent', { defaultValue: 'Sent' })
            : t('agent.agentMessageIndicator.directionReceived', { defaultValue: 'Received' })}
        </span>
        <span className="font-medium">{fromAgentName}</span>
        {isSent && toAgentName && (
          <>
            <ArrowRight size={12} className="opacity-60" aria-hidden="true" />
            <span className="font-medium">{toAgentName}</span>
          </>
        )}
      </div>

      <Tooltip
        title={
          <div className="space-y-1">
            <div>
              <strong>{t('agent.agentMessageIndicator.from')}:</strong> {fromAgentName}
            </div>
            {toAgentName && (
              <div>
                <strong>{t('agent.agentMessageIndicator.to')}:</strong> {toAgentName}
              </div>
            )}
            <div>
              <strong>{t('agent.agentMessageIndicator.message')}:</strong> {messagePreview}
            </div>
          </div>
        }
      >
        <div className="flex items-center gap-1 opacity-70 cursor-help text-xs max-w-50 truncate">
          <Bot size={12} aria-hidden="true" />
          <span className="truncate">{messagePreview}</span>
        </div>
      </Tooltip>
    </div>
  );
};

export default AgentMessageIndicator;
