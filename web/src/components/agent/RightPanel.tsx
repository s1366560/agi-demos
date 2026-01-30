/**
 * RightPanel - Modern side panel combining Plans and Sandbox
 *
 * Features:
 * - Tabbed interface for Plan and Sandbox
 * - PlanEditor integration for Plan Mode
 * - Integrated Terminal and Remote Desktop
 * - Tool execution output viewer
 * - Draggable resize support
 * - Modern, clean design
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Tabs, Button, Empty, Badge, Alert, Spin } from 'antd';
import {
  X,
  ListTodo,
  Terminal,
  CheckCircle2,
  Play,
  Clock
} from 'lucide-react';
import { SandboxSection } from './SandboxSection';
import { PlanEditor } from './PlanEditor';
import { usePlanModeStore } from '../../stores/agent/planModeStore';
import type { WorkPlan } from '../../types/agent';
import type { ExecutionPlan } from '../../types/agent';
import type { ToolExecution } from './sandbox/SandboxOutputViewer';

export type RightPanelTab = 'plan' | 'sandbox';

export interface RightPanelProps {
  workPlan: WorkPlan | null;
  executionPlan: ExecutionPlan | null;
  sandboxId?: string | null;
  toolExecutions?: ToolExecution[];
  currentTool?: { name: string; input: Record<string, unknown> } | null;
  onClose?: () => void;
  onFileClick?: (filePath: string) => void;
  collapsed?: boolean;
  /** Width of the panel (controlled by parent) */
  width?: number;
  /** Callback when width changes during resize */
  onWidthChange?: (width: number) => void;
  /** Minimum width */
  minWidth?: number;
  /** Maximum width */
  maxWidth?: number;
}

// Resize Handle Component
const ResizeHandle: React.FC<{
  onResize: (delta: number) => void;
}> = ({ onResize }) => {
  const [isDragging, setIsDragging] = useState(false);
  const startXRef = useRef(0);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
    startXRef.current = e.clientX;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'ew-resize';
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - startXRef.current;
      startXRef.current = e.clientX;
      onResize(delta);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, onResize]);

  return (
    <div
      onMouseDown={handleMouseDown}
      className={`
        absolute left-0 top-0 bottom-0 w-1.5 cursor-ew-resize z-50
        flex items-center justify-center
        bg-transparent
        hover:bg-slate-200/50 dark:hover:bg-slate-700/50
        ${isDragging ? 'bg-slate-300/70 dark:bg-slate-600/70' : ''}
        transition-all duration-150
        group
      `}
    >
      {/* Visual indicator - subtle dots */}
      <div className={`
        w-0.5 h-6 rounded-full
        bg-slate-400/50 dark:bg-slate-500/50
        opacity-0 group-hover:opacity-100
        ${isDragging ? 'opacity-100 bg-slate-500 dark:bg-slate-400' : ''}
        transition-all duration-150
      `} />
    </div>
  );
};

// Plan Tab Content
const PlanContent: React.FC<{
  workPlan: WorkPlan | null;
  executionPlan: ExecutionPlan | null;
}> = ({ workPlan, executionPlan }) => {
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
      <div className="mb-6">
        <div className="flex justify-between text-xs text-slate-500 mb-1">
          <span>Progress</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
          <div 
            className="h-full bg-primary rounded-full transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Steps */}
      <div className="space-y-3">
        {steps.map((step: any, index: number) => {
          const isCompleted = index < currentStep;
          const isCurrent = index === currentStep;

          return (
            <div
              key={index}
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
        })}
      </div>

      {/* Plan Meta Info */}
      {plan && (
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
      )}
    </div>
  );
};

export const RightPanel: React.FC<RightPanelProps> = ({
  workPlan,
  executionPlan,
  sandboxId,
  toolExecutions = [],
  currentTool,
  onClose,
  collapsed,
  width = 360,
  onWidthChange,
  minWidth = 280,
  maxWidth = 600,
}) => {
  const [activeTab, setActiveTab] = useState<RightPanelTab>('plan');

  const hasPlan = !!(workPlan || executionPlan);
  const hasSandbox = !!sandboxId;

  // Handle resize
  const handleResize = useCallback((delta: number) => {
    if (!onWidthChange) return;
    const newWidth = Math.max(minWidth, Math.min(maxWidth, width - delta));
    onWidthChange(newWidth);
  }, [width, onWidthChange, minWidth, maxWidth]);

  const tabItems = [
    {
      key: 'plan' as RightPanelTab,
      label: (
        <div className="flex items-center gap-2">
          <ListTodo size={16} />
          <span>Plan</span>
          {hasPlan && <Badge status="processing" className="ml-1" />}
        </div>
      ),
      children: (
        <PlanContent 
          workPlan={workPlan} 
          executionPlan={executionPlan} 
        />
      ),
    },
    {
      key: 'sandbox' as RightPanelTab,
      label: (
        <div className="flex items-center gap-2">
          <Terminal size={16} />
          <span>Sandbox</span>
          {hasSandbox && <Badge status="success" className="ml-1" />}
        </div>
      ),
      children: (
        <SandboxSection
          sandboxId={sandboxId || null}
          toolExecutions={toolExecutions}
          currentTool={currentTool || null}
        />
      ),
    },
  ];

  if (collapsed) {
    return null;
  }

  return (
    <div 
      className="h-full flex bg-white dark:bg-slate-900 relative"
      style={{ width }}
    >
      {/* Resize Handle - only show if onWidthChange is provided */}
      {onWidthChange && (
        <ResizeHandle onResize={handleResize} />
      )}

      {/* Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2">
            {activeTab === 'plan' ? (
              <ListTodo size={18} className="text-slate-500" />
            ) : (
              <Terminal size={18} className="text-slate-500" />
            )}
            <h2 className="font-semibold text-slate-900 dark:text-slate-100">
              {activeTab === 'plan' ? 'Work Plan' : 'Sandbox'}
            </h2>
          </div>
          <div className="flex items-center gap-1">
            {onClose && (
              <Button
                type="text"
                size="small"
                icon={<X size={18} />}
                onClick={onClose}
                className="text-slate-400 hover:text-slate-600"
              />
            )}
          </div>
        </div>

        {/* Tabs */}
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as RightPanelTab)}
          items={tabItems}
          className="flex-1 right-panel-tabs"
          tabBarStyle={{ 
            margin: 0, 
            paddingLeft: 16,
            paddingRight: 16,
            borderBottom: '1px solid #e2e8f0',
          }}
        />

        {/* Styles */}
        <style>{`
          .right-panel-tabs {
            display: flex;
            flex-direction: column;
            height: 100%;
          }
          .right-panel-tabs .ant-tabs-content {
            flex: 1;
            height: 0;
          }
          .right-panel-tabs .ant-tabs-content-holder {
            flex: 1;
            display: flex;
            flex-direction: column;
          }
          .right-panel-tabs .ant-tabs-tabpane {
            height: 100%;
            overflow-y: auto;
          }
          .right-panel-tabs .ant-tabs-nav {
            margin-bottom: 0;
          }
        `}</style>
      </div>
    </div>
  );
};

export default RightPanel;
