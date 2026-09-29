import { useLayoutEffect, useRef, useState } from 'react';
import { DropdownMenu } from '@radix-ui/themes';
import {
  ColumnsIcon,
  Cross2Icon,
  EnterFullScreenIcon,
  PlusIcon,
  ViewVerticalIcon,
} from '@radix-ui/react-icons';

import { ResizeHandle } from '../../components/ResizeHandle';
import { useI18n } from '../../i18n';
import { BrowserPanel } from '../browser/BrowserPanel';
import { useTimelineInspection } from '../session/TimelineInspectionContext';
import { SessionContextRail } from '../session/SessionContextRail';
import { getSessionWorkPanelOptions } from '../session/sessionWorkPanelOptions';
import type { SessionCanvasTabId } from '../session/sessionCanvasModel';
import type { SessionDetailViewModel, SessionRunAction } from '../session/sessionViewModel';
import { DesktopRendererSessionCanvasV2 } from '../../plugins/DesktopRendererSessionCanvasV2';
import type { DesktopSessionCanvasInputV2 } from '../../plugins/DesktopSessionCanvasSurfaceV2';
import { workPanelGeometry, type WorkPanelState, type WorkPanelTab } from './workPanelState';
import './DesktopRightSidebar.css';

export type DesktopRightSidebarCanvasV2 =
  | Readonly<{ kind: 'available'; input: DesktopSessionCanvasInputV2 }>
  | Readonly<{ kind: 'unavailable' }>;

const WIDTH_KEY = 'agistack.desktop.rightSidebarWidth';

type DesktopRightSidebarProps = {
  state: WorkPanelState;
  canvas: DesktopRightSidebarCanvasV2;
  viewModel: SessionDetailViewModel | null;
  runActionPending: SessionRunAction | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
  onSelectPanel: (panel: WorkPanelTab) => void;
  onCloseTab: (panel: WorkPanelTab) => void;
  onCloseCanvas: () => void;
  onClose: () => void;
};

export function DesktopRightSidebar({
  state,
  canvas,
  viewModel,
  runActionPending,
  onRunAction,
  onOpenCanvas,
  onSelectPanel,
  onCloseTab,
  onClose,
}: DesktopRightSidebarProps) {
  const { t } = useI18n();
  const inspection = useTimelineInspection();
  const hostRef = useRef<HTMLElement>(null);
  const [focused, setFocused] = useState(false);
  const [availableWidth, setAvailableWidth] = useState(1000);
  const [preferredWidth, setPreferredWidth] = useState<number | null>(() => {
    try {
      const value = Number(window.localStorage.getItem(WIDTH_KEY));
      return Number.isFinite(value) && value >= 360 ? value : null;
    } catch {
      return null;
    }
  });
  useLayoutEffect(() => {
    const shell = hostRef.current?.closest('.app-shell');
    if (!(shell instanceof HTMLElement)) return;
    const measure = () => {
      const leftWidth = Number.parseFloat(getComputedStyle(shell).gridTemplateColumns) || 0;
      setAvailableWidth(Math.max(0, shell.clientWidth - leftWidth));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(shell);
    const mutation = new MutationObserver(measure);
    mutation.observe(shell, {
      attributes: true,
      attributeFilter: ['class', 'style'],
    });
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect();
      mutation.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);
  const geometry = workPanelGeometry(availableWidth, preferredWidth, focused);
  useLayoutEffect(() => {
    const main = hostRef.current?.closest('.app-shell')?.querySelector<HTMLElement>('.workbench');
    if (!main || !geometry.fullWidth) return;
    const previous = main.inert;
    const shouldMoveFocus = main.contains(document.activeElement);
    main.inert = true;
    if (shouldMoveFocus) {
      hostRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
    }
    return () => {
      main.inert = previous;
    };
  }, [geometry.fullWidth]);
  useLayoutEffect(() => {
    hostRef.current
      ?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [state.active]);

  const resize = (width: number) => {
    const next = Math.min(geometry.constraints.max, Math.max(geometry.constraints.min, width));
    setPreferredWidth(next);
    try {
      window.localStorage.setItem(WIDTH_KEY, String(Math.round(next)));
    } catch {
      /* Optional preference. */
    }
  };
  const options: {
    id: WorkPanelTab;
    labelKey: string;
    available: boolean;
    reasonKey?: string;
    group: 'work' | 'details';
  }[] = [
    ...(canvas.kind === 'available' ? getSessionWorkPanelOptions(canvas.input.state) : []),
    {
      id: 'browser',
      labelKey: 'rightbar.browser',
      available: true,
      group: 'work',
    },
    {
      id: 'run-details',
      labelKey: 'rightbar.runDetails',
      available: viewModel !== null,
      reasonKey: 'rightbar.noSession',
      group: 'details',
    },
  ];
  const option = options.find((entry) => entry.id === state.active);
  const label = (id: WorkPanelTab) =>
    t(options.find((entry) => entry.id === id)?.labelKey ?? 'rightbar.unavailable');
  const unavailable = !option?.available;
  const active = state.active;
  const closeTab = (id: WorkPanelTab) => {
    if (id === 'activity') inspection.dismiss();
    onCloseTab(id);
    if (state.tabs.length > 1)
      requestAnimationFrame(() => {
        hostRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
      });
  };
  return (
    <aside
      ref={hostRef}
      className={`desktop-right-sidebar${geometry.fullWidth ? ' desktop-right-sidebar-full' : ''}`}
      aria-label={t('rightbar.workspace')}
      style={{ width: Math.round(geometry.width) }}
    >
      {!geometry.fullWidth ? (
        <ResizeHandle
          side="leading"
          width={geometry.width}
          constraints={geometry.constraints}
          label={t('rightbar.resize')}
          onResize={resize}
          onReset={() => resize(geometry.constraints.default)}
        />
      ) : null}
      <header className="desktop-right-sidebar-head">
        <div className="work-panel-tabs" role="tablist" aria-label={t('rightbar.workspace')}>
          {state.tabs.map((id, index) => (
            <div className="work-panel-tab" data-active={id === active} key={id}>
              <button
                type="button"
                role="tab"
                id={`work-panel-tab-${id}`}
                aria-selected={id === active}
                aria-controls="work-panel-content"
                tabIndex={id === active ? 0 : -1}
                title={label(id)}
                onClick={() => onSelectPanel(id)}
                onKeyDown={(event) => {
                  if (event.key === 'Delete') {
                    event.preventDefault();
                    closeTab(id);
                    return;
                  }
                  const next =
                    event.key === 'ArrowRight'
                      ? (index + 1) % state.tabs.length
                      : event.key === 'ArrowLeft'
                        ? (index + state.tabs.length - 1) % state.tabs.length
                        : event.key === 'Home'
                          ? 0
                          : event.key === 'End'
                            ? state.tabs.length - 1
                            : null;
                  if (next === null) return;
                  event.preventDefault();
                  onSelectPanel(state.tabs[next]);
                  document.getElementById(`work-panel-tab-${state.tabs[next]}`)?.focus();
                }}
              >
                {label(id)}
              </button>
              <button
                type="button"
                className="work-panel-tab-close"
                aria-label={t('rightbar.closeTab', { name: label(id) })}
                onClick={() => closeTab(id)}
              >
                <Cross2Icon />
              </button>
            </div>
          ))}
        </div>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <button type="button" aria-label={t('rightbar.addView')} title={t('rightbar.addView')}>
              <PlusIcon />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content className="work-panel-menu" align="end">
            {(['work', 'details'] as const).map((group) => (
              <DropdownMenu.Group key={group}>
                <DropdownMenu.Label>
                  {t(group === 'work' ? 'rightbar.workContent' : 'rightbar.runDetails')}
                </DropdownMenu.Label>
                {options
                  .filter((entry) => entry.group === group)
                  .map((entry) => (
                    <DropdownMenu.Item
                      key={entry.id}
                      disabled={!entry.available}
                      onSelect={() => onSelectPanel(entry.id)}
                    >
                      <span>{t(entry.labelKey)}</span>
                      {!entry.available ? (
                        <small>{t(entry.reasonKey ?? 'rightbar.unavailable')}</small>
                      ) : null}
                    </DropdownMenu.Item>
                  ))}
              </DropdownMenu.Group>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Root>
        {availableWidth >= 840 ? (
          <button
            type="button"
            aria-label={t(focused ? 'session.splitView' : 'session.focusCanvas')}
            title={t(focused ? 'session.splitView' : 'session.focusCanvas')}
            onClick={() => setFocused((value) => !value)}
          >
            {focused ? <ColumnsIcon /> : <EnterFullScreenIcon />}
          </button>
        ) : null}
        <button
          type="button"
          aria-label={t('rightbar.hide')}
          title={t('rightbar.hide')}
          onClick={onClose}
        >
          <ViewVerticalIcon />
        </button>
      </header>
      <div
        className="desktop-right-sidebar-content"
        id="work-panel-content"
        role="tabpanel"
        aria-labelledby={active ? `work-panel-tab-${active}` : undefined}
      >
        {active === 'browser' ? (
          <BrowserPanel />
        ) : active === 'run-details' && viewModel ? (
          <SessionContextRail
            viewModel={viewModel}
            runActionPending={runActionPending}
            onRunAction={onRunAction}
            onOpenCanvas={onOpenCanvas}
          />
        ) : unavailable ? (
          <div className="work-panel-empty" role="status">
            {t(option?.reasonKey ?? 'rightbar.unavailable')}
          </div>
        ) : canvas.kind === 'available' ? (
          <DesktopRendererSessionCanvasV2
            input={canvas.input}
            controls={{
              embedded: true,
              layout: focused ? 'focus' : 'split',
              onLayoutChange: (layout) => setFocused(layout === 'focus'),
              onClose: () => {
                if (active) closeTab(active);
              },
            }}
          />
        ) : null}
      </div>
    </aside>
  );
}
