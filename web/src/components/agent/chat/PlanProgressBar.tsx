/**
 * PlanProgressBar - Compact inline progress indicator for multi-step plans
 *
 * Shows current step / total steps with a segmented progress bar.
 * Appears in the message stream when agent is executing a work plan.
 */

import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { CheckCircle2, Circle, Loader2, ListChecks } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';


import { useAgentV3Store } from '@/stores/agentV3';

import type { PlanStatus } from '@/types/agent';

interface PlanProgressBarProps {
  className?: string;
}

export const PlanProgressBar: React.FC<PlanProgressBarProps> = memo(({ className = '' }) => {
  const { t } = useTranslation();
  const { workPlan, isStreaming } = useAgentV3Store(
    useShallow((s) => ({
      workPlan: s.workPlan,
      isStreaming: s.isStreaming,
    }))
  );

  if (!workPlan || workPlan.steps.length === 0) return null;
  if (workPlan.status === 'completed' && !isStreaming) return null;

  const { steps, current_step_index: currentStep, status } = workPlan;
  const totalSteps = steps.length;
  const currentStepDescription = steps[currentStep]?.description || '';

  return (
    <div
      role="progressbar"
      aria-valuenow={currentStep + 1}
      aria-valuemin={1}
      aria-valuemax={totalSteps}
      aria-label={`Step ${currentStep + 1} of ${totalSteps}: ${currentStepDescription}`}
      className={`
        flex items-center gap-3 px-4 py-2.5
        bg-slate-50 dark:bg-slate-800/60
        border border-slate-200/80 dark:border-slate-700/50
        rounded-xl
        animate-fade-in-up
        ${className}
      `}
    >
      <ListChecks size={16} className="text-primary flex-shrink-0" />

      <div className="flex-1 min-w-0">
        {/* Step label */}
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
            {t('agent.plan.step', 'Step')} {currentStep + 1} / {totalSteps}
          </span>
          <StatusBadge status={status} t={t} />
        </div>

        {/* Segmented progress bar */}
        <div className="flex gap-0.5">
          {steps.map((_, i) => (
            <div
              key={i}
              className={`
                h-1.5 flex-1 rounded-full transition-all duration-500 ease-out
                ${i < currentStep
                  ? 'bg-emerald-500'
                  : i === currentStep
                    ? status === 'failed'
                      ? 'bg-red-400'
                      : 'bg-primary animate-pulse'
                    : 'bg-slate-200 dark:bg-slate-600'
                }
              `}
            />
          ))}
        </div>

        {/* Current step description */}
        {currentStepDescription && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1.5 truncate">
            {currentStepDescription}
          </p>
        )}
      </div>
    </div>
  );
});

PlanProgressBar.displayName = 'PlanProgressBar';

const StatusBadge: React.FC<{
  status: PlanStatus;
  t: (key: string, fallback: string) => string;
}> = memo(({ status, t }) => {
  switch (status) {
    case 'in_progress':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
          <Loader2 size={10} className="animate-spin" />
          {t('agent.plan.inProgress', 'In progress')}
        </span>
      );
    case 'completed':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 size={10} />
          {t('agent.plan.completed', 'Complete')}
        </span>
      );
    case 'failed':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-red-600 dark:text-red-400">
          <Circle size={10} />
          {t('agent.plan.failed', 'Failed')}
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
          <Circle size={10} />
          {t('agent.plan.planning', 'Planning')}
        </span>
      );
  }
});

StatusBadge.displayName = 'StatusBadge';
