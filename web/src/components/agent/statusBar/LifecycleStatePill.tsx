import type { FC } from 'react';

import { Loader2, CheckCircle2, AlertCircle, PauseCircle, Power, Cpu } from 'lucide-react';

import type { InstanceStatus } from '@/services/poolService';

import type { ProjectAgentLifecycleState, UnifiedAgentStatus as AgentStatus } from '@/hooks/useUnifiedAgentStatus';

import { LazyTooltip } from '@/components/ui/lazyAntd';


import type { TFunction } from 'i18next';
import type { LucideIcon } from 'lucide-react';

/**
 * Map pool instance status to lifecycle state
 */
export function mapPoolStatusToLifecycle(status: InstanceStatus | undefined): ProjectAgentLifecycleState {
  if (!status) return 'uninitialized';

  switch (status) {
    case 'created':
    case 'initializing':
      return 'initializing';
    case 'initialization_failed':
    case 'unhealthy':
    case 'degraded':
      return 'error';
    case 'ready':
      return 'ready';
    case 'executing':
      return 'executing';
    case 'paused':
      return 'paused';
    case 'terminating':
      return 'shutting_down';
    case 'terminated':
      return 'uninitialized';
    default:
      return 'uninitialized';
  }
}

/**
 * Lifecycle state configuration
 */
export const lifecycleConfig: Record<
  ProjectAgentLifecycleState,
  {
    icon: LucideIcon;
    color: string;
    bgColor: string;
    animate?: boolean | undefined;
  }
> = {
  uninitialized: {
    icon: Power,
    color: 'text-text-muted',
    bgColor: 'bg-surface-alt dark:bg-surface-dark-alt',
  },
  initializing: {
    icon: Loader2,
    color: 'text-info',
    bgColor: 'bg-info-bg dark:bg-info-bg-dark',
    animate: true,
  },
  ready: {
    icon: CheckCircle2,
    color: 'text-success',
    bgColor: 'bg-success-bg dark:bg-success-bg-dark',
  },
  executing: {
    icon: Cpu,
    color: 'text-warning',
    bgColor: 'bg-warning-bg dark:bg-warning-bg-dark',
    animate: true,
  },
  paused: {
    icon: PauseCircle,
    color: 'text-caution',
    bgColor: 'bg-caution-bg dark:bg-caution-bg-dark',
  },
  error: {
    icon: AlertCircle,
    color: 'text-error',
    bgColor: 'bg-error-bg dark:bg-error-bg-dark',
  },
  shutting_down: {
    icon: Power,
    color: 'text-text-muted',
    bgColor: 'bg-surface-alt dark:bg-surface-dark-alt',
    animate: true,
  },
};

export interface LifecycleStatePillProps {
  lifecycleState: ProjectAgentLifecycleState;
  config: {
    icon: LucideIcon;
    color: string;
    bgColor: string;
    animate?: boolean | undefined;
  };
  status: AgentStatus;
  error: string | null;
  t: TFunction;
}

export const LifecycleStatePill: FC<LifecycleStatePillProps> = ({
  lifecycleState,
  config,
  status,
  error,
  t,
}) => {
  const StatusIcon = config.icon;

  return (
    <LazyTooltip
      title={
        <div className="space-y-2 max-w-xs">
          <div className="font-medium">{t(`agent.lifecycle.states.${lifecycleState}`)}</div>
          <div className="text-xs opacity-80">{t(`agent.lifecycle.descriptions.${lifecycleState}`)}</div>
          {error && (
            <div className="text-xs text-status-text-error-dark pt-1 border-t border-border-dark mt-1">
              {t('agent.lifecycle.error.prefix')}: {error}
            </div>
          )}
        </div>
      }
    >
      <div
        className={`
          flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
          ${config.bgColor} ${config.color}
          transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 cursor-help
        `}
      >
        <StatusIcon
          size={12}
          className={config.animate ? 'animate-spin motion-reduce:animate-none' : ''}
        />
        <span className="hidden sm:inline">{t(`agent.lifecycle.states.${lifecycleState}`)}</span>
        {status.resources.activeCalls > 0 ? (
          <span className="ml-0.5">({status.resources.activeCalls})</span>
        ) : null}
      </div>
    </LazyTooltip>
  );
};
