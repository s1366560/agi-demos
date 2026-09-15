import { useEffect, useRef, useState } from 'react';

import { Cross2Icon, GlobeIcon, LayoutIcon, ReaderIcon } from '@radix-ui/react-icons';

import { ResizeHandle, useResizablePanelWidth } from '../../components/ResizeHandle';
import { useI18n } from '../../i18n';
import { BrowserPanel } from '../browser/BrowserPanel';
import { SessionContextRail } from '../session/SessionContextRail';
import type { SessionCanvasTabId } from '../session/sessionCanvasModel';
import type {
  SessionDetailViewModel,
  SessionRunAction,
} from '../session/sessionViewModel';
import type { SessionCanvasControls } from '../session/workspaceReviewPanelModel';
import { DesktopRendererSessionCanvasV2 } from '../../plugins/DesktopRendererSessionCanvasV2';
import type { DesktopSessionCanvasInputV2 } from '../../plugins/DesktopSessionCanvasSurfaceV2';
import './DesktopRightSidebar.css';

export type DesktopRightPanel = 'context' | 'canvas' | 'browser';

export type DesktopRightSidebarCanvasV2 =
  | Readonly<{ kind: 'available'; input: DesktopSessionCanvasInputV2 }>
  | Readonly<{ kind: 'unavailable' }>;

const RIGHT_SIDEBAR_WIDTH_STORAGE_KEY = 'agistack.desktop.rightSidebarWidth';
// prototype mission-control refactor 2026-09 (phase 5a): the default matches
// the prototype context-rail width (248px); focus mode lifts the max so the
// canvas can expand across the thread column (prototype layout-focus).
const RIGHT_SIDEBAR_WIDTH_CONSTRAINTS = { min: 220, max: 520, default: 248 } as const;
const RIGHT_SIDEBAR_FOCUS_MAX_WIDTH = 2000;
const RIGHT_SIDEBAR_ACTIVITY_BAR_WIDTH = 40;

type DesktopRightSidebarProps = {
  activePanel: DesktopRightPanel;
  canvas: DesktopRightSidebarCanvasV2;
  viewModel: SessionDetailViewModel | null;
  runActionPending: SessionRunAction | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
  onSelectPanel: (panel: DesktopRightPanel) => void;
  onCloseCanvas: () => void;
  onClose: () => void;
};

/**
 * Orca-style right sidebar: a 40px vertical activity bar on the outer edge
 * plus a resizable panel hosting the session context rail or the review
 * canvas. Canvas layout mapping: the old split/focus surfaces become panel
 * widths here — 'focus' expands the panel across the thread column (the
 * prototype's layout-focus), 'split' returns it to the default width.
 */
export function DesktopRightSidebar({
  activePanel,
  canvas,
  viewModel,
  runActionPending,
  onRunAction,
  onOpenCanvas,
  onSelectPanel,
  onCloseCanvas,
  onClose,
}: DesktopRightSidebarProps) {
  const { t } = useI18n();
  const [canvasLayout, setCanvasLayout] = useState<'split' | 'focus'>('split');
  const hostRef = useRef<HTMLElement | null>(null);
  // Focus mode needs a wider clamp than the split panel; the hook re-reads the
  // constraints every render, so widening the max while focused is enough.
  const widthConstraints =
    canvasLayout === 'focus'
      ? { ...RIGHT_SIDEBAR_WIDTH_CONSTRAINTS, max: RIGHT_SIDEBAR_FOCUS_MAX_WIDTH }
      : RIGHT_SIDEBAR_WIDTH_CONSTRAINTS;
  const panelWidth = useResizablePanelWidth(
    RIGHT_SIDEBAR_WIDTH_STORAGE_KEY,
    widthConstraints,
  );
  const canvasTriggerRef = useRef<string | null>(null);

  // The context rail and review canvas are session-scoped; without a session
  // the browser panel is the only surface that can render.
  const effectivePanel: DesktopRightPanel =
    viewModel === null ? 'browser' : activePanel;

  // Panel width at which the thread column (minmax(0, 1fr)) collapses: the
  // whole shell row left of the activity bar. Measured from the live grid so
  // the left sidebar's user-resized width is honored.
  const measureFocusPanelWidth = () => {
    if (typeof window === 'undefined') return RIGHT_SIDEBAR_WIDTH_CONSTRAINTS.max;
    const shell = hostRef.current?.closest('.app-shell');
    if (!(shell instanceof HTMLElement)) return RIGHT_SIDEBAR_WIDTH_CONSTRAINTS.max;
    const sidebarColumn = Number.parseFloat(
      window.getComputedStyle(shell).gridTemplateColumns.split(' ')[0] ?? '',
    );
    if (!Number.isFinite(sidebarColumn)) return RIGHT_SIDEBAR_WIDTH_CONSTRAINTS.max;
    return Math.max(
      RIGHT_SIDEBAR_WIDTH_CONSTRAINTS.max,
      Math.round(shell.clientWidth - sidebarColumn - RIGHT_SIDEBAR_ACTIVITY_BAR_WIDTH),
    );
  };

  // Keep the focused canvas pinned to the full body width across window
  // resizes; in split mode the user's chosen width persists untouched.
  useEffect(() => {
    if (canvasLayout !== 'focus') return;
    const refocus = () => panelWidth.resize(measureFocusPanelWidth());
    window.addEventListener('resize', refocus);
    return () => window.removeEventListener('resize', refocus);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvasLayout]);

  // Capture the canvas trigger that opened the panel so closing the canvas
  // can return focus to it, wherever it lives (thread pane or context rail).
  useEffect(() => {
    if (effectivePanel !== 'canvas') return;
    if (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement) {
      canvasTriggerRef.current =
        document.activeElement.dataset.sessionCanvasTrigger ?? canvasTriggerRef.current;
    }
  }, [effectivePanel]);

  const canvasControls: SessionCanvasControls = {
    layout: canvasLayout,
    onLayoutChange: (layout) => {
      setCanvasLayout(layout);
      if (layout === 'focus') panelWidth.resize(measureFocusPanelWidth());
      else panelWidth.reset();
    },
    onClose: () => {
      onCloseCanvas();
      const triggerId = canvasTriggerRef.current;
      if (triggerId && typeof window !== 'undefined') {
        window.requestAnimationFrame(() => {
          const triggers = document.querySelectorAll<HTMLButtonElement>(
            '[data-session-canvas-trigger]',
          );
          for (const trigger of triggers) {
            if (trigger.dataset.sessionCanvasTrigger !== triggerId) continue;
            trigger.focus();
            break;
          }
        });
      }
    },
  };

  const canvasContent =
    effectivePanel === 'canvas' && canvas.kind === 'available' ? (
      <DesktopRendererSessionCanvasV2 input={canvas.input} controls={canvasControls} />
    ) : null;

  const panelTitle =
    effectivePanel === 'canvas'
      ? t('rightbar.canvas')
      : effectivePanel === 'browser'
        ? t('rightbar.browser')
        : t('rightbar.context');

  return (
    <aside className="desktop-right-sidebar" aria-label={panelTitle} ref={hostRef}>
      <div
        className="desktop-right-sidebar-panel"
        style={{ width: `${Math.round(panelWidth.width)}px` }}
      >
        <ResizeHandle
          side="leading"
          width={panelWidth.width}
          constraints={widthConstraints}
          label={t('rightbar.resize')}
          onResize={panelWidth.resize}
          onReset={panelWidth.reset}
        />
        <header className="desktop-right-sidebar-head">
          <strong>{panelTitle}</strong>
          <button
            type="button"
            aria-label={t('rightbar.close')}
            title={t('rightbar.close')}
            onClick={onClose}
          >
            <Cross2Icon />
          </button>
        </header>
        <div className="desktop-right-sidebar-content">
          {effectivePanel === 'canvas' ? (
            <div className="desktop-right-sidebar-canvas">{canvasContent}</div>
          ) : effectivePanel === 'browser' ? (
            <BrowserPanel />
          ) : viewModel !== null ? (
            <SessionContextRail
              viewModel={viewModel}
              runActionPending={runActionPending}
              onRunAction={onRunAction}
              onOpenCanvas={onOpenCanvas}
            />
          ) : null}
        </div>
      </div>
      <nav className="desktop-right-activity-bar">
        <button
          type="button"
          aria-label={t('rightbar.context')}
          aria-pressed={effectivePanel === 'context'}
          title={t('rightbar.context')}
          disabled={viewModel === null}
          onClick={() => onSelectPanel('context')}
        >
          <ReaderIcon />
        </button>
        <button
          type="button"
          aria-label={t('rightbar.canvas')}
          aria-pressed={effectivePanel === 'canvas'}
          title={t('rightbar.canvas')}
          disabled={canvas.kind === 'unavailable' || viewModel === null}
          onClick={() => onSelectPanel('canvas')}
        >
          <LayoutIcon />
        </button>
        <button
          type="button"
          aria-label={t('rightbar.browser')}
          aria-pressed={effectivePanel === 'browser'}
          title={t('rightbar.browser')}
          onClick={() => onSelectPanel('browser')}
        >
          <GlobeIcon />
        </button>
      </nav>
    </aside>
  );
}
