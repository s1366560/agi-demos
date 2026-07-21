/**
 * SubAgentDelegationIndicator Component
 *
 * Shows when the main agent delegates a task to a SubAgent.
 */

import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Tooltip } from 'antd';
import { Bot, Loader2, CheckCircle, XCircle, AtSign, Search, Zap } from 'lucide-react';

import type { TFunction } from 'i18next';

export interface SubAgentDelegationIndicatorProps {
  subagentName: string;
  subagentColor?: string | undefined;
  triggerType: 'keyword' | 'semantic' | 'explicit';
  taskDescription?: string | undefined;
  status: 'started' | 'completed' | 'failed';
}

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

const getTriggerIcon = (triggerType: string) => {
  switch (triggerType) {
    case 'keyword':
      return <Zap size={12} />;
    case 'semantic':
      return <Search size={12} />;
    case 'explicit':
      return <AtSign size={12} />;
    default:
      return <Bot size={12} />;
  }
};

const getTriggerLabel = (triggerType: string, t: TFunction) => {
  switch (triggerType) {
    case 'keyword':
      return tFallback(t, 'agent.subAgentDelegation.keywordMatch', 'Keyword Match');
    case 'semantic':
      return tFallback(t, 'agent.subAgentDelegation.semanticMatch', 'Semantic Match');
    case 'explicit':
      return '@Mention';
    default:
      return tFallback(t, 'agent.subAgentDelegation.delegated', 'Delegated');
  }
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'started':
      return <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />;
    case 'completed':
      return <CheckCircle size={12} className="text-green-500" />;
    case 'failed':
      return <XCircle size={12} className="text-red-500" />;
    default:
      return null;
  }
};

const getStatusLabel = (status: string, t: TFunction) => {
  switch (status) {
    case 'started':
      return tFallback(t, 'agent.subAgentDelegation.statusStarted', 'Started');
    case 'completed':
      return tFallback(t, 'agent.subAgentDelegation.statusCompleted', 'Completed');
    case 'failed':
      return tFallback(t, 'agent.subAgentDelegation.statusFailed', 'Failed');
    default:
      return status;
  }
};

export const SubAgentDelegationIndicator: FC<SubAgentDelegationIndicatorProps> = ({
  subagentName,
  subagentColor,
  triggerType,
  taskDescription,
  status,
}) => {
  const { t } = useTranslation();
  const customColorStyle = subagentColor
    ? {
        color: subagentColor,
        backgroundColor: `color-mix(in srgb, ${subagentColor} 12%, transparent)`,
        borderColor: `color-mix(in srgb, ${subagentColor} 24%, transparent)`,
      }
    : undefined;

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm ${
        subagentColor
          ? ''
          : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800/40 dark:bg-blue-950/20 dark:text-blue-300'
      }`}
      style={customColorStyle}
      data-testid="subagent-delegation-indicator"
    >
      <div className="flex items-center gap-1.5">
        <Bot size={14} />
        <span className="font-medium">{subagentName}</span>
      </div>

      <Tooltip
        title={
          <div className="space-y-1">
            <div>
              <strong>{tFallback(t, 'agent.subAgentDelegation.trigger', 'Trigger')}:</strong>{' '}
              {getTriggerLabel(triggerType, t)}
            </div>
            {taskDescription && (
              <div>
                <strong>{tFallback(t, 'agent.subAgentDelegation.task', 'Task')}:</strong>{' '}
                {taskDescription}
              </div>
            )}
            <div>
              <strong>{tFallback(t, 'agent.subAgentDelegation.status', 'Status')}:</strong>{' '}
              {getStatusLabel(status, t)}
            </div>
          </div>
        }
      >
        <div className="flex items-center gap-1 opacity-70 cursor-help">
          {getTriggerIcon(triggerType)}
          {getStatusIcon(status)}
        </div>
      </Tooltip>
    </div>
  );
};

export default SubAgentDelegationIndicator;
