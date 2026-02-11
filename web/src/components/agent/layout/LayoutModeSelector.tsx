/**
 * LayoutModeSelector - Quick-switch buttons for layout modes
 *
 * Renders in the status bar area. Provides visual indication of current mode
 * and one-click switching between Chat, Code, Desktop, and Focus modes.
 */

import type { FC } from 'react';
import { useEffect, useCallback } from 'react';

import { MessageSquareText, TerminalSquare, Monitor, Maximize, PanelRight } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useLayoutModeStore, type LayoutMode } from '@/stores/layoutMode';

import { LazyTooltip } from '@/components/ui/lazyAntd';

const modes: Array<{
  key: LayoutMode;
  icon: React.ElementType;
  label: string;
  shortcut: string;
  description: string;
}> = [
  {
    key: 'chat',
    icon: MessageSquareText,
    label: 'Chat',
    shortcut: '1',
    description: 'Full chat view with optional plan panel',
  },
  {
    key: 'code',
    icon: TerminalSquare,
    label: 'Code',
    shortcut: '2',
    description: 'Split view: chat + terminal (50/50)',
  },
  {
    key: 'desktop',
    icon: Monitor,
    label: 'Desktop',
    shortcut: '3',
    description: 'Split view: chat + remote desktop (30/70)',
  },
  {
    key: 'focus',
    icon: Maximize,
    label: 'Focus',
    shortcut: '4',
    description: 'Fullscreen desktop with floating chat',
  },
  {
    key: 'canvas',
    icon: PanelRight,
    label: 'Canvas',
    shortcut: '5',
    description: 'Split view: chat + artifact canvas (35/65)',
  },
];

export const LayoutModeSelector: FC = () => {
  const { mode, setMode } = useLayoutModeStore(
    useShallow((state) => ({ mode: state.mode, setMode: state.setMode }))
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) {
        const modeForKey = modes.find((m) => m.shortcut === e.key);
        if (modeForKey) {
          e.preventDefault();
          setMode(modeForKey.key);
        }
      }
    },
    [setMode]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div data-tour="layout-selector" className="flex items-center gap-0.5 bg-slate-200/60 dark:bg-slate-700/40 rounded-md p-0.5">
      {modes.map((m) => {
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
                    {navigator.platform.includes('Mac') ? 'Cmd' : 'Ctrl'}+{m.shortcut}
                  </span>
                </div>
                <div className="text-xs opacity-80">{m.description}</div>
              </div>
            }
          >
            <button
              type="button"
              onClick={() => setMode(m.key)}
              className={`
                flex items-center gap-1 px-2 py-1 rounded text-xs font-medium
                transition-all duration-150 cursor-pointer
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
