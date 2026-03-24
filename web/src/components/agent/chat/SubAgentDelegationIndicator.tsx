/**
 * SubAgentDelegationIndicator Component
 *
 * Shows when the main agent delegates a task to a SubAgent.
 */

import type { FC } from 'react';

import { Tooltip } from 'antd';
import { Bot, Loader2, CheckCircle, XCircle, AtSign, Search, Zap } from 'lucide-react';

export interface SubAgentDelegationIndicatorProps {
  subagentName: string;
  subagentColor?: string | undefined;
  triggerType: 'keyword' | 'semantic' | 'explicit';
  taskDescription?: string | undefined;
  status: 'started' | 'completed' | 'failed';
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

const getTriggerLabel = (triggerType: string) => {
  switch (triggerType) {
    case 'keyword':
      return 'Keyword Match';
    case 'semantic':
      return 'Semantic Match';
    case 'explicit':
      return '@Mention';
    default:
      return 'Delegated';
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

export const SubAgentDelegationIndicator: FC<SubAgentDelegationIndicatorProps> = ({
  subagentName,
  subagentColor = '#8B5CF6',
  triggerType,
  taskDescription,
  status,
}) => {
  const backgroundColor = `${subagentColor}20`;
  const borderColor = `${subagentColor}40`;

  return (
    <div
      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm"
      style={{
        backgroundColor,
        borderColor,
        color: subagentColor,
      }}
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
              <strong>Trigger:</strong> {getTriggerLabel(triggerType)}
            </div>
            {taskDescription && (
              <div>
                <strong>Task:</strong> {taskDescription}
              </div>
            )}
            <div>
              <strong>Status:</strong> {status}
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
