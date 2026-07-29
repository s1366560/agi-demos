import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent,
} from 'react';

import {
  clampPanelWidth,
  panelWidthFromDrag,
  panelWidthFromKey,
  parsePersistedPanelWidth,
  type PanelResizeConstraints,
  type PanelResizeSide,
} from './resizeHandleModel';
import './ResizeHandle.css';

export type ResizablePanelWidth = {
  width: number;
  resize: (width: number) => void;
  reset: () => void;
};

/**
 * Track a user-resizable panel width. The choice persists in localStorage but
 * stays clamped to the current constraints, and falls back to the default
 * when storage is unavailable (SSR, privacy modes).
 */
export function useResizablePanelWidth(
  storageKey: string,
  constraints: PanelResizeConstraints,
): ResizablePanelWidth {
  const constraintsRef = useRef(constraints);
  constraintsRef.current = constraints;
  const [width, setWidth] = useState(() => {
    try {
      if (typeof window === 'undefined') return constraints.default;
      return (
        parsePersistedPanelWidth(window.localStorage.getItem(storageKey), constraints) ??
        constraints.default
      );
    } catch {
      return constraints.default;
    }
  });

  const resize = useCallback(
    (next: number) => {
      const clamped = clampPanelWidth(next, constraintsRef.current);
      setWidth(clamped);
      try {
        window.localStorage.setItem(storageKey, String(Math.round(clamped)));
      } catch {
        // Persistence is best-effort; the in-memory width still applies.
      }
    },
    [storageKey],
  );
  const reset = useCallback(() => resize(constraintsRef.current.default), [resize]);

  return { width, resize, reset };
}

type ResizeHandleProps = {
  side: PanelResizeSide;
  width: number;
  constraints: PanelResizeConstraints;
  label: string;
  onResize: (width: number) => void;
  onReset: () => void;
};

export function ResizeHandle({
  side,
  width,
  constraints,
  label,
  onResize,
  onReset,
}: ResizeHandleProps) {
  const handleRef = useRef<HTMLDivElement>(null);
  const onResizeRef = useRef(onResize);
  onResizeRef.current = onResize;
  const [drag, setDrag] = useState<{
    pointerId: number;
    startX: number;
    startWidth: number;
  } | null>(null);

  // The effect owns the whole drag lifecycle: window-level listeners keep
  // tracking beyond the handle bounds, and its cleanup restores the global
  // cursor/selection on every exit path — pointerup, pointercancel, lost
  // pointer capture, window blur, Escape, and unmount mid-drag.
  useEffect(() => {
    if (!drag) return undefined;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const trackPointer = (event: PointerEvent) => {
      if (event.pointerId !== drag.pointerId) return;
      onResizeRef.current(
        panelWidthFromDrag(drag.startWidth, event.clientX - drag.startX, side, constraints),
      );
    };
    const finishDrag = (event: PointerEvent) => {
      if (event.pointerId === drag.pointerId) setDrag(null);
    };
    const cancelDrag = () => setDrag(null);
    const cancelOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      cancelDrag();
    };

    window.addEventListener('pointermove', trackPointer);
    window.addEventListener('pointerup', finishDrag);
    window.addEventListener('pointercancel', finishDrag);
    window.addEventListener('lostpointercapture', finishDrag);
    window.addEventListener('blur', cancelDrag);
    document.addEventListener('keydown', cancelOnEscape);
    return () => {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      try {
        if (handleRef.current?.hasPointerCapture(drag.pointerId)) {
          handleRef.current.releasePointerCapture(drag.pointerId);
        }
      } catch {
        // The element may already be gone; capture release is best-effort.
      }
      window.removeEventListener('pointermove', trackPointer);
      window.removeEventListener('pointerup', finishDrag);
      window.removeEventListener('pointercancel', finishDrag);
      window.removeEventListener('lostpointercapture', finishDrag);
      window.removeEventListener('blur', cancelDrag);
      document.removeEventListener('keydown', cancelOnEscape);
    };
  }, [drag, side, constraints]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || drag) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ pointerId: event.pointerId, startX: event.clientX, startWidth: width });
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const next = panelWidthFromKey(width, event.key, side, constraints);
    if (next === null) return;
    event.preventDefault();
    onResize(next);
  };

  return (
    <div
      ref={handleRef}
      className={`panel-resize-handle panel-resize-handle-${side} ${drag ? 'dragging' : ''}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(width)}
      aria-valuemin={constraints.min}
      aria-valuemax={constraints.max}
      title={label}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onKeyDown={handleKeyDown}
      onDoubleClick={onReset}
    />
  );
}
