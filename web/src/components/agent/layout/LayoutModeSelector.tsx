/**
 * LayoutModeSelector - Quick-switch buttons for layout modes
 *
 * Renders in the status bar area. Provides visual indication of current mode
 * and one-click switching between Chat, Task, Code, Canvas, and Collab modes.
 */

import type { FC } from 'react';
import { useEffect, useCallback, useMemo } from 'react';

import { MessageSquareText, ListTodo, TerminalSquare, PanelRight, Users } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useLayoutModeStore, type LayoutMode } from '@/stores/layoutMode';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import type { LucideIcon } from 'lucide-react';

const ALL_MODES: Array<{
  key: LayoutMode;
  icon: LucideIcon;
  label: string;
  shortcut: string;
  description: string;
  requiresWorkspace?: boolean;
}> = [
  {
    key: 'chat',
    icon: MessageSquareText,
    label: 'Chat',
    shortcut: '1',
    description: 'Full chat view with optional plan panel',
  },
  {
    key: 'task',
    icon: ListTodo,
    label: 'Task',
    shortcut: '2',
    description: 'Split view: chat + task panel (50/50)',
  },
  {
    key: 'code',
    icon: TerminalSquare,
    label: 'Code',
    shortcut: '3',
    description: 'Split view: chat + terminal (50/50)',
  },
  {
    key: 'canvas',
    icon: PanelRight,
    label: 'Canvas',
    shortcut: '4',
    description: 'Split view: chat + artifact canvas (35/65)',
  },
  {
    key: 'collab',
    icon: Users,
    label: 'Collab',
    shortcut: '5',
    description: 'Split view: chat + workspace group chat (55/45)',
    requiresWorkspace: true,
  },
];

interface LayoutModeSelectorProps {
  hasWorkspace?: boolean;
}

export const LayoutModeSelector: FC<LayoutModeSelectorProps> = ({ hasWorkspace = false }) => {
  const { mode, setMode } = useLayoutModeStore(
    useShallow((state) => ({ mode: state.mode, setMode: state.setMode }))
  );

  const visibleModes = useMemo(
    () => ALL_MODES.filter((m) => !m.requiresWorkspace || hasWorkspace),
    [hasWorkspace],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) {
        const modeForKey = visibleModes.find((m) => m.shortcut === e.key);
        if (modeForKey) {
          e.preventDefault();
          setMode(modeForKey.key);
        }
      }
    },
    [setMode, visibleModes]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleKeyDown]);

  return (
    <div
      data-tour="layout-selector"
      className="flex items-center gap-0.5 bg-slate-200/60 dark:bg-slate-700/40 rounded-md p-0.5"
    >
      {visibleModes.map((m) => {
        const Icon = m.icon;
        const isActive = mode === m.key;
        return (
          <LazyTooltip
            key={m.key}
            title={
              <div>
                <div className="font-medium">
                  {m.label} Mode{' '}
                  <span className="opacity-60 ml-1">
                    {/(Mac|iPhone|iPod|iPad)/i.test(navigator.userAgent) ? 'Cmd' : 'Ctrl'}+{m.shortcut}
                  </span>
                </div>
                <div className="text-xs opacity-80">{m.description}</div>
              </div>
            }
          >
            <button
              type="button"
              onClick={() => {
                setMode(m.key);
              }}
              className={`
                flex items-center gap-1 px-2 py-1 rounded text-xs font-medium
                transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-150 cursor-pointer
                ${
                  isActive
                    ? 'bg-white dark:bg-slate-600 text-slate-900 dark:text-slate-100 shadow-sm'
                    : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
                }
              `}
              aria-pressed={isActive}
              aria-label={`${m.label} mode`}
            >
              <Icon size={13} />
              <span className="hidden sm:inline">{m.label}</span>
            </button>
          </LazyTooltip>
        );
      })}
    </div>
  );
};
