/**
 * PlanModeBanner - Modern plan mode indicator banner
 */

import React from 'react';

import { FileText, Eye, X, Beaker, Hammer } from 'lucide-react';

import { LazyButton, LazyTag } from '@/components/ui/lazyAntd';

import type { PlanModeStatus, AgentMode } from '../../types/agent';

interface PlanModeBannerProps {
  status: PlanModeStatus;
  onViewPlan: () => void;
  onExit: () => void;
}

const modeConfig: Record<
  AgentMode,
  {
    icon: React.ReactNode;
    label: string;
    color: string;
    bgColor: string;
    borderColor: string;
    description: string;
  }
> = {
  build: {
    icon: <Hammer size={16} />,
    label: 'Build Mode',
    color: 'text-emerald-600 dark:text-emerald-400',
    bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
    borderColor: 'border-emerald-200 dark:border-emerald-800',
    description: 'Full access to read, write, and execute',
  },
  plan: {
    icon: <FileText size={16} />,
    label: 'Plan Mode',
    color: 'text-blue-600 dark:text-blue-400',
    bgColor: 'bg-blue-50 dark:bg-blue-900/20',
    borderColor: 'border-blue-200 dark:border-blue-800',
    description: 'Read-only with plan editing capabilities',
  },
  explore: {
    icon: <Beaker size={16} />,
    label: 'Explore Mode',
    color: 'text-purple-600 dark:text-purple-400',
    bgColor: 'bg-purple-50 dark:bg-purple-900/20',
    borderColor: 'border-purple-200 dark:border-purple-800',
    description: 'Pure read-only exploration',
  },
};

export const PlanModeBanner: React.FC<PlanModeBannerProps> = ({ status, onViewPlan, onExit }) => {
  const currentMode = status.current_mode || 'plan';
  const config = modeConfig[currentMode];

  return (
    <div
      className={`
      mx-4 mt-4 mb-2 p-4 rounded-xl border
      ${config.bgColor} ${config.borderColor}
      animate-slide-down
    `}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={`
            w-10 h-10 rounded-lg bg-white dark:bg-slate-800 shadow-sm
            flex items-center justify-center
            ${config.color}
          `}
          >
            {config.icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className={`font-semibold ${config.color}`}>{config.label}</h3>
              <LazyTag
                className={`
                ${config.bgColor} ${config.color} border-0
                text-xs font-medium
              `}
              >
                Active
              </LazyTag>
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400">{config.description}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {status.plan && (
            <LazyButton
              type="default"
              size="small"
              icon={<Eye size={14} />}
              onClick={onViewPlan}
              className="flex items-center gap-1"
            >
              View Plan
            </LazyButton>
          )}
          <LazyButton type="primary" danger size="small" icon={<X size={14} />} onClick={onExit}>
            Exit
          </LazyButton>
        </div>
      </div>
    </div>
  );
};
