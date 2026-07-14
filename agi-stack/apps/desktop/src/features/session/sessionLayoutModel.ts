import type { SessionCanvasTabId } from './sessionCanvasModel';

export type SessionSurface = 'conversation' | 'split' | 'canvas';

export type SessionInspectorMode = 'code' | 'work' | 'unavailable';

export type SessionSurfaceAction =
  | 'select_session'
  | 'show_conversation'
  | 'open_canvas'
  | 'show_split'
  | 'focus_canvas'
  | 'close_canvas';

export type SessionSurfacePanes = {
  thread: boolean;
  inspector: boolean;
  canvas: boolean;
};

export function nextSessionSurface(
  current: SessionSurface,
  action: SessionSurfaceAction,
): SessionSurface {
  if (action === 'select_session' || action === 'show_conversation' || action === 'close_canvas') {
    return 'conversation';
  }
  if (action === 'open_canvas' || action === 'show_split') return 'split';
  if (action === 'focus_canvas') return 'canvas';
  return current;
}

export function sessionSurfacePanes(
  surface: SessionSurface,
  hasCanvas: boolean,
): SessionSurfacePanes {
  if (!hasCanvas || surface === 'conversation') {
    return { thread: true, inspector: true, canvas: false };
  }
  if (surface === 'split') {
    return { thread: true, inspector: false, canvas: true };
  }
  return { thread: false, inspector: false, canvas: true };
}

export function sessionInspectorSurfaceIds(
  mode: SessionInspectorMode,
): SessionCanvasTabId[] {
  if (mode === 'code') return ['plan', 'changes', 'checks'];
  if (mode === 'work') return ['plan', 'artifacts', 'verification'];
  return ['plan', 'artifacts', 'activity'];
}
