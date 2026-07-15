export type SessionSurface = 'conversation' | 'split' | 'canvas';

export type SessionSurfaceAction =
  | 'select_session'
  | 'show_conversation'
  | 'open_canvas'
  | 'show_split'
  | 'focus_canvas'
  | 'close_canvas';

export type SessionSurfacePanes = {
  thread: boolean;
  canvas: boolean;
};

export type SessionSurfaceState = {
  sessionId: string;
  surface: SessionSurface;
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

export function sessionSurfaceForSession(
  state: SessionSurfaceState,
  sessionId: string,
): SessionSurface {
  return state.sessionId === sessionId ? state.surface : 'conversation';
}

export function transitionSessionSurface(
  state: SessionSurfaceState,
  sessionId: string,
  action: SessionSurfaceAction,
): SessionSurfaceState {
  return {
    sessionId,
    surface: nextSessionSurface(sessionSurfaceForSession(state, sessionId), action),
  };
}

export function sessionSurfacePanes(
  surface: SessionSurface,
  hasCanvas: boolean,
): SessionSurfacePanes {
  if (!hasCanvas || surface === 'conversation') {
    return { thread: true, canvas: false };
  }
  if (surface === 'split') {
    return { thread: true, canvas: true };
  }
  return { thread: false, canvas: true };
}
