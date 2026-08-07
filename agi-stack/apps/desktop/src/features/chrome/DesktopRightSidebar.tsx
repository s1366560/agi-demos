import { useEffect, useRef, useState, type ReactNode } from 'react';

import { Cross2Icon, LayoutIcon, ReaderIcon } from '@radix-ui/react-icons';

import { ResizeHandle, useResizablePanelWidth } from '../../components/ResizeHandle';
import { useI18n } from '../../i18n';
import { SessionContextRail } from '../session/SessionContextRail';
import type { SessionCanvasTabId } from '../session/sessionCanvasModel';
import type {
  SessionDetailViewModel,
  SessionRunAction,
} from '../session/sessionViewModel';
import type { SessionCanvasControls } from '../session/workspaceReviewPanelModel';
import './DesktopRightSidebar.css';

export type DesktopRightPanel = 'context' | 'canvas';

const RIGHT_SIDEBAR_WIDTH_STORAGE_KEY = 'agistack.desktop.rightSidebarWidth';
const RIGHT_SIDEBAR_WIDTH_CONSTRAINTS = { min: 220, max: 520, default: 280 } as const;

type DesktopRightSidebarProps = {
  activePanel: DesktopRightPanel;
  canvasAvailable: boolean;
  viewModel: SessionDetailViewModel;
  runActionPending: SessionRunAction | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
  onSelectPanel: (panel: DesktopRightPanel) => void;
  onCloseCanvas: () => void;
  onClose: () => void;
  renderCanvas: ((controls: SessionCanvasControls) => ReactNode) | null;
};

/**
 * Orca-style right sidebar: a 40px vertical activity bar on the outer edge
 * plus a resizable panel hosting the session context rail or the review
 * canvas. Canvas layout mapping: the old split/focus surfaces become panel
 * widths here — 'focus' widens the panel to the max constraint, 'split'
 * returns it to the default width.
 */
export function DesktopRightSidebar({
  activePanel,
  canvasAvailable,
  viewModel,
  runActionPending,
  onRunAction,
  onOpenCanvas,
  onSelectPanel,
  onCloseCanvas,
  onClose,
  renderCanvas,
}: DesktopRightSidebarProps) {
  const { t } = useI18n();
  const panelWidth = useResizablePanelWidth(
    RIGHT_SIDEBAR_WIDTH_STORAGE_KEY,
    RIGHT_SIDEBAR_WIDTH_CONSTRAINTS,
  );
  const [canvasLayout, setCanvasLayout] = useState<'split' | 'focus'>('split');
  const canvasTriggerRef = useRef<string | null>(null);

  // Capture the canvas trigger that opened the panel so closing the canvas
  // can return focus to it, wherever it lives (thread pane or context rail).
  useEffect(() => {
    if (activePanel !== 'canvas') return;
    if (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement) {
      canvasTriggerRef.current =
        document.activeElement.dataset.sessionCanvasTrigger ?? canvasTriggerRef.current;
    }
  }, [activePanel]);

  const canvasControls: SessionCanvasControls = {
    layout: canvasLayout,
    onLayoutChange: (layout) => {
      setCanvasLayout(layout);
      if (layout === 'focus') panelWidth.resize(RIGHT_SIDEBAR_WIDTH_CONSTRAINTS.max);
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
    activePanel === 'canvas' && canvasAvailable && renderCanvas
      ? renderCanvas(canvasControls)
      : null;

  return (
    <aside className="desktop-right-sidebar" aria-label={t('rightbar.context')}>
      <div
        className="desktop-right-sidebar-panel"
        style={{ width: `${Math.round(panelWidth.width)}px` }}
      >
        <ResizeHandle
          side="leading"
          width={panelWidth.width}
          constraints={RIGHT_SIDEBAR_WIDTH_CONSTRAINTS}
          label={t('rightbar.resize')}
          onResize={panelWidth.resize}
          onReset={panelWidth.reset}
        />
        <header className="desktop-right-sidebar-head">
          <strong>
            {activePanel === 'canvas' ? t('rightbar.canvas') : t('rightbar.context')}
          </strong>
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
          {activePanel === 'canvas' ? (
            <div className="desktop-right-sidebar-canvas">{canvasContent}</div>
          ) : (
            <SessionContextRail
              viewModel={viewModel}
              runActionPending={runActionPending}
              onRunAction={onRunAction}
              onOpenCanvas={onOpenCanvas}
            />
          )}
        </div>
      </div>
      <nav className="desktop-right-activity-bar">
        <button
          type="button"
          aria-label={t('rightbar.context')}
          aria-pressed={activePanel === 'context'}
          title={t('rightbar.context')}
          onClick={() => onSelectPanel('context')}
        >
          <ReaderIcon />
        </button>
        <button
          type="button"
          aria-label={t('rightbar.canvas')}
          aria-pressed={activePanel === 'canvas'}
          title={t('rightbar.canvas')}
          disabled={!canvasAvailable}
          onClick={() => onSelectPanel('canvas')}
        >
          <LayoutIcon />
        </button>
      </nav>
    </aside>
  );
}
