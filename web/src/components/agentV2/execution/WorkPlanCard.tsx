/**
 * Work Plan Card
 *
 * Displays the agent's work plan with step-by-step progress.
 */

import { useState } from 'react';
import {
  DownOutlined,
  RightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import { useWorkPlan, useCurrentStepIndex, useStepStatuses } from '../../../stores/agentV2';

interface WorkPlanCardProps {
  variant?: 'full' | 'compact' | 'inline';
}

export function WorkPlanCard({ variant = 'full' }: WorkPlanCardProps) {
  const workPlan = useWorkPlan();
  const currentStepIndex = useCurrentStepIndex();
  const stepStatuses = useStepStatuses();
  const [isExpanded, setIsExpanded] = useState(true);

  if (!workPlan || workPlan.steps.length <= 1) return null;

  const progress = workPlan.steps.length > 0
    ? (Array.from(stepStatuses.values()).filter((s) => s === 'completed').length / workPlan.steps.length) * 100
    : 0;

  return (
    <div className={`mb-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden ${
      variant === 'inline' ? 'border-dashed' : ''
    }`}>
      {/* Header */}
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-900/50 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? <DownOutlined /> : <RightOutlined />}
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">
            Execution Plan
          </h3>
          <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-full">
            {workPlan.steps.length} steps
          </span>
        </div>

        {/* Progress Bar */}
        <div className="flex items-center gap-3">
          <div className="w-32 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-sm text-gray-600 dark:text-gray-400">
            {Math.round(progress)}%
          </span>
        </div>
      </div>

      {/* Steps */}
      {isExpanded && (
        <div className="p-4 space-y-3">
          {workPlan.steps.map((step) => {
            const status = stepStatuses.get(step.step_number) || 'pending';
            const isCurrent = step.step_number === currentStepIndex;

            return (
              <div
                key={step.step_number}
                className={`flex items-start gap-3 p-3 rounded-lg border transition-all ${
                  status === 'running'
                    ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-700'
                    : status === 'completed'
                    ? 'bg-green-50 dark:bg-green-900/20 border-green-300 dark:border-green-700'
                    : status === 'failed'
                    ? 'bg-red-50 dark:bg-red-900/20 border-red-300 dark:border-red-700'
                    : 'bg-gray-50 dark:bg-gray-900/20 border-gray-300 dark:border-gray-700'
                } ${isCurrent ? 'ring-2 ring-blue-500' : ''}`}
              >
                {/* Step Number / Icon */}
                <div className="flex-shrink-0">
                  {status === 'running' ? (
                    <ClockCircleOutlined className="text-blue-500" />
                  ) : status === 'completed' ? (
                    <CheckCircleOutlined className="text-green-500" />
                  ) : status === 'failed' ? (
                    <CloseCircleOutlined className="text-red-500" />
                  ) : (
                    <div className="w-6 h-6 rounded-full bg-gray-300 dark:bg-gray-700 flex items-center justify-center text-xs font-medium text-gray-600 dark:text-gray-400">
                      {step.step_number}
                    </div>
                  )}
                </div>

                {/* Step Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-gray-900 dark:text-gray-100">
                      {step.description}
                    </p>
                    {isCurrent && (
                      <span className="px-2 py-0.5 text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-full animate-pulse">
                        Running
                      </span>
                    )}
                  </div>

                  {/* Required Tools */}
                  {step.required_tools && step.required_tools.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {step.required_tools.map((tool) => (
                        <span
                          key={tool}
                          className="px-2 py-0.5 text-xs bg-gray-200 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded"
                        >
                          {tool}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Expected Output */}
                  {step.expected_output && (
                    <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                      <span className="font-medium">Output:</span> {step.expected_output}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
