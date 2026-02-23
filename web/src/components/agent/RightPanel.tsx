/**
 * RightPanel - Side panel with Tasks
 *
 * Features:
 * - Agent-managed task checklist (DB-persistent, SSE-streamed)
 * - Draggable resize support
 */

import { useCallback, memo } from 'react';

import { X, ListTodo } from 'lucide-react';

import { LazyButton } from '@/components/ui/lazyAntd';

import { ResizeHandle } from './RightPanelComponents';
import { TaskList } from './TaskList';

import type { AgentTask } from '../../types/agent';

export interface RightPanelProps {
  tasks?: AgentTask[];
  sandboxId?: string | null;
  onClose?: () => void;
  onFileClick?: (filePath: string) => void;
  collapsed?: boolean;
  width?: number;
  onWidthChange?: (width: number) => void;
  minWidth?: number;
  maxWidth?: number;
}

export const RightPanel = memo<RightPanelProps>(
  ({
    tasks = [],
    onClose,
    collapsed,
    width = 360,
    onWidthChange,
    minWidth = 280,
    maxWidth = 600,
  }) => {
    const handleResize = useCallback(
      (delta: number) => {
        if (!onWidthChange) return;
        const newWidth = Math.max(minWidth, Math.min(maxWidth, width - delta));
        onWidthChange(newWidth);
      },
      [width, onWidthChange, minWidth, maxWidth]
    );

    if (collapsed) {
      return null;
    }

    return (
      <div
        className="h-full w-full flex bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm relative"
        data-testid="right-panel"
      >
        {onWidthChange ? (
          <ResizeHandle onResize={handleResize} direction="horizontal" position="left" />
        ) : null}

        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/50">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-100 to-violet-100 dark:from-purple-900/30 dark:to-violet-900/20 flex items-center justify-center">
                <ListTodo size={16} className="text-purple-600 dark:text-purple-400" />
              </div>
              <h2 className="font-semibold text-slate-900 dark:text-slate-100">Tasks</h2>
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

          {/* Task List */}
          <div className="flex-1 overflow-y-auto">
            <TaskList tasks={tasks} />
          </div>
        </div>
      </div>
    );
  }
);

RightPanel.displayName = 'RightPanel';

export default RightPanel;
