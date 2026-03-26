/**
 * StatusBadge - Reusable status indicator component
 *
 * Displays status with consistent styling across the application.
 * Supports multiple variants for different use cases.
 *
 * @example
 * <StatusBadge status="running" label="Processing" />
 * <StatusBadge status="success" label="Complete" duration={1234} />
 * <StatusBadge status="error" label="Failed" />
 */

import { memo } from 'react';

import { CheckCircle2, Circle, Loader2, AlertCircle, AlertTriangle } from 'lucide-react';

export type StatusBadgeStatus = 'running' | 'success' | 'error' | 'warning' | 'idle';

export interface StatusBadgeProps {
  /** Status variant */
  status: StatusBadgeStatus;
  /** Optional custom label (defaults to status) */
  label?: string | undefined;
  /** Optional duration in ms to display */
  duration?: number | undefined;
  /** Size variant */
  size?: 'sm' | 'md' | undefined;
  /** Additional className */
  className?: string | undefined;
  /** Show animated pulse for running state */
  animate?: boolean | undefined;
}

const VARIANT_CONFIG = {
  running: {
    icon: Loader2,
    bgColor: 'bg-blue-50 dark:bg-blue-500/10',
    textColor: 'text-blue-600 dark:text-blue-400',
    dotColor: 'bg-blue-500',
    animate: true,
  },
  success: {
    icon: CheckCircle2,
    bgColor: 'bg-emerald-50 dark:bg-emerald-500/10',
    textColor: 'text-emerald-600 dark:text-emerald-400',
    dotColor: 'bg-emerald-500',
    animate: false,
  },
  error: {
    icon: AlertCircle,
    bgColor: 'bg-red-50 dark:bg-red-500/10',
    textColor: 'text-red-600 dark:text-red-400',
    dotColor: 'bg-red-500',
    animate: false,
  },
  warning: {
    icon: AlertTriangle,
    bgColor: 'bg-amber-50 dark:bg-amber-500/10',
    textColor: 'text-amber-600 dark:text-amber-400',
    dotColor: 'bg-amber-500',
    animate: false,
  },
  idle: {
    icon: Circle,
    bgColor: 'bg-slate-50 dark:bg-slate-500/10',
    textColor: 'text-slate-500 dark:text-slate-400',
    dotColor: 'bg-slate-400',
    animate: false,
  },
} as const;

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

export const StatusBadge: React.FC<StatusBadgeProps> = memo(
  ({ status, label, duration, size = 'sm', className = '', animate = true }) => {
    const config = VARIANT_CONFIG[status];
    const Icon = config.icon;
    const showAnimation = animate && config.animate;

    const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-3 py-1 text-xs';

    return (
      <span
        className={`
          inline-flex items-center gap-1.5 rounded-full
          ${config.bgColor} ${config.textColor}
          font-bold uppercase tracking-wider
          ${sizeClasses}
          ${className}
        `}
        role="status"
      >
        {showAnimation ? (
          <span
            className={`w-1.5 h-1.5 rounded-full ${config.dotColor} animate-pulse motion-reduce:animate-none`}
          />
        ) : (
          <Icon
            size={size === 'sm' ? 11 : 14}
            className={showAnimation ? 'animate-spin motion-reduce:animate-none' : ''}
          />
        )}
        <span>{label ?? status}</span>
        {duration !== undefined && status === 'success' && (
          <span className="ml-0.5 opacity-70">({formatDuration(duration)})</span>
        )}
      </span>
    );
  }
);

StatusBadge.displayName = 'StatusBadge';
