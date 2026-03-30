import type { FC } from 'react';

import { Zap, Brain, Loader2, Eye, MessageCircle, RotateCcw, CheckCircle2 } from 'lucide-react';

import type { TFunction } from 'i18next';
import type { LucideIcon } from 'lucide-react';

export type AgentExecState =
  | 'idle'
  | 'thinking'
  | 'preparing'
  | 'acting'
  | 'observing'
  | 'awaiting_input'
  | 'retrying';

export interface ExecStateConfig {
  icon: LucideIcon;
  iconAnimate: string;
  color: string;
  bgColor: string;
  borderColor: string;
}

export const execStateConfig: Record<AgentExecState, ExecStateConfig> = {
  thinking: {
    icon: Brain,
    iconAnimate: 'animate-pulse motion-reduce:animate-none',
    color: 'text-status-text-muted dark:text-status-text-muted-dark',
    bgColor: 'bg-surface-alt dark:bg-surface-dark-alt/50',
    borderColor: 'border-border-light dark:border-border-dark',
  },
  preparing: {
    icon: Loader2,
    iconAnimate: 'animate-spin motion-reduce:animate-none',
    color: 'text-status-text-info dark:text-status-text-info-dark',
    bgColor: 'bg-info-bg dark:bg-info-bg-dark',
    borderColor: 'border-info-border dark:border-info-border-dark',
  },
  acting: {
    icon: Zap,
    iconAnimate: '',
    color: 'text-status-text-info dark:text-status-text-info-dark',
    bgColor: 'bg-info-bg dark:bg-info-bg-dark',
    borderColor: 'border-info-border dark:border-info-border-dark',
  },
  observing: {
    icon: Eye,
    iconAnimate: '',
    color: 'text-status-text-success dark:text-status-text-success-dark',
    bgColor: 'bg-success-bg dark:bg-success-bg-dark',
    borderColor: 'border-success-border dark:border-success-border-dark',
  },
  awaiting_input: {
    icon: MessageCircle,
    iconAnimate: 'animate-pulse motion-reduce:animate-none',
    color: 'text-status-text-muted dark:text-status-text-muted-dark',
    bgColor: 'bg-surface-alt dark:bg-surface-dark-alt/50',
    borderColor: 'border-border-light dark:border-border-dark',
  },
  retrying: {
    icon: RotateCcw,
    iconAnimate: 'animate-spin motion-reduce:animate-none',
    color: 'text-status-text-error dark:text-status-text-error-dark',
    bgColor: 'bg-error-bg dark:bg-error-bg-dark',
    borderColor: 'border-error-border dark:border-error-border-dark',
  },
  idle: {
    icon: CheckCircle2,
    iconAnimate: '',
    color: 'text-text-muted dark:text-text-muted',
    bgColor: 'bg-surface-alt dark:bg-surface-dark-alt/50',
    borderColor: 'border-border-light dark:border-border-dark',
  },
};

/**
 * Status bar phase dot
 */
export const StatusPhaseDot: FC<{ active: boolean; completed: boolean }> = ({ active, completed }) => (
  <span
    className={`
      w-1.5 h-1.5 rounded-full transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300
      ${active ? 'bg-current scale-125' : completed ? 'bg-current opacity-40' : 'bg-border-separator dark:bg-border-separator-dark'}
    `}
  />
);

export interface AgentExecStatePillProps {
  agentState: AgentExecState;
  execConfig: ExecStateConfig;
  currentTool: string | null;
  isActingPhase: boolean;
  isPostThinking: boolean;
  t: TFunction;
}

export const AgentExecStatePill: FC<AgentExecStatePillProps> = ({
  agentState,
  execConfig,
  currentTool,
  isActingPhase,
  isPostThinking,
  t,
}) => {
  return (
    <div
      className={`
        flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
        ${execConfig.bgColor} ${execConfig.color} border ${execConfig.borderColor}
        transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300
      `}
    >
      <execConfig.icon size={12} className={execConfig.iconAnimate} />
      <span className="hidden sm:inline">{t(`agent.state.${agentState}`, agentState)}</span>
      {currentTool && agentState === 'acting' && (
        <span className="text-xs opacity-60 truncate max-w-[80px] hidden sm:inline">
          {currentTool}
        </span>
      )}
      {/* Phase progress dots */}
      <div className="flex items-center gap-0.5 ml-0.5">
        <StatusPhaseDot active={agentState === 'thinking'} completed={isPostThinking} />
        <StatusPhaseDot active={isActingPhase} completed={agentState === 'observing'} />
        <StatusPhaseDot active={agentState === 'observing'} completed={false} />
      </div>
    </div>
  );
};
