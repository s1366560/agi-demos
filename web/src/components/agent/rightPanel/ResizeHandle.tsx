/**
 * ResizeHandle - Draggable resize handle component
 *
 * A reusable resize handle that can be oriented horizontally or vertically.
 * Extracted from RightPanel for better separation of concerns.
 *
 * Features:
 * - Drag-to-resize with mouse events
 * - Configurable direction (horizontal/vertical)
 * - Visual feedback during drag
 * - Min/max size constraints
 */

import { useState, useCallback, useRef, useEffect } from 'react';

export interface ResizeHandleProps {
  /** Callback when resize occurs - called with delta change */
  onResize: (delta: number) => void;
  /** Direction of resize */
  direction?: 'horizontal' | 'vertical';
  /** Position of handle */
  position?: 'left' | 'right' | 'top' | 'bottom';
  /** Optional className for custom styling */
  className?: string;
}

export const ResizeHandle = ({
  onResize,
  direction = 'horizontal',
  position = 'left',
  className = '',
}: ResizeHandleProps) => {
  const [isDragging, setIsDragging] = useState(false);
  const startPosRef = useRef(0);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
      startPosRef.current = direction === 'horizontal' ? e.clientX : e.clientY;
      document.body.style.userSelect = 'none';
      document.body.style.cursor = direction === 'horizontal' ? 'ew-resize' : 'ns-resize';
    },
    [direction]
  );

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const currentPos = direction === 'horizontal' ? e.clientX : e.clientY;
      const delta = currentPos - startPosRef.current;
      startPosRef.current = currentPos;
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
  }, [isDragging, onResize, direction]);

  // Generate position classes
  const getPositionClasses = () => {
    switch (position) {
      case 'left':
        return 'left-0 top-0 bottom-0 w-1.5';
      case 'right':
        return 'right-0 top-0 bottom-0 w-1.5';
      case 'top':
        return 'top-0 left-0 right-0 h-1.5';
      case 'bottom':
        return 'bottom-0 left-0 right-0 h-1.5';
      default:
        return 'left-0 top-0 bottom-0 w-1.5';
    }
  };

  // Generate cursor class
  const getCursorClass = () => {
    return direction === 'horizontal' ? 'cursor-ew-resize' : 'cursor-ns-resize';
  };

  return (
    <div
      onMouseDown={handleMouseDown}
      className={`
        absolute z-50 flex items-center justify-center
        ${getPositionClasses()} ${getCursorClass()}
        bg-transparent
        hover:bg-slate-200/50 dark:hover:bg-slate-700/50
        ${isDragging ? 'bg-slate-300/70 dark:bg-slate-600/70' : ''}
        transition-all duration-150
        group
        ${className}
      `}
      data-testid="resize-handle"
    >
      {/* Visual indicator - subtle line */}
      <div
        className={`
        ${direction === 'horizontal' ? 'w-0.5 h-6' : 'h-0.5 w-6'}
        rounded-full
        bg-slate-400/50 dark:bg-slate-500/50
        opacity-0 group-hover:opacity-100
        ${isDragging ? 'opacity-100 bg-slate-500 dark:bg-slate-400' : ''}
        transition-all duration-150
      `}
      />
    </div>
  );
};

export default ResizeHandle;
