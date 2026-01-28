/**
 * RenderModeSwitch - Toggle between grouped and timeline rendering modes
 *
 * Allows users to switch between:
 * - Grouped mode: Messages are aggregated into user/assistant groups
 * - Timeline mode: Each event is displayed independently in chronological order
 *
 * @module components/agent/RenderModeSwitch
 */

import { memo } from 'react';
import type { RenderMode } from './VirtualTimelineEventList';

export interface RenderModeSwitchProps {
  /** Current render mode */
  mode: RenderMode;
  /** Callback when mode is toggled */
  onToggle: (newMode: RenderMode) => void;
  /** Additional CSS class name */
  className?: string;
  /** Whether to show labels (default: true) */
  showLabels?: boolean;
}

/**
 * RenderModeSwitch component
 *
 * @example
 * ```tsx
 * import { RenderModeSwitch } from '@/components/agent/RenderModeSwitch'
 *
 * function ChatToolbar() {
 *   const [mode, setMode] = useState<RenderMode>('grouped')
 *
 *   return (
 *     <RenderModeSwitch
 *       mode={mode}
 *       onToggle={setMode}
 *     />
 *   )
 * }
 * ```
 */
export const RenderModeSwitch: React.FC<RenderModeSwitchProps> = memo(({
  mode,
  onToggle,
  className = '',
  showLabels = true,
}) => {
  const handleToggle = () => {
    const newMode: RenderMode = mode === 'grouped' ? 'timeline' : 'grouped';
    onToggle(newMode);
  };

  return (
    <div
      data-testid="render-mode-switch"
      data-mode={mode}
      className={`flex items-center gap-2 ${className}`}
    >
      {/* Toggle Switch */}
      <button
        onClick={handleToggle}
        role="switch"
        aria-checked={mode === 'timeline'}
        aria-label={`Switch to ${mode === 'grouped' ? 'timeline' : 'grouped'} mode`}
        className={`
          relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full
          border-2 border-transparent transition-colors duration-200 ease-in-out
          focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2
          ${mode === 'timeline'
            ? 'bg-primary'
            : 'bg-slate-200 dark:bg-slate-700'
          }
        `}
        type="button"
      >
        <span
          className={`
            pointer-events-none inline-block h-5 w-5 rounded-full
            bg-white shadow transform transition-transform duration-200 ease-in-out
            ${mode === 'timeline' ? 'translate-x-5' : 'translate-x-0'}
          `}
        />
      </button>

      {/* Labels */}
      {showLabels && (
        <div className="flex items-center gap-3 text-xs font-medium">
          <span
            aria-label="Grouped mode"
            className={`flex items-center gap-1 transition-colors ${
              mode === 'grouped'
                ? 'text-primary font-semibold'
                : 'text-slate-500 dark:text-slate-400'
            }`}
          >
            <span className="material-symbols-outlined text-sm">view_day</span>
            Grouped
          </span>
          <span
            aria-label="Timeline mode"
            className={`flex items-center gap-1 transition-colors ${
              mode === 'timeline'
                ? 'text-primary font-semibold'
                : 'text-slate-500 dark:text-slate-400'
            }`}
          >
            <span className="material-symbols-outlined text-sm">timeline</span>
            Timeline
          </span>
        </div>
      )}
    </div>
  );
});

RenderModeSwitch.displayName = 'RenderModeSwitch';

export default RenderModeSwitch;
