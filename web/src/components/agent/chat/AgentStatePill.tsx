/**
 * AgentStatePill - Animated phase indicator for agent execution state
 *
 * Shows current agent state (thinking/acting/observing/idle) with smooth
 * transitions between phases. Displays contextual info like current tool name.
 */

import { memo, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Brain,
  CheckCircle2,
  Eye,
  Loader2,
  MessageCircle,
  RotateCcw,
  Zap,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';


import { useAgentV3Store } from '@/stores/agentV3';

type AgentState =
  | 'idle'
  | 'thinking'
  | 'preparing'
  | 'acting'
  | 'observing'
  | 'awaiting_input'
  | 'retrying';

interface StateConfig {
  icon: React.ReactNode;
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
}

function getStateConfig(
  state: AgentState,
  t: (key: string, fallback: string) => string,
): StateConfig {
  switch (state) {
    case 'thinking':
      return {
        icon: <Brain size={14} className="animate-pulse" />,
        label: t('agent.state.thinking', 'Thinking'),
        color: 'text-violet-600 dark:text-violet-400',
        bgColor: 'bg-violet-50 dark:bg-violet-900/20',
        borderColor: 'border-violet-200 dark:border-violet-800',
      };
    case 'preparing':
      return {
        icon: <Loader2 size={14} className="animate-spin" />,
        label: t('agent.state.preparing', 'Preparing'),
        color: 'text-blue-600 dark:text-blue-400',
        bgColor: 'bg-blue-50 dark:bg-blue-900/20',
        borderColor: 'border-blue-200 dark:border-blue-800',
      };
    case 'acting':
      return {
        icon: <Zap size={14} />,
        label: t('agent.state.acting', 'Executing'),
        color: 'text-amber-600 dark:text-amber-400',
        bgColor: 'bg-amber-50 dark:bg-amber-900/20',
        borderColor: 'border-amber-200 dark:border-amber-800',
      };
    case 'observing':
      return {
        icon: <Eye size={14} />,
        label: t('agent.state.observing', 'Analyzing'),
        color: 'text-emerald-600 dark:text-emerald-400',
        bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
        borderColor: 'border-emerald-200 dark:border-emerald-800',
      };
    case 'awaiting_input':
      return {
        icon: <MessageCircle size={14} className="animate-pulse" />,
        label: t('agent.state.awaitingInput', 'Waiting for input'),
        color: 'text-orange-600 dark:text-orange-400',
        bgColor: 'bg-orange-50 dark:bg-orange-900/20',
        borderColor: 'border-orange-200 dark:border-orange-800',
      };
    case 'retrying':
      return {
        icon: <RotateCcw size={14} className="animate-spin" />,
        label: t('agent.state.retrying', 'Retrying'),
        color: 'text-red-600 dark:text-red-400',
        bgColor: 'bg-red-50 dark:bg-red-900/20',
        borderColor: 'border-red-200 dark:border-red-800',
      };
    default:
      return {
        icon: <CheckCircle2 size={14} />,
        label: t('agent.state.idle', 'Ready'),
        color: 'text-slate-400 dark:text-slate-500',
        bgColor: 'bg-slate-50 dark:bg-slate-800/50',
        borderColor: 'border-slate-200 dark:border-slate-700',
      };
  }
}

interface AgentStatePillProps {
  className?: string;
}

export const AgentStatePill: React.FC<AgentStatePillProps> = memo(({ className = '' }) => {
  const { t } = useTranslation();
  const { isStreaming, agentState, pendingToolsStack } = useAgentV3Store(
    useShallow((s) => ({
      isStreaming: s.isStreaming,
      agentState: s.agentState,
      pendingToolsStack: s.pendingToolsStack,
    })),
  );

  const state = agentState as AgentState;
  const config = useMemo(() => getStateConfig(state, t), [state, t]);
  const currentTool =
    pendingToolsStack.length > 0 ? pendingToolsStack[pendingToolsStack.length - 1] : null;

  // Derive visibility from props — no effect needed
  const visible = isStreaming && state !== 'idle';
  if (!visible) return null;

  const isActingPhase = state === 'acting' || state === 'preparing';
  const isPostThinking = state === 'acting' || state === 'observing';

  return (
    <div
      role="status"
      aria-live="polite"
      className={`
        flex items-center justify-center
        animate-fade-in-up
        ${className}
      `}
    >
      <div
        className={`
          inline-flex items-center gap-2 px-3 py-1.5
          rounded-full border
          ${config.bgColor} ${config.borderColor}
          transition-all duration-300 ease-out
          shadow-sm
        `}
      >
        <span className={`${config.color} transition-colors duration-300`}>{config.icon}</span>
        <span className={`text-xs font-medium ${config.color} transition-colors duration-300`}>
          {config.label}
        </span>
        {currentTool && state === 'acting' && (
          <span className="text-xs text-slate-400 dark:text-slate-500 truncate max-w-[120px]">
            {currentTool}
          </span>
        )}
        {/* Phase progress dots */}
        <div className="flex items-center gap-1 ml-1">
          <PhaseDot active={state === 'thinking'} completed={isPostThinking} />
          <PhaseDot active={isActingPhase} completed={state === 'observing'} />
          <PhaseDot active={state === 'observing'} completed={false} />
        </div>
      </div>
    </div>
  );
});

AgentStatePill.displayName = 'AgentStatePill';

const PhaseDot: React.FC<{ active: boolean; completed: boolean }> = memo(
  ({ active, completed }) => (
    <span
      className={`
      w-1.5 h-1.5 rounded-full transition-all duration-300
      ${active ? 'bg-current scale-125' : completed ? 'bg-current opacity-40' : 'bg-slate-300 dark:bg-slate-600'}
    `}
    />
  ),
);

PhaseDot.displayName = 'PhaseDot';
