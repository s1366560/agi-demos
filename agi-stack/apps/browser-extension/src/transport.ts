import type { ChromeApi, NativePort } from './chrome-api';
import type { Bridge } from './handlers';
import { notification } from './protocol';

export const NATIVE_HOST_NAME = 'com.memstack.browserbridge';
export const RECONNECT_ALARM = 'native-reconnect';
export const RECONNECT_FAST_ALARM = 'native-reconnect-fast';
export const RECONNECT_PERIOD_MINUTES = 0.5;
export const FAST_RETRY_DELAY_MINUTES = 5 / 60; // ~5s first retry

export const STATUS_STORAGE_KEY = 'memstackNativeStatus';

export interface NativeStatus {
  connected: boolean;
  lastError: string | null;
  lastConnectedAt: string | null;
  updatedAt: string;
}

/**
 * Native-port state machine. Owns the port lifecycle, the disconnect
 * kill-switch, alarm-based reconnect, and debugger-event relay.
 */
export function startNativeTransport(chrome: ChromeApi, bridge: Bridge): void {
  let port: NativePort | null = null;
  let lastConnectedAt: string | null = null;

  function setStatus(status: NativeStatus): void {
    void chrome.storage.local.set({ [STATUS_STORAGE_KEY]: status });
  }

  function notify(method: string, params: unknown): void {
    if (!port) return;
    try {
      port.postMessage(notification(method, params));
    } catch {
      /* port went away mid-send */
    }
  }

  function scheduleReconnect(): void {
    void chrome.alarms.create(RECONNECT_ALARM, { periodInMinutes: RECONNECT_PERIOD_MINUTES });
    void chrome.alarms.create(RECONNECT_FAST_ALARM, { delayInMinutes: FAST_RETRY_DELAY_MINUTES });
  }

  function connect(): void {
    if (port) return;
    let connectedPort: NativePort;
    try {
      connectedPort = chrome.runtime.connectNative(NATIVE_HOST_NAME);
    } catch {
      scheduleReconnect();
      return;
    }
    port = connectedPort;

    void chrome.alarms.clear(RECONNECT_ALARM);
    void chrome.alarms.clear(RECONNECT_FAST_ALARM);

    // The sidecar re-issues `attach` after reconnecting; drop stale state.
    bridge.clearAttachState();

    connectedPort.onMessage.addListener((message: unknown) => {
      void bridge.dispatch(message).then((response) => {
        if (!response) return;
        try {
          connectedPort.postMessage(response);
        } catch {
          /* port went away mid-send */
        }
      });
    });

    connectedPort.onDisconnect.addListener(() => {
      if (port !== connectedPort) return;
      port = null;
      const lastError = chrome.runtime.lastError?.message ?? null;
      // Kill-switch: never leave debuggers attached without a broker.
      void bridge.detachAll();
      // Also drop every virtual cursor: states, waiters, on-page overlays.
      bridge.clearCursorStates();
      setStatus({ connected: false, lastError, lastConnectedAt, updatedAt: new Date().toISOString() });
      scheduleReconnect();
    });

    lastConnectedAt = new Date().toISOString();
    setStatus({ connected: true, lastError: null, lastConnectedAt, updatedAt: lastConnectedAt });
  }

  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === RECONNECT_ALARM || alarm.name === RECONNECT_FAST_ALARM) connect();
  });

  chrome.debugger.onEvent.addListener((source, method, params) => {
    if (typeof source?.tabId !== 'number') return;
    notify('onCDPEvent', { tabId: source.tabId, method, params });
  });

  chrome.debugger.onDetach.addListener((source, reason) => {
    if (typeof source?.tabId !== 'number') return;
    bridge.attachedTabs.delete(source.tabId);
    notify('onCDPDetach', { tabId: source.tabId, reason });
  });

  chrome.runtime.onStartup.addListener(connect);
  chrome.runtime.onInstalled.addListener(connect);

  connect();
}
