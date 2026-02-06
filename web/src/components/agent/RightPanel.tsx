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
 *
 * Refactored: Extracted ResizeHandle and PlanContent into separate modules
 * for better separation of concerns and reusability.
 */

import { useState, useCallback, memo } from 'react';

import { X, ListTodo, Terminal } from 'lucide-react';

import { LazyTabs, LazyButton, LazyBadge } from '@/components/ui/lazyAntd';

import { ResizeHandle, PlanContent } from './RightPanelComponents';
import { SandboxSection } from './SandboxSection';

import type { ToolExecution } from './sandbox/SandboxOutputViewer';
import type { WorkPlan, ExecutionPlan } from '../../types/agent';

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

// Memoized RightPanel to prevent unnecessary re-renders (rerender-memo)
export const RightPanel = memo<RightPanelProps>(
  ({
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

    // Handle resize with constraints
    const handleResize = useCallback(
      (delta: number) => {
        if (!onWidthChange) return;
        const newWidth = Math.max(minWidth, Math.min(maxWidth, width - delta));
        onWidthChange(newWidth);
      },
      [width, onWidthChange, minWidth, maxWidth]
    );

    const tabItems = [
      {
        key: 'plan' as RightPanelTab,
        label: (
          <div className="flex items-center gap-2">
            <ListTodo size={16} />
            <span>Plan</span>
            {hasPlan && <LazyBadge status="processing" className="ml-1" />}
          </div>
        ),
        children: <PlanContent workPlan={workPlan} executionPlan={executionPlan} />,
      },
      {
        key: 'sandbox' as RightPanelTab,
        label: (
          <div className="flex items-center gap-2">
            <Terminal size={16} />
            <span>Sandbox</span>
            {hasSandbox && <LazyBadge status="success" className="ml-1" />}
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
        className="h-full flex bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm relative"
        style={{ '--panel-width': `${width}px` } as React.CSSProperties}
        data-testid="right-panel"
      >
        {/* Resize Handle - only show if onWidthChange is provided */}
        {onWidthChange ? (
          <ResizeHandle onResize={handleResize} direction="horizontal" position="left" />
        ) : null}

        {/* Content */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/50">
            <div className="flex items-center gap-2">
              {activeTab === 'plan' ? (
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-100 to-violet-100 dark:from-purple-900/30 dark:to-violet-900/20 flex items-center justify-center">
                  <ListTodo size={16} className="text-purple-600 dark:text-purple-400" />
                </div>
              ) : (
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-100 to-cyan-100 dark:from-blue-900/30 dark:to-cyan-900/20 flex items-center justify-center">
                  <Terminal size={16} className="text-blue-600 dark:text-blue-400" />
                </div>
              )}
              <h2 className="font-semibold text-slate-900 dark:text-slate-100">
                {activeTab === 'plan' ? 'Work Plan' : 'Sandbox'}
              </h2>
            </div>
            <div className="flex items-center gap-1">
              {onClose ? (
                <LazyButton
                  type="text"
                  size="small"
                  icon={<X size={18} />}
                  onClick={onClose}
                  className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-all"
                  data-testid="close-button"
                />
              ) : null}
            </div>
          </div>

          {/* Tabs */}
          <LazyTabs
            activeKey={activeTab}
            onChange={(key: string) => setActiveTab(key as RightPanelTab)}
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
          [data-testid="right-panel"] {
            width: var(--panel-width, 360px);
          }
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
  }
);

RightPanel.displayName = 'RightPanel';

export default RightPanel;
