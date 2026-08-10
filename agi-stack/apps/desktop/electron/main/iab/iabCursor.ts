/**
 * Virtual-cursor driver for iab tabs.
 *
 * Injects the compiled agent-cursor content script (built by
 * `apps/browser-extension`, staged to `electron/resources/iab-cursor.js` by
 * `scripts/stage-iab-cursor.mjs`) into a tab on demand via
 * `webContents.executeJavaScript`, then drives it with `moveMouse` state.
 *
 * The packaged script's messaging depends on `chrome.runtime` (it was built
 * as a Chrome extension content script), so the injection installs a minimal
 * shim first: `chrome.runtime.onMessage.addListener` collects the script's
 * listener, `chrome.runtime.sendMessage` answers `GET_AGENT_CURSOR_STATE`
 * from the last dispatched state and bridges `AGENT_CURSOR_ARRIVED` out over
 * a `console.log` prefix (picked up on the main side via the webContents
 * `console-message` event — the simplest reliable channel; no preload
 * coupling and it works in the page's main world). Cross-origin iframes are
 * unsupported, same as synthesized input.
 */

import { readFile } from 'node:fs/promises';

import type { WebContents } from 'electron';

/** Console prefix the page-side shim uses to post cursor bridge messages. */
export const IAB_CURSOR_CONSOLE_PREFIX = '__memstack_cursor__:';

const ARRIVAL_TIMEOUT_MS = 12_000;

const CURSOR_STATE_TYPE = 'AGENT_CURSOR_STATE';
const CURSOR_ARRIVED_TYPE = 'AGENT_CURSOR_ARRIVED';

/** Minimal `chrome.runtime` adapter installed ahead of the packaged script. */
const CURSOR_SHIM_SOURCE = String.raw`
if (!window.__memstackCursorDispatch) {
  const listeners = new Set();
  let lastState = null;
  const chromeShim = {
    runtime: {
      id: 'memstack-iab',
      onMessage: {
        addListener: (listener) => {
          if (typeof listener === 'function') listeners.add(listener);
        },
      },
      sendMessage: (message) => {
        if (message && typeof message === 'object') {
          if (message.type === ${JSON.stringify(CURSOR_ARRIVED_TYPE)}) {
            try {
              console.log(${JSON.stringify(IAB_CURSOR_CONSOLE_PREFIX)} + JSON.stringify(message));
            } catch (error) {
              void error;
            }
            return Promise.resolve(null);
          }
          if (message.type === 'GET_AGENT_CURSOR_STATE') {
            return Promise.resolve(lastState);
          }
        }
        return Promise.resolve(null);
      },
    },
  };
  try {
    if (typeof window.chrome === 'undefined' || !window.chrome || !window.chrome.runtime) {
      Object.defineProperty(window, 'chrome', {
        value: chromeShim,
        configurable: true,
        writable: false,
      });
    }
  } catch (error) {
    void error;
    try {
      window.chrome = window.chrome || chromeShim;
    } catch (assignError) {
      void assignError;
    }
  }
  window.__memstackCursorDispatch = (message) => {
    if (message && message.type === ${JSON.stringify(CURSOR_STATE_TYPE)}) {
      lastState = message.state ?? lastState;
    }
    for (const listener of listeners) {
      try {
        listener(message, {}, () => undefined);
      } catch (error) {
        void error;
      }
    }
  };
}
`;

export type IabCursorArrival = Readonly<{
  moveSequence: number;
}>;

/** Parse one console message; non-cursor logs return null. */
export function parseIabCursorConsoleMessage(message: string): IabCursorArrival | null {
  if (!message.startsWith(IAB_CURSOR_CONSOLE_PREFIX)) return null;
  try {
    const parsed: unknown = JSON.parse(message.slice(IAB_CURSOR_CONSOLE_PREFIX.length));
    if (
      parsed !== null &&
      typeof parsed === 'object' &&
      (parsed as Record<string, unknown>).type === CURSOR_ARRIVED_TYPE &&
      typeof (parsed as Record<string, unknown>).moveSequence === 'number'
    ) {
      return Object.freeze({
        moveSequence: (parsed as { moveSequence: number }).moveSequence,
      });
    }
  } catch {
    // Malformed bridge payloads are ignored.
  }
  return null;
}

type PendingArrival = {
  moveSequence: number;
  resolve: () => void;
  timer: NodeJS.Timeout;
};

/**
 * Per-tab cursor driver. `moveMouse` never rejects: the bridge contract says
 * the handler always succeeds so the cursor can never block agent actions.
 */
export class IabCursorController {
  readonly #scriptSourcePath: () => string;
  #scriptSource: string | null = null;
  #scriptSourceFailed = false;
  #moveSequence = 0;
  readonly #pendingArrivals = new Map<number, PendingArrival[]>();

  constructor(scriptSourcePath: () => string) {
    this.#scriptSourcePath = scriptSourcePath;
  }

  /** Console-message hook: call from the view pool for each iab webContents. */
  handleConsoleMessage(tabId: number, message: string): void {
    const arrival = parseIabCursorConsoleMessage(message);
    if (!arrival) return;
    const pending = this.#pendingArrivals.get(tabId);
    if (!pending) return;
    const remaining: PendingArrival[] = [];
    for (const waiter of pending) {
      if (waiter.moveSequence === arrival.moveSequence) {
        clearTimeout(waiter.timer);
        waiter.resolve();
      } else {
        remaining.push(waiter);
      }
    }
    if (remaining.length === 0) this.#pendingArrivals.delete(tabId);
    else this.#pendingArrivals.set(tabId, remaining);
  }

  /** Drop waiters for a closed tab. */
  discardTab(tabId: number): void {
    const pending = this.#pendingArrivals.get(tabId);
    if (!pending) return;
    for (const waiter of pending) {
      clearTimeout(waiter.timer);
      waiter.resolve();
    }
    this.#pendingArrivals.delete(tabId);
  }

  async #loadScriptSource(): Promise<string | null> {
    if (this.#scriptSource !== null) return this.#scriptSource;
    if (this.#scriptSourceFailed) return null;
    try {
      this.#scriptSource = await readFile(this.#scriptSourcePath(), 'utf8');
      return this.#scriptSource;
    } catch {
      // Missing staged cursor asset: the agent still works, just without the
      // visible cursor. Logged once by the absence of further attempts.
      this.#scriptSourceFailed = true;
      return null;
    }
  }

  async #ensureInjected(webContents: WebContents): Promise<boolean> {
    const source = await this.#loadScriptSource();
    if (source === null || webContents.isDestroyed()) return false;
    try {
      return (await webContents.executeJavaScript(
        `(() => {if (window.__memstackCursorDispatch) return true;\n${CURSOR_SHIM_SOURCE}\n${source}\nreturn true;})()`,
      )) === true;
    } catch {
      return false;
    }
  }

  async moveMouse(
    tabId: number,
    webContents: WebContents,
    x: number,
    y: number,
    waitForArrival: boolean,
  ): Promise<void> {
    try {
      const injected = await this.#ensureInjected(webContents);
      if (!injected || webContents.isDestroyed()) return;
      this.#moveSequence += 1;
      const moveSequence = this.#moveSequence;
      const arrival =
        waitForArrival === true
          ? new Promise<void>((resolve) => {
              const timer = setTimeout(() => {
                this.#removeWaiter(tabId, moveSequence);
                resolve();
              }, ARRIVAL_TIMEOUT_MS);
              const waiters = this.#pendingArrivals.get(tabId) ?? [];
              waiters.push({ moveSequence, resolve, timer });
              this.#pendingArrivals.set(tabId, waiters);
            })
          : null;
      const state = JSON.stringify({
        visible: true,
        x,
        y,
        moveSequence,
        animateMovement: true,
      });
      await webContents.executeJavaScript(
        `window.__memstackCursorDispatch && window.__memstackCursorDispatch({type: ${JSON.stringify(
          CURSOR_STATE_TYPE,
        )}, state: ${state}}), true`,
      );
      if (arrival) await arrival;
    } catch {
      // Cursor failures are swallowed by contract.
    }
  }

  #removeWaiter(tabId: number, moveSequence: number): void {
    const pending = this.#pendingArrivals.get(tabId);
    if (!pending) return;
    const remaining = pending.filter((waiter) => waiter.moveSequence !== moveSequence);
    if (remaining.length === 0) this.#pendingArrivals.delete(tabId);
    else this.#pendingArrivals.set(tabId, remaining);
  }
}
