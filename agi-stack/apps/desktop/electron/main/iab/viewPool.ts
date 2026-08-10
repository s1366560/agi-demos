/**
 * iab WebContentsView pool.
 *
 * One `WebContentsView` per tab, all sharing `session.fromPartition(
 * 'persist:memstack-iab')` so login state is shared by design. Views are
 * sandboxed (contextIsolation, sandbox, no nodeIntegration) with the minimal
 * `iabPreload` that exposes nothing by default. tabIds are iab-local
 * incrementing integers (`IabTabRegistry`); the sidecar namespaces by
 * backend, so no global coordination is needed.
 *
 * The pool also owns:
 *  - the navigation policy wiring (`iabNavigationPolicy.ts`),
 *  - per-tab CDP debugger sessions (`webContents.debugger`, protocol 1.3)
 *    with a 20s command timeout and event/detach forwarding,
 *  - pane attachment: the active tab's view is added to the host window's
 *    content view at renderer-reported bounds; hiding the panel zeroes the
 *    bounds but keeps the view alive for the agent.
 */

import { WebContentsView, session, type BrowserWindow, type WebContents } from 'electron';

import { IabCursorController } from './iabCursor';
import { buildIabInputScript, isIabSynthesizedInputMethod } from './iabInputTranslation';
import {
  evaluateIabNavigation,
  evaluateIabWindowOpen,
  isIabPermissionAllowed,
} from './iabNavigationPolicy';
import { IabTabRegistry, type IabTurnEndedLease } from './iabTabRegistry';

export const IAB_SESSION_PARTITION = 'persist:memstack-iab';
export const IAB_CDP_TIMEOUT_MS = 20_000;
export const IAB_WINDOW_ID = 1;

export type IabTabSnapshot = Readonly<{
  tabId: number;
  windowId: number;
  title: string;
  url: string;
  active: boolean;
}>;

export type IabPaneBounds = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
}>;

export type IabViewPoolOptions = Readonly<{
  preloadPath: string;
  cursorScriptPath: () => string;
  onTabsChanged?: () => void;
  onCdpEvent?: (tabId: number, method: string, params: unknown) => void;
  onCdpDetach?: (tabId: number, reason: string) => void;
}>;

type IabTabEntry = {
  view: WebContentsView;
  debuggerAttached: boolean;
};

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`${label} timed out after ${ms}ms`));
    }, ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(String(error)));
      },
    );
  });
}

export class IabViewPool {
  readonly registry = new IabTabRegistry();
  readonly cursor: IabCursorController;
  readonly #options: IabViewPoolOptions;
  readonly #tabs = new Map<number, IabTabEntry>();
  #activeTabId: number | null = null;
  #hostWindow: BrowserWindow | null = null;
  #paneVisible = false;
  #paneBounds: IabPaneBounds = Object.freeze({ x: 0, y: 0, width: 0, height: 0 });

  constructor(options: IabViewPoolOptions) {
    this.#options = options;
    this.cursor = new IabCursorController(options.cursorScriptPath);
  }

  setHostWindow(window: BrowserWindow | null): void {
    this.#hostWindow = window;
    this.#layoutActiveView();
  }

  get activeTabId(): number | null {
    return this.#activeTabId;
  }

  #entry(tabId: number): IabTabEntry {
    const entry = this.#tabs.get(tabId);
    if (!entry || entry.view.webContents.isDestroyed()) {
      throw new Error(`iab tab ${tabId} does not exist`);
    }
    return entry;
  }

  webContentsFor(tabId: number): WebContents {
    return this.#entry(tabId).view.webContents;
  }

  async createTab(url?: string | null): Promise<number> {
    const target = url ?? 'about:blank';
    const navigation = evaluateIabNavigation(target);
    if (!navigation.allowed) {
      throw new Error(`iab navigation denied: ${navigation.reasonCode}`);
    }
    const view = new WebContentsView({
      webPreferences: {
        preload: this.#options.preloadPath,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
        session: session.fromPartition(IAB_SESSION_PARTITION),
      },
    });
    const tabId = this.registry.createTab();
    const entry: IabTabEntry = { view, debuggerAttached: false };
    this.#tabs.set(tabId, entry);
    this.#installPolicy(tabId, view);
    if (this.#activeTabId === null) this.#activeTabId = tabId;
    this.#layoutActiveView();
    this.#emitTabsChanged();
    try {
      await view.webContents.loadURL(target);
    } catch (error) {
      // about:blank cannot fail; a failing initial URL still yields a live
      // tab (mirrors a browser opening a tab to an unreachable page).
      if (target !== 'about:blank') {
        await view.webContents.loadURL('about:blank').catch(() => undefined);
        this.#emitTabsChanged();
      } else {
        this.closeTab(tabId);
        throw error instanceof Error ? error : new Error(String(error));
      }
    }
    return tabId;
  }

  closeTab(tabId: number): void {
    const entry = this.#tabs.get(tabId);
    if (!entry) throw new Error(`iab tab ${tabId} does not exist`);
    this.#detachFromWindow(entry);
    this.#tabs.delete(tabId);
    this.registry.removeTab(tabId);
    this.cursor.discardTab(tabId);
    if (!entry.view.webContents.isDestroyed()) {
      entry.view.webContents.close();
    }
    if (this.#activeTabId === tabId) {
      const remaining = this.registry.listTabIds();
      this.#activeTabId = remaining.length > 0 ? remaining[remaining.length - 1]! : null;
    }
    this.#layoutActiveView();
    this.#emitTabsChanged();
  }

  focusTab(tabId: number): void {
    this.#entry(tabId);
    this.#activeTabId = tabId;
    this.#layoutActiveView();
    this.#emitTabsChanged();
  }

  getTabs(): IabTabSnapshot[] {
    const snapshots: IabTabSnapshot[] = [];
    for (const [tabId, entry] of this.#tabs) {
      const webContents = entry.view.webContents;
      snapshots.push(
        Object.freeze({
          tabId,
          windowId: IAB_WINDOW_ID,
          title: webContents.isDestroyed() ? '' : webContents.getTitle(),
          url: webContents.isDestroyed() ? 'about:blank' : webContents.getURL(),
          active: tabId === this.#activeTabId,
        }),
      );
    }
    return snapshots;
  }

  /** Idempotent: attaching an already-attached tab is a no-op. */
  attachDebugger(tabId: number): void {
    const entry = this.#entry(tabId);
    if (entry.debuggerAttached) return;
    const tabDebug = entry.view.webContents.debugger;
    try {
      tabDebug.attach('1.3');
    } catch (error) {
      throw new Error(
        `iab debugger attach failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    entry.debuggerAttached = true;
    tabDebug.on('message', (_event, method, params: unknown) => {
      this.#options.onCdpEvent?.(tabId, method, params);
    });
    tabDebug.on('detach', (_event, reason) => {
      entry.debuggerAttached = false;
      this.#options.onCdpDetach?.(tabId, reason);
    });
  }

  detachDebugger(tabId: number): void {
    const entry = this.#entry(tabId);
    if (!entry.debuggerAttached) return;
    entry.debuggerAttached = false;
    try {
      entry.view.webContents.debugger.detach();
    } catch {
      // A racing target-close also ends the session; both paths are clean.
    }
  }

  isDebuggerAttached(tabId: number): boolean {
    return this.#tabs.get(tabId)?.debuggerAttached === true;
  }

  /**
   * Run one CDP command. Input.* methods are translated to in-page
   * synthesized events (never sent over the debugger); everything else goes
   * through the debugger with the 20s contract timeout. Auto-attaches on
   * first use.
   */
  async executeCdp(tabId: number, method: string, params: unknown): Promise<unknown> {
    const entry = this.#entry(tabId);
    if (isIabSynthesizedInputMethod(method)) {
      const script = buildIabInputScript(method, params);
      if (script === null) throw new Error(`iab cannot translate input method: ${method}`);
      const result: unknown = await withTimeout(
        entry.view.webContents.executeJavaScript(script, true) as Promise<unknown>,
        IAB_CDP_TIMEOUT_MS,
        `iab input synthesis ${method}`,
      );
      return result;
    }
    this.attachDebugger(tabId);
    return withTimeout(
      entry.view.webContents.debugger.sendCommand(method, params as object | undefined),
      IAB_CDP_TIMEOUT_MS,
      `iab CDP command ${method}`,
    );
  }

  /** End-of-turn disposition; returns the contract `{closed, ungrouped}`. */
  turnEnded(leases: readonly IabTurnEndedLease[]): { closed: number; ungrouped: number } {
    const plan = this.registry.planTurnEnded(leases);
    let closed = 0;
    let ungrouped = 0;
    for (const tabId of plan.closeTabIds) {
      try {
        this.closeTab(tabId);
        closed += 1;
      } catch {
        // A tab closed out from under the turn is already at its end state.
      }
    }
    for (const tabId of plan.ungroupTabIds) {
      try {
        if (this.registry.ungroupTab(tabId)) ungrouped += 1;
      } catch {
        // Unknown tabs were reported in the plan; nothing else to do.
      }
    }
    return { closed, ungrouped };
  }

  /** Renderer pane plumbing: show/hide/relayout the active tab's view. */
  showPane(bounds: IabPaneBounds): void {
    this.#paneVisible = true;
    this.#paneBounds = sanitizeBounds(bounds);
    this.#layoutActiveView();
  }

  setPaneBounds(bounds: IabPaneBounds): void {
    this.#paneBounds = sanitizeBounds(bounds);
    if (this.#paneVisible) this.#layoutActiveView();
  }

  hidePane(): void {
    this.#paneVisible = false;
    const active = this.#activeEntry();
    // The view keeps running for the agent; only its bounds go to zero.
    if (active) active.view.setBounds({ x: 0, y: 0, width: 0, height: 0 });
  }

  destroyAll(): void {
    for (const [tabId] of this.#tabs) {
      try {
        this.closeTab(tabId);
      } catch {
        // Shutdown must not throw.
      }
    }
  }

  #activeEntry(): IabTabEntry | null {
    if (this.#activeTabId === null) return null;
    return this.#tabs.get(this.#activeTabId) ?? null;
  }

  #detachFromWindow(entry: IabTabEntry): void {
    const window = this.#hostWindow;
    if (!window || window.isDestroyed()) return;
    try {
      window.contentView.removeChildView(entry.view);
    } catch {
      // The view may not be attached; removal is best-effort.
    }
  }

  #layoutActiveView(): void {
    const window = this.#hostWindow;
    if (!window || window.isDestroyed()) return;
    const active = this.#activeEntry();
    // Detach every non-active view; only the active tab is on screen.
    for (const [tabId, entry] of this.#tabs) {
      if (tabId !== this.#activeTabId) this.#detachFromWindow(entry);
    }
    if (!active) return;
    try {
      window.contentView.addChildView(active.view);
    } catch {
      // Already attached: addChildView throws on double-add in some versions.
    }
    active.view.setBounds(
      this.#paneVisible ? this.#paneBounds : { x: 0, y: 0, width: 0, height: 0 },
    );
  }

  #installPolicy(tabId: number, view: WebContentsView): void {
    const webContents = view.webContents;
    webContents.setWindowOpenHandler(({ url }) => {
      const decision = evaluateIabWindowOpen(url);
      if (decision.action === 'new-tab' && decision.url !== null) {
        void this.createTab(decision.url).catch(() => undefined);
      }
      return { action: 'deny' };
    });
    webContents.on('will-navigate', (event, url) => {
      if (!evaluateIabNavigation(url).allowed) event.preventDefault();
    });
    webContents.on('will-redirect', (event, url) => {
      if (!evaluateIabNavigation(url).allowed) event.preventDefault();
    });
    webContents.on('console-message', (details) => {
      this.cursor.handleConsoleMessage(tabId, details.message);
    });
    webContents.on('did-navigate', () => this.#emitTabsChanged());
    webContents.on('did-navigate-in-page', () => this.#emitTabsChanged());
    webContents.on('page-title-updated', () => this.#emitTabsChanged());
    webContents.on('destroyed', () => {
      if (this.#tabs.delete(tabId)) {
        this.registry.removeTab(tabId);
        this.cursor.discardTab(tabId);
        if (this.#activeTabId === tabId) {
          const remaining = this.registry.listTabIds();
          this.#activeTabId = remaining.length > 0 ? remaining[remaining.length - 1]! : null;
        }
        this.#layoutActiveView();
        this.#emitTabsChanged();
      }
    });
  }

  #emitTabsChanged(): void {
    try {
      this.#options.onTabsChanged?.();
    } catch {
      // Renderer notification failures must not break pool state.
    }
  }
}

function sanitizeBounds(bounds: IabPaneBounds): IabPaneBounds {
  const component = (value: number): number =>
    Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
  return Object.freeze({
    x: component(bounds.x),
    y: component(bounds.y),
    width: component(bounds.width),
    height: component(bounds.height),
  });
}

/** Installed once per process: iab views get no permission grants. */
export function installIabSessionPermissionPolicy(): void {
  const iabSession = session.fromPartition(IAB_SESSION_PARTITION);
  iabSession.setPermissionCheckHandler(() => isIabPermissionAllowed());
  iabSession.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(isIabPermissionAllowed());
  });
}
