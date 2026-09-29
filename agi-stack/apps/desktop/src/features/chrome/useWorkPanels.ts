import { useCallback, useRef, useState } from 'react';
import {
  EMPTY_WORK_PANEL,
  reduceWorkPanel,
  type WorkPanelAction,
  type WorkPanelState,
  type WorkPanelTab,
} from './workPanelState';

/** Session UI state intentionally lives only for this application run. */
export function useWorkPanels() {
  const scopeRef = useRef('');
  const triggerRef = useRef(new Map<string, HTMLElement>());
  const [sessions, setSessions] = useState<Readonly<Record<string, WorkPanelState>>>({});
  const dispatch = useCallback((action: WorkPanelAction) => {
    const key = scopeRef.current;
    if (action.type === 'open' || action.type === 'show') {
      const focused = document.activeElement;
      if (
        focused instanceof HTMLElement &&
        !focused.closest('.desktop-right-sidebar, [role="menu"]')
      ) {
        triggerRef.current.set(key, focused);
      }
    }
    setSessions((current) => ({
      ...current,
      [key]: reduceWorkPanel(current[key] ?? EMPTY_WORK_PANEL, action),
    }));
  }, []);
  const restoreFocus = useCallback(() => {
    const scope = scopeRef.current;
    const trigger = triggerRef.current.get(scope);
    window.requestAnimationFrame(() => {
      if (scopeRef.current !== scope) return;
      const fallback = document.querySelector<HTMLElement>('[data-work-panel-toggle]');
      (trigger?.isConnected ? trigger : fallback)?.focus();
    });
  }, []);
  const open = useCallback((tab: WorkPanelTab) => dispatch({ type: 'open', tab }), [dispatch]);
  const hide = useCallback(() => {
    dispatch({ type: 'hide' });
    restoreFocus();
  }, [dispatch, restoreFocus]);
  return { sessions, scopeRef, dispatch, open, hide, restoreFocus };
}
