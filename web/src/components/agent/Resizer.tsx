/**
 * Resizer - Draggable resize handle component
 *
 * Supports horizontal (left/right) and vertical (up/down) resizing
 * Unified subtle styling for all resize handles
 */

import * as React from 'react';
import { useState, useCallback, useEffect, useRef } from 'react';

type ResizeDirection = 'horizontal' | 'vertical';

interface ResizerProps {
  /** Resize direction */
  direction: ResizeDirection;
  /** Current size (width for horizontal, height for vertical) */
  currentSize: number;
  /** Minimum size */
  minSize: number;
  /** Maximum size */
  maxSize: number;
  /** Callback when size changes */
  onResize: (newSize: number) => void;
  /** Optional className */
  className?: string | undefined;
  /** Position: 'left' | 'right' for horizontal, 'top' | 'bottom' for vertical */
  position?: 'left' | 'right' | 'top' | 'bottom' | undefined;
}

export const Resizer: React.FC<ResizerProps> = ({
  direction,
  currentSize,
  minSize,
  maxSize,
  onResize,
  className = '',
  position = 'right',
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const startPosRef = useRef(0);
  const startSizeRef = useRef(currentSize);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
      startPosRef.current = direction === 'horizontal' ? e.clientX : e.clientY;
      startSizeRef.current = currentSize;

      // Prevent text selection during drag
      document.body.style.userSelect = 'none';
      document.body.style.cursor = direction === 'horizontal' ? 'ew-resize' : 'ns-resize';
    },
    [direction, currentSize]
  );

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const currentPos = direction === 'horizontal' ? e.clientX : e.clientY;
      const delta = currentPos - startPosRef.current;

      // Calculate new size based on position
      let newSize: number;
      if (position === 'right' || position === 'bottom') {
        newSize = startSizeRef.current + delta;
      } else {
        newSize = startSizeRef.current - delta;
      }

      // Clamp to min/max
      newSize = Math.max(minSize, Math.min(maxSize, newSize));
      onResize(newSize);
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
  }, [isDragging, direction, position, minSize, maxSize, onResize]);

  // Position styles
  const positionStyles: Record<ResizeDirection, Record<string, string>> = {
    horizontal: {
      right: 'left-0 -translate-x-full',
      left: 'right-0 translate-x-full',
    },
    vertical: {
      top: 'bottom-0 translate-y-full',
      bottom: 'top-0 -translate-y-full',
    },
  };

  const cursorClass = direction === 'horizontal' ? 'cursor-ew-resize' : 'cursor-ns-resize';
  const sizeClass = direction === 'horizontal' ? 'w-1.5 hover:w-2' : 'h-1.5 hover:h-2';

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const step = e.shiftKey ? 50 : 10;
      let newSize = currentSize;
      if (direction === 'horizontal') {
        if (e.key === 'ArrowRight') newSize = currentSize + step;
        else if (e.key === 'ArrowLeft') newSize = currentSize - step;
        else return;
      } else {
        if (e.key === 'ArrowDown') newSize = currentSize + step;
        else if (e.key === 'ArrowUp') newSize = currentSize - step;
        else return;
      }
      e.preventDefault();
      onResize(Math.max(minSize, Math.min(maxSize, newSize)));
    },
    [direction, currentSize, minSize, maxSize, onResize]
  );

  return (
    <div
      role="separator"
      aria-valuenow={currentSize}
      aria-valuemin={minSize}
      aria-valuemax={maxSize}
      aria-orientation={direction === 'horizontal' ? 'vertical' : 'horizontal'}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onMouseDown={handleMouseDown}
      className={`
        absolute z-10 flex items-center justify-center
        ${positionStyles[direction][position]}
        ${cursorClass}
        ${sizeClass}
        bg-transparent
        hover:bg-slate-200/50 dark:hover:bg-slate-700/50
        ${isDragging ? 'bg-slate-300/70 dark:bg-slate-600/70' : ''}
        transition-colors duration-150
        group
        ${className ?? ''}
      `}
      style={{
        [direction === 'horizontal' ? 'top' : 'left']: 0,
        [direction === 'horizontal' ? 'bottom' : 'right']: 0,
      }}
    >
      {/* Visual indicator - subtle dots */}
      <div
        className={`
        ${direction === 'horizontal' ? 'w-0.5 h-6' : 'h-0.5 w-6'}
        rounded-full
        bg-slate-400/50 dark:bg-slate-500/50
        opacity-0 group-hover:opacity-100
        ${isDragging ? 'opacity-100 bg-slate-500 dark:bg-slate-400' : ''}
        transition-colors duration-150
      `}
      />
    </div>
  );
};

export default Resizer;
