import { useTranslation } from 'react-i18next';
import { Tooltip } from 'antd';
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Loader2,
  Power,
  PauseCircle,
  type LucideIcon,
} from 'lucide-react';
import type { ProjectAgentLifecycleState } from '../hooks/useUnifiedAgentStatus';

const lifecycleConfig: Record<
  ProjectAgentLifecycleState,
  {
    label: string;
    icon: LucideIcon;
    color: string;
    bgColor: string;
    description: string;
    animate?: boolean | undefined;
  }
> = {
  uninitialized: {
    label: 'agent.lifecycle.states.uninitialized',
    icon: Power,
    color: 'text-slate-600 dark:text-slate-300',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'agent.lifecycle.descriptions.uninitialized',
  },
  initializing: {
    label: 'agent.lifecycle.states.initializing',
    icon: Loader2,
    color: 'text-blue-500',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
    description: 'agent.lifecycle.descriptions.initializing',
    animate: true,
  },
  ready: {
    label: 'agent.lifecycle.states.ready',
    icon: CheckCircle2,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-100 dark:bg-emerald-900/30',
    description: 'agent.lifecycle.descriptions.ready',
  },
  executing: {
    label: 'agent.lifecycle.states.executing',
    icon: Cpu,
    color: 'text-amber-500',
    bgColor: 'bg-amber-100 dark:bg-amber-900/30',
    description: 'agent.lifecycle.descriptions.executing',
    animate: true,
  },
  paused: {
    label: 'agent.lifecycle.states.paused',
    icon: PauseCircle,
    color: 'text-orange-500',
    bgColor: 'bg-orange-100 dark:bg-orange-900/30',
    description: 'agent.lifecycle.descriptions.paused',
  },
  error: {
    label: 'agent.lifecycle.states.error',
    icon: AlertCircle,
    color: 'text-red-500',
    bgColor: 'bg-red-100 dark:bg-red-900/30',
    description: 'agent.lifecycle.descriptions.error',
  },
  shutting_down: {
    label: 'agent.lifecycle.states.shutting_down',
    icon: Power,
    color: 'text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'agent.lifecycle.descriptions.shutting_down',
    animate: true,
  },
};

export function AgentLifecycleBadge({
  lifecycle,
  error,
  activeCalls = 0,
}: {
  lifecycle: ProjectAgentLifecycleState;
  error?: string | null;
  activeCalls?: number;
}) {
  const { t } = useTranslation();
  const config = lifecycleConfig[lifecycle];
  const StatusIcon = config.icon;
  return (
    <Tooltip
      title={
        <div className="space-y-2 max-w-xs">
          <div className="font-medium">{t(config.label)}</div>
          <div className="text-xs opacity-80">{t(config.description)}</div>
          {error && (
            <div className="text-xs text-red-400 pt-1 border-t border-gray-600 mt-1">
              {t('agent.lifecycle.error.prefix')}: {error}
            </div>
          )}
        </div>
      }
    >
      <div
        className={`
                flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium
                ${config.bgColor} ${config.color}
                transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 cursor-help
              `}
      >
        <StatusIcon
          size={12}
          className={config.animate ? 'animate-spin motion-reduce:animate-none' : ''}
        />
        <span className="hidden min-w-0 truncate sm:inline-block">{t(config.label)}</span>
        {activeCalls > 0 ? <span className="ml-0.5">({activeCalls})</span> : null}
      </div>
    </Tooltip>
  );
}
