/**
 * AgentChatInputArea - Extracted input area component
 *
 * A reusable input area component with resize support.
 * Extracted from AgentChatContent for better modularity.
 *
 * Features:
 * - Resizable input area with drag handle
 * - Integration with InputBar component
 * - Min/max height constraints
 */

import { GripHorizontal } from 'lucide-react';

import { InputBar } from './InputBar';
import { Resizer } from './Resizer';

import type { INPUT_MIN_HEIGHT, INPUT_MAX_HEIGHT } from './AgentChatHooks';

import type { FileMetadata } from '@/services/sandboxUploadService';

export interface AgentChatInputAreaProps {
  /** Current height of the input area */
  inputHeight: number;
  /** Callback when height changes */
  onHeightChange: (height: number) => void;
  /** Callback when user sends a message */
  onSend: (content: string, fileMetadata?: FileMetadata[]) => void | Promise<void>;
  /** Callback when user aborts streaming */
  onAbort: () => void;
  /** Whether agent is currently streaming */
  isStreaming: boolean;
  /** Whether input is disabled */
  disabled?: boolean;
  /** Whether in plan mode */
  isPlanMode?: boolean;
  /** Callback to toggle plan mode (required by InputBar) */
  onTogglePlanMode: () => void;
  /** Minimum height constraint */
  minHeight?: typeof INPUT_MIN_HEIGHT;
  /** Maximum height constraint */
  maxHeight?: typeof INPUT_MAX_HEIGHT;
  /** Current project ID for file attachments */
  projectId?: string;
}

/**
 * AgentChatInputArea component
 *
 * A self-contained input area with resize functionality.
 */
export const AgentChatInputArea = ({
  inputHeight,
  onHeightChange,
  onSend,
  onAbort,
  isStreaming,
  disabled = false,
  isPlanMode = false,
  onTogglePlanMode,
  minHeight = 140,
  maxHeight = 400,
  projectId,
}: AgentChatInputAreaProps) => {
  return (
    <div
      className="flex-shrink-0 border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 relative flex flex-col"
      style={{ height: inputHeight }}
      data-testid="agent-chat-input-area"
    >
      {/* Resize handle for input area (at top) */}
      <div className="absolute -top-2 left-0 right-0 z-40 flex justify-center">
        <Resizer
          direction="vertical"
          currentSize={inputHeight}
          minSize={minHeight}
          maxSize={maxHeight}
          onResize={onHeightChange}
          position="top"
        />
        <div className="pointer-events-none absolute top-1 flex items-center gap-1 text-slate-400">
          <GripHorizontal size={12} />
        </div>
      </div>

      <InputBar
        onSend={onSend}
        onAbort={onAbort}
        isStreaming={isStreaming}
        isPlanMode={isPlanMode}
        onTogglePlanMode={onTogglePlanMode}
        disabled={disabled}
        projectId={projectId}
      />
    </div>
  );
};

export default AgentChatInputArea;
