import type { ChromeApi, MessageSenderLike } from '../chrome-api';

export const CURSOR_CONTENT_SCRIPT_FILE = 'content-scripts/cursor.js';
export const ARRIVAL_TIMEOUT_MS = 1500;
export const PUBLISH_TIMEOUT_MS = 1000;

export const CURSOR_MESSAGE_TYPES = {
  ping: 'AGENT_CURSOR_PING',
  state: 'AGENT_CURSOR_STATE',
  arrived: 'AGENT_CURSOR_ARRIVED',
  getState: 'GET_AGENT_CURSOR_STATE',
} as const;

export interface CursorState {
  visible: boolean;
  x: number;
  y: number;
  animateMovement: boolean;
  moveSequence: number;
}

interface ArrivalWaiter {
  resolve: () => void;
  timer: ReturnType<typeof setTimeout>;
}

/**
 * Service-worker half of the virtual cursor handshake (design §2.7).
 * Publishes cursor state to the per-tab content script and gates real
 * Input dispatch on the visual arrival, with two circuit breakers
 * (publish 1s, arrival 1.5s) — every path resolves, none rejects.
 */
export function createCursorManager(chrome: ChromeApi) {
  const states = new Map<number, CursorState>();
  const waiters = new Map<string, ArrivalWaiter>();
  let moveSequence = 0;

  function waiterKey(tabId: number, sequence: number): string {
    return `${tabId}:${sequence}`;
  }

  function resolveWaiter(key: string): void {
    const waiter = waiters.get(key);
    if (!waiter) return;
    waiters.delete(key);
    clearTimeout(waiter.timer);
    waiter.resolve();
  }

  function createWaiter(tabId: number, sequence: number): Promise<void> {
    const key = waiterKey(tabId, sequence);
    return new Promise<void>((resolve) => {
      const timer = setTimeout(() => resolveWaiter(key), ARRIVAL_TIMEOUT_MS);
      waiters.set(key, { resolve, timer });
    });
  }

  async function isObserved(tabId: number): Promise<boolean> {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.active !== true || typeof tab.windowId !== 'number') return false;
      const window = await chrome.windows.get(tab.windowId);
      return window.type === 'normal' && window.state !== 'minimized';
    } catch {
      return false;
    }
  }

  async function ensureInjected(tabId: number): Promise<void> {
    try {
      await chrome.tabs.sendMessage(tabId, { type: CURSOR_MESSAGE_TYPES.ping });
    } catch {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: [CURSOR_CONTENT_SCRIPT_FILE],
      });
    }
  }

  /**
   * Deliver state to the tab with a 1s publish breaker.
   * Throws on failure — callers turn that into "resolve the waiter now".
   */
  async function publish(tabId: number, state: CursorState): Promise<void> {
    states.set(tabId, state);
    await ensureInjected(tabId);
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        chrome.tabs.sendMessage(tabId, { type: CURSOR_MESSAGE_TYPES.state, state }),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => reject(new Error('cursor publish timeout')), PUBLISH_TIMEOUT_MS);
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  /** moveMouse: animate when observed and waitForArrival, else teleport. */
  async function moveMouse(params: {
    tabId: number;
    x: number;
    y: number;
    waitForArrival: boolean;
  }): Promise<void> {
    const { tabId, x, y } = params;
    const observed = params.waitForArrival && (await isObserved(tabId));
    moveSequence += 1;
    const sequence = moveSequence;
    const state: CursorState = {
      visible: true,
      x,
      y,
      animateMovement: observed,
      moveSequence: sequence,
    };
    if (!observed) {
      await publish(tabId, state).catch(() => {
        /* teleport is best-effort; the client swallows errors anyway */
      });
      return;
    }
    const waiter = createWaiter(tabId, sequence);
    try {
      await publish(tabId, state);
    } catch {
      resolveWaiter(waiterKey(tabId, sequence)); // publish failure → arrive now
    }
    await waiter; // arrival timeout resolves; never rejects
  }

  /** Best-effort hide for tabs (turnEnded cleanup). */
  function hideTabs(tabIds: number[]): void {
    for (const tabId of tabIds) {
      const current = states.get(tabId);
      if (!current || !current.visible) continue;
      void publish(tabId, { ...current, visible: false }).catch(() => {
        /* tab may be gone */
      });
    }
  }

  /** Forget a tab entirely (tab closed). */
  function clearTab(tabId: number): void {
    states.delete(tabId);
  }

  /** Native-port disconnect kill-switch: hide everything, drop all state. */
  function clearAll(): void {
    const tabIds = [...states.keys()];
    hideTabs(tabIds);
    states.clear();
    for (const key of [...waiters.keys()]) resolveWaiter(key);
  }

  /**
   * chrome.runtime.onMessage hook for the cursor content script.
   * Returns the sendResponse value semantics: true when async (never today).
   */
  function handleMessage(
    message: unknown,
    sender: MessageSenderLike,
    sendResponse: (response?: unknown) => void,
  ): boolean | undefined {
    if (typeof message !== 'object' || message === null) return undefined;
    const type = (message as Record<string, unknown>).type;
    const tabId = sender.tab?.id;
    if (type === CURSOR_MESSAGE_TYPES.arrived && typeof tabId === 'number') {
      const sequence = (message as Record<string, unknown>).moveSequence;
      if (typeof sequence === 'number') resolveWaiter(waiterKey(tabId, sequence));
      return undefined;
    }
    if (type === CURSOR_MESSAGE_TYPES.getState) {
      const state = typeof tabId === 'number' ? states.get(tabId) : undefined;
      sendResponse(state ?? { visible: false, x: 0, y: 0, animateMovement: false, moveSequence: 0 });
      return undefined;
    }
    return undefined;
  }

  return {
    moveMouse,
    hideTabs,
    clearTab,
    clearAll,
    handleMessage,
    getState: (tabId: number) => states.get(tabId),
  };
}

export type CursorManager = ReturnType<typeof createCursorManager>;
