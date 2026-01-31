/**
 * PlanContent - Plan view content for RightPanel
 *
 * Displays work plans and execution plans with progress tracking.
 * Extracted from RightPanel for better separation of concerns.
 *
 * Features:
 * - Empty state when no plan
 * - Progress bar with percentage
 * - Step list with completion status
 * - Plan mode editor integration
 * - Error handling
 */

import { Empty, Alert, Spin } from 'antd';
import { CheckCircle2, Play, Clock } from 'lucide-react';
import { PlanEditor } from '../PlanEditor';
import { usePlanModeStore } from '@/stores/agent/planModeStore';
import type { WorkPlan } from '@/types/agent';
import type { ExecutionPlan } from '@/types/agent';

export interface PlanContentProps {
  /** Current work plan */
  workPlan: WorkPlan | null;
  /** Current execution plan */
  executionPlan: ExecutionPlan | null;
}

/**
 * Individual plan step component
 */
const PlanStep = ({ step, index, currentStep }: { step: any; index: number; currentStep: number }) => {
  const isCompleted = index < currentStep;
  const isCurrent = index === currentStep;

  return (
    <div
      className={`
        p-3 rounded-xl border transition-all
        ${isCompleted
          ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800'
          : isCurrent
            ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 shadow-sm'
            : 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700'
        }
      `}
    >
      <div className="flex items-start gap-3">
        <div className={`
          w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0
          ${isCompleted
            ? 'bg-emerald-500 text-white'
            : isCurrent
              ? 'bg-blue-500 text-white animate-pulse'
              : 'bg-slate-200 dark:bg-slate-700 text-slate-500'
          }
        `}>
          {isCompleted ? (
            <CheckCircle2 size={14} />
          ) : isCurrent ? (
            <Play size={12} />
          ) : (
            <span className="text-xs">{index + 1}</span>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className={`
            text-sm font-medium
            ${isCompleted
              ? 'text-emerald-700 dark:text-emerald-400'
              : isCurrent
                ? 'text-blue-700 dark:text-blue-400'
                : 'text-slate-600 dark:text-slate-400'
            }
          `}>
            {step.description}
          </p>
          {isCurrent && step.thought_prompt && (
            <p className="text-xs text-slate-500 mt-1">
              {step.thought_prompt}
            </p>
          )}
          {step.expected_output && (
            <p className="text-xs text-slate-400 mt-1">
              Expected: {step.expected_output}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

/**
 * Progress bar component
 */
const ProgressBar = ({ progress }: { progress: number }) => {
  return (
    <div className="mb-6">
      <div className="flex justify-between text-xs text-slate-500 mb-1">
        <span>Progress</span>
        <span>{Math.round(progress)}%</span>
      </div>
      <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-primary rounded-full transition-all duration-500"
          style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
        />
      </div>
    </div>
  );
};

/**
 * Plan meta information display
 */
const PlanMeta = ({ plan }: { plan: WorkPlan | ExecutionPlan }) => {
  return (
    <div className="mt-6 pt-4 border-t border-slate-200 dark:border-slate-700">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>Status: {(plan as any).status || 'active'}</span>
        {(plan as any).created_at && (
          <span className="flex items-center gap-1">
            <Clock size={12} />
            {new Date((plan as any).created_at).toLocaleTimeString()}
          </span>
        )}
      </div>
    </div>
  );
};

/**
 * Main PlanContent component
 */
export const PlanContent = ({ workPlan, executionPlan }: PlanContentProps) => {
  const { planModeStatus, currentPlan, planLoading, planError } = usePlanModeStore();

  // Show error state if plan mode failed
  if (planError && planModeStatus?.is_in_plan_mode) {
    return (
      <div className="p-4">
        <Alert
          type="error"
          message="Plan Mode Error"
          description={planError}
          showIcon
          closable
        />
      </div>
    );
  }

  // Show PlanEditor when in Plan Mode with an active plan
  if (planModeStatus?.is_in_plan_mode && currentPlan) {
    return (
      <PlanEditor
        plan={currentPlan}
        isLoading={planLoading}
        onUpdate={async (content: string) => {
          const { updatePlan } = usePlanModeStore.getState();
          await updatePlan(currentPlan.id, { content });
        }}
        onSubmitForReview={async () => {
          const { submitPlanForReview } = usePlanModeStore.getState();
          await submitPlanForReview(currentPlan.id);
        }}
        onExit={async (approve: boolean, summary?: string) => {
          const conversationId = currentPlan.metadata?.conversation_id as string;
          const { exitPlanMode } = usePlanModeStore.getState();
          await exitPlanMode(conversationId, currentPlan.id, approve, summary);
        }}
      />
    );
  }

  // Show loading spinner when in plan mode but plan not yet loaded
  if (planModeStatus?.is_in_plan_mode && planLoading && !currentPlan) {
    return (
      <div className="p-8 text-center">
        <Spin size="large" />
        <p className="mt-4 text-slate-500">Loading plan...</p>
      </div>
    );
  }

  // Show EmptyState if no plan at all
  if (!workPlan && !executionPlan && !planModeStatus?.is_in_plan_mode) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="No active plan"
        className="mt-8"
      />
    );
  }

  const plan = executionPlan || workPlan;
  const steps = plan?.steps || [];
  const currentStep = (plan as any)?.current_step_index || 0;
  const progress = steps.length > 0 ? ((currentStep) / steps.length) * 100 : 0;

  return (
    <div className="p-4">
      {/* Plan Header */}
      <div className="mb-4">
        <h3 className="font-semibold text-slate-900 dark:text-slate-100">
          {executionPlan ? 'Execution Plan' : 'Work Plan'}
        </h3>
        <p className="text-sm text-slate-500">
          {steps.length} steps • {currentStep} completed
        </p>
      </div>

      {/* Progress Bar */}
      <ProgressBar progress={progress} />

      {/* Steps */}
      <div className="space-y-3">
        {steps.map((step: any, index: number) => (
          <PlanStep
            key={index}
            step={step}
            index={index}
            currentStep={currentStep}
          />
        ))}
      </div>

      {/* Plan Meta Info */}
      {plan && <PlanMeta plan={plan} />}
    </div>
  );
};

export default PlanContent;
