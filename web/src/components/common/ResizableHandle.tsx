import React from "react";
import { Separator } from "react-resizable-panels";

/**
 * Props for ResizableHandle component
 */
interface ResizableHandleProps {
  /** Optional className for additional styling */
  className?: string;
  /** Unique id for the handle */
  id?: string;
}

/**
 * ResizableHandle Component - Draggable separator for resizable panels
 *
 * Provides a visual and interactive handle for resizing panels.
 * Features hover effects and visual feedback during dragging.
 *
 * @component
 */
export const ResizableHandle: React.FC<ResizableHandleProps> = React.memo(({
  className = "",
  id,
}) => {
  return (
    <Separator
      id={id}
      className={`
        relative z-50 flex items-center justify-center
        bg-slate-200 hover:bg-primary
        transition-all duration-150 ease-out
        cursor-ew-resize
        before:absolute before:inset-0 before:bg-transparent before:hover:bg-primary/10
        ${className}
      `}
      style={{
        width: "8px",
        // Make the entire area clickable
      }}
    />
  );
});

ResizableHandle.displayName = "ResizableHandle";
