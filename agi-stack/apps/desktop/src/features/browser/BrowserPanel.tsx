import { useCallback, useEffect, useRef, useState } from 'react';

import { ArrowLeftIcon, ArrowRightIcon, Cross2Icon, GlobeIcon, PlusIcon, ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import './BrowserPanel.css';

type IabTab = Readonly<{
  tabId: number;
  windowId: number;
  title: string;
  url: string;
  active: boolean;
  canGoBack?: boolean;
  canGoForward?: boolean;
  loading?: boolean;
  ownership?: { sessionId: string; origin: 'agent' | 'user'; controller: 'agent' | 'user'; callerId: string | null; mark: 'handoff' | 'deliverable' | null };
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
export function BrowserPanel({ conversationId }: Readonly<{ conversationId?: string }> = {}) {
  const { t } = useI18n();
  const bridge = window.__MEMSTACK_DESKTOP__?.iab;
  const [tabs, setTabs] = useState<readonly IabTab[]>([]);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const lastBoundsRef = useRef<string>('');
  const mounted = useRef(false);
  const [loaded, setLoaded] = useState(false);
  const [failure, setFailure] = useState<{ key: string; retry: () => Promise<unknown> } | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [connection, setConnection] = useState('connecting');
  const [contextReady, setContextReady] = useState(false);
  const [group, setGroup] = useState('all');
  const [address, setAddress] = useState<string | null>(null);
  const activeTab = tabs.find(tab => tab.active) ?? null;
  const sessions = [...new Set(tabs.flatMap(tab => tab.ownership ? [tab.ownership.sessionId] : []))];
  const shownTabs = group === 'all' ? tabs : tabs.filter(tab => tab.ownership?.sessionId === group);
  useEffect(() => { setAddress(null); }, [activeTab?.tabId, activeTab?.url]);
  const perform = useCallback(async (action: () => Promise<unknown>, key: string) => {
    try {
      await action();
      return true;
    } catch {
      if (mounted.current) setFailure({ key, retry: action });
      return false;
    }
  }, []);

  useEffect(() => {
    if (!bridge) return undefined;
    mounted.current = true;
    let disposed = false;
    let revision = 0;
    setLoaded(false);
    const load = async () => {
      const requestRevision = revision;
      try {
        const payload = await bridge.listTabs();
        if (!disposed && requestRevision === revision) {
          setTabs(payload.tabs);
          setLoaded(true);
        }
      } catch (error) {
        if (!disposed && requestRevision === revision) throw error;
      }
    };
    const refresh = async () => {
      await load();
      const status = await bridge.status();
      if (!disposed) {
        setConnection(status.status);
        setContextReady(status.contextReady !== false);
        setFailure(current => current?.key === 'browserPanel.loadFailed' ? null : current);
      }
    };
    void perform(refresh, 'browserPanel.loadFailed');
    const timer = window.setInterval(() => void perform(refresh, 'browserPanel.loadFailed'), 3000);
    const unsubscribe = bridge.onTabsChanged((payload) => {
      if (disposed) return;
      revision += 1;
      setTabs(payload.tabs);
      setLoaded(true);
      setFailure((current) => current?.key === 'browserPanel.loadFailed' ? null : current);
    });
    return () => {
      mounted.current = false;
      disposed = true;
      unsubscribe();
      window.clearInterval(timer);
    };
  }, [bridge, perform]);

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
      void perform(() => bridge.setBounds(bounds), 'browserPanel.displayFailed');
    };
    const rect = element.getBoundingClientRect();
    void perform(() => bridge.showPane({
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      }), 'browserPanel.displayFailed');
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
  }, [bridge, perform]);

  if (!bridge) {
    return (
      <div className="browser-panel browser-panel-unavailable">
        <GlobeIcon />
        <p>{t('browserPanel.unavailable')}</p>
      </div>
    );
  }

  return (
    <div className="browser-panel">
      <div className="browser-panel-session">
        <select aria-label={t('browserPanel.session')} value={group} onChange={event => {
          const next = event.target.value;
          setGroup(next);
          const first = tabs.find(tab => next === 'all' || tab.ownership?.sessionId === next);
          if (first) void perform(() => bridge.focusTab(first.tabId), 'browserPanel.actionFailed');
        }}>
          <option value="all">{t('browserPanel.allSessions')}</option>
          {sessions.map(id => <option key={id} value={id}>{id === conversationId ? t('browserPanel.currentSession') : t('browserPanel.sessionName', { id: id.slice(0, 12) })}</option>)}
        </select>
        <span role="status">{t(!contextReady ? 'browserPanel.contextPending' : connection === 'connected' ? 'browserPanel.connected' : 'browserPanel.reconnecting')}</span>
      </div>
      <div className="browser-panel-tabs" role="tablist" aria-label={t('rightbar.browser')}>
        {shownTabs.map((tab) => (
          <button
            key={tab.tabId}
            type="button"
            role="tab"
            aria-selected={tab.active}
            className={
              tab.active ? 'browser-panel-tab browser-panel-tab-active' : 'browser-panel-tab'
            }
            title={tab.url}
            onClick={() => void perform(() => bridge.focusTab(tab.tabId), 'browserPanel.actionFailed')}
          >
            <span className="browser-panel-tab-label">
              {tabLabel(tab, t('browserPanel.untitledTab'))}
            </span>
            <span
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                event.stopPropagation();
                void perform(() => bridge.closeTab(tab.tabId), 'browserPanel.actionFailed');
              }}
              aria-label={t('browserPanel.closeTab')}
              className="browser-panel-tab-close"
              onClick={(event) => {
                event.stopPropagation();
                void perform(() => bridge.closeTab(tab.tabId), 'browserPanel.actionFailed');
              }}
            >
              <Cross2Icon />
            </span>
          </button>
        ))}
        <button
          type="button"
          className="browser-panel-new-tab"
          disabled={!contextReady}
          aria-label={t('browserPanel.newTab')}
          title={t('browserPanel.newTab')}
          onClick={() => void perform(() => bridge.createTab(), 'browserPanel.actionFailed')}
        >
          <PlusIcon />
        </button>
      </div>
      <div>
      {failure ? (
        <div role="alert" className="browser-panel-error">
          <span>{t(failure.key)}</span>
          <button type="button" disabled={retrying} onClick={async () => {
            setRetrying(true);
            const pending = failure;
            if (await perform(pending.retry, pending.key)) {
              setFailure((current) => current === pending ? null : current);
            }
            if (mounted.current) setRetrying(false);
          }}>{t('common.retry')}</button>
        </div>
      ) : null}
      <form className="browser-panel-address" onSubmit={event => {
        event.preventDefault();
        if (!activeTab) return;
        const value = (address ?? activeTab.url).trim();
        if (!value) return;
        const url = URL.canParse(value) ? value : `https://${value}`;
        void perform(() => bridge.navigateTab(activeTab.tabId, url), 'browserPanel.actionFailed');
      }}>
        <button type="button" aria-label={t('browserPanel.back')} disabled={!activeTab?.canGoBack}
          onClick={() => activeTab && void perform(() => bridge.navigateHistory(activeTab.tabId, 'back'), 'browserPanel.actionFailed')}><ArrowLeftIcon /></button>
        <button type="button" aria-label={t('browserPanel.forward')} disabled={!activeTab?.canGoForward}
          onClick={() => activeTab && void perform(() => bridge.navigateHistory(activeTab.tabId, 'forward'), 'browserPanel.actionFailed')}><ArrowRightIcon /></button>
        <button type="button" aria-label={t('browserPanel.reload')} disabled={!activeTab}
          onClick={() => activeTab && void perform(() => bridge.navigateHistory(activeTab.tabId, 'reload'), 'browserPanel.actionFailed')}><ReloadIcon /></button>
        <input aria-label={t('browserPanel.address')} value={address ?? activeTab?.url ?? ''} disabled={!activeTab}
          onChange={event => setAddress(event.target.value)} onFocus={event => event.target.select()} />
        <button type="submit" disabled={!activeTab}>{t('browserPanel.go')}</button>
      </form>
      {activeTab?.ownership ? <div className="browser-panel-ownership">
        <span>{t(activeTab.ownership.controller === 'agent' ? 'browserPanel.agentControl' : 'browserPanel.userControl')}</span>
        {activeTab.ownership.mark ? <span>{t(`browserPanel.${activeTab.ownership.mark}`)}</span> : null}
        {activeTab.ownership.controller === 'agent' ? <button type="button" onClick={() => void perform(() => bridge.takeOver(activeTab.tabId), 'browserPanel.actionFailed')}>{t('browserPanel.takeOver')}</button> : null}
      </div> : null}
      </div>
      <div className="browser-panel-viewport" ref={viewportRef}>
        {!loaded && !failure ? <p role="status">{t('common.loading')}</p> : null}
        {loaded && !failure && tabs.length === 0 ? (
          <div className="browser-panel-empty">
            <p>{t('browserPanel.empty')}</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
