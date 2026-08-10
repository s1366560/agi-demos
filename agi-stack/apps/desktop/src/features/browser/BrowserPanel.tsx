import { useEffect, useRef, useState } from 'react';

import { Cross2Icon, GlobeIcon, PlusIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import './BrowserPanel.css';

type IabTab = Readonly<{
  tabId: number;
  windowId: number;
  title: string;
  url: string;
  active: boolean;
}>;

function tabLabel(tab: IabTab, untitled: string): string {
  if (tab.title.trim().length > 0) return tab.title;
  try {
    const url = new URL(tab.url);
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.host;
  } catch {
    // about:blank and friends fall through to the untitled label.
  }
  return untitled;
}

/**
 * In-app browser panel: tab strip + read-only address display + a viewport
 * region whose rect is continuously reported to the main process, which maps
 * the active tab's WebContentsView onto it. Hiding (unmount) zeroes the view
 * bounds main-side; the tab keeps running for the agent.
 */
export function BrowserPanel() {
  const { t } = useI18n();
  const bridge = window.__MEMSTACK_DESKTOP__?.iab;
  const [tabs, setTabs] = useState<readonly IabTab[]>([]);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const lastBoundsRef = useRef<string>('');

  useEffect(() => {
    if (!bridge) return undefined;
    let disposed = false;
    bridge
      .listTabs()
      .then((payload) => {
        if (!disposed) setTabs(payload.tabs);
      })
      .catch(() => {});
    const unsubscribe = bridge.onTabsChanged((payload) => {
      setTabs(payload.tabs);
    });
    return () => {
      disposed = true;
      unsubscribe();
    };
  }, [bridge]);

  useEffect(() => {
    if (!bridge) return undefined;
    const element = viewportRef.current;
    if (!element) return undefined;
    const report = (): void => {
      const rect = element.getBoundingClientRect();
      const bounds = {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };
      const key = `${bounds.x},${bounds.y},${bounds.width},${bounds.height}`;
      if (key === lastBoundsRef.current) return;
      lastBoundsRef.current = key;
      void bridge.setBounds(bounds).catch(() => {});
    };
    const rect = element.getBoundingClientRect();
    void bridge
      .showPane({
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      })
      .catch(() => {});
    const observer = new ResizeObserver(report);
    observer.observe(element);
    window.addEventListener('resize', report);
    // Position-only changes (sidebar collapse, window move between displays)
    // fire neither ResizeObserver nor window resize reliably; poll lightly.
    const poll = window.setInterval(report, 1_000);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', report);
      window.clearInterval(poll);
      lastBoundsRef.current = '';
      void bridge.hidePane().catch(() => {});
    };
  }, [bridge]);

  if (!bridge) {
    return (
      <div className="browser-panel browser-panel-unavailable">
        <GlobeIcon />
        <p>{t('browserPanel.unavailable')}</p>
      </div>
    );
  }

  const activeTab = tabs.find((tab) => tab.active) ?? null;

  return (
    <div className="browser-panel">
      <div className="browser-panel-tabs" role="tablist" aria-label={t('rightbar.browser')}>
        {tabs.map((tab) => (
          <button
            key={tab.tabId}
            type="button"
            role="tab"
            aria-selected={tab.active}
            className={
              tab.active ? 'browser-panel-tab browser-panel-tab-active' : 'browser-panel-tab'
            }
            title={tab.url}
            onClick={() => void bridge.focusTab(tab.tabId).catch(() => {})}
          >
            <span className="browser-panel-tab-label">
              {tabLabel(tab, t('browserPanel.untitledTab'))}
            </span>
            <span
              role="button"
              aria-label={t('browserPanel.closeTab')}
              className="browser-panel-tab-close"
              onClick={(event) => {
                event.stopPropagation();
                void bridge.closeTab(tab.tabId).catch(() => {});
              }}
            >
              <Cross2Icon />
            </span>
          </button>
        ))}
        <button
          type="button"
          className="browser-panel-new-tab"
          aria-label={t('browserPanel.newTab')}
          title={t('browserPanel.newTab')}
          onClick={() => void bridge.createTab().catch(() => {})}
        >
          <PlusIcon />
        </button>
      </div>
      <div className="browser-panel-address" title={activeTab?.url ?? ''}>
        <GlobeIcon />
        <span>{activeTab?.url ?? 'about:blank'}</span>
      </div>
      <div className="browser-panel-viewport" ref={viewportRef}>
        {tabs.length === 0 ? (
          <div className="browser-panel-empty">
            <p>{t('browserPanel.empty')}</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
