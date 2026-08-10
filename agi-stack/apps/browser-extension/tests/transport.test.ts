import { describe, expect, it } from 'vitest';
import { createBridge } from '../src/handlers';
import {
  FAST_RETRY_DELAY_MINUTES,
  NATIVE_HOST_NAME,
  RECONNECT_ALARM,
  RECONNECT_FAST_ALARM,
  RECONNECT_PERIOD_MINUTES,
  STATUS_STORAGE_KEY,
  startNativeTransport,
} from '../src/transport';
import { createChromeMock, flush } from './chrome-mock';

function setup() {
  const { chrome, port } = createChromeMock();
  const bridge = createBridge(chrome);
  startNativeTransport(chrome, bridge);
  return { chrome, port, bridge };
}

describe('native transport lifecycle', () => {
  it('connects to the pinned native host on startup and records status', () => {
    const { chrome } = setup();
    expect(chrome.runtime.connectNative).toHaveBeenCalledWith(NATIVE_HOST_NAME);
    expect(chrome.alarms.clear).toHaveBeenCalledWith(RECONNECT_ALARM);
    expect(chrome.alarms.clear).toHaveBeenCalledWith(RECONNECT_FAST_ALARM);
    expect(chrome.storage.local.set).toHaveBeenCalledWith({
      [STATUS_STORAGE_KEY]: expect.objectContaining({ connected: true, lastError: null }),
    });
  });

  it('round-trips a request and posts the response with the matching id', async () => {
    const { port } = setup();
    port.onMessage.fire({ jsonrpc: '2.0', id: 'abc', method: 'ping' });
    await flush();
    expect(port.postMessage).toHaveBeenCalledWith({ jsonrpc: '2.0', id: 'abc', result: {} });
  });

  it('posts the error response for unknown methods', async () => {
    const { port } = setup();
    port.onMessage.fire({ jsonrpc: '2.0', id: 9, method: 'bogus' });
    await flush();
    expect(port.postMessage).toHaveBeenCalledWith({
      jsonrpc: '2.0',
      id: 9,
      error: { code: -32601, message: 'unknown method: bogus' },
    });
  });

  it('drops malformed inbound messages silently', async () => {
    const { port } = setup();
    port.onMessage.fire('not a request');
    port.onMessage.fire({ method: 'ping' });
    await flush();
    expect(port.postMessage).not.toHaveBeenCalled();
  });

  it('kill-switch: detaches every attached debugger on disconnect', async () => {
    const { chrome, port, bridge } = setup();
    await bridge.attachTab(3);
    await bridge.attachTab(4);
    port.onDisconnect.fire();
    await flush();
    expect(chrome.debugger.detach).toHaveBeenCalledWith({ tabId: 3 });
    expect(chrome.debugger.detach).toHaveBeenCalledWith({ tabId: 4 });
    expect(bridge.attachedTabs.size).toBe(0);
  });

  it('schedules reconnect alarms and records the disconnect error', async () => {
    const { chrome, port } = setup();
    chrome.runtime.lastError = { message: 'Specified native messaging host not found.' };
    port.onDisconnect.fire();
    await flush();
    expect(chrome.alarms.create).toHaveBeenCalledWith(RECONNECT_ALARM, {
      periodInMinutes: RECONNECT_PERIOD_MINUTES,
    });
    expect(chrome.alarms.create).toHaveBeenCalledWith(RECONNECT_FAST_ALARM, {
      delayInMinutes: FAST_RETRY_DELAY_MINUTES,
    });
    expect(chrome.storage.local.set).toHaveBeenCalledWith({
      [STATUS_STORAGE_KEY]: expect.objectContaining({
        connected: false,
        lastError: 'Specified native messaging host not found.',
      }),
    });
  });

  it('reconnects when either alarm fires and clears stale attach state', async () => {
    const { chrome, port, bridge } = setup();
    await bridge.attachTab(3);
    port.onDisconnect.fire();
    await flush();
    chrome.debugger.detach.mockClear();

    chrome.alarms.onAlarm.fire({ name: RECONNECT_FAST_ALARM });
    expect(chrome.runtime.connectNative).toHaveBeenCalledTimes(2);
    expect(bridge.attachedTabs.size).toBe(0); // sidecar re-issues attach

    chrome.alarms.onAlarm.fire({ name: RECONNECT_ALARM });
    expect(chrome.runtime.connectNative).toHaveBeenCalledTimes(2); // already connected
  });

  it('ignores unrelated alarms', () => {
    const { chrome } = setup();
    chrome.alarms.onAlarm.fire({ name: 'something-else' });
    expect(chrome.runtime.connectNative).toHaveBeenCalledTimes(1);
  });
});

describe('event relay', () => {
  it('forwards debugger events as onCDPEvent notifications', () => {
    const { chrome, port } = setup();
    const params = { requestId: 'r1' };
    chrome.debugger.onEvent.fire({ tabId: 3 }, 'Network.requestWillBeSent', params);
    expect(port.postMessage).toHaveBeenCalledWith({
      jsonrpc: '2.0',
      method: 'onCDPEvent',
      params: { tabId: 3, method: 'Network.requestWillBeSent', params },
    });
  });

  it('forwards detach as onCDPDetach and drops the tab from the set', async () => {
    const { chrome, port, bridge } = setup();
    await bridge.attachTab(3);
    chrome.debugger.onDetach.fire({ tabId: 3 }, 'target_closed');
    expect(bridge.attachedTabs.has(3)).toBe(false);
    expect(port.postMessage).toHaveBeenCalledWith({
      jsonrpc: '2.0',
      method: 'onCDPDetach',
      params: { tabId: 3, reason: 'target_closed' },
    });
  });

  it('ignores debugger events without a tab id', () => {
    const { chrome, port } = setup();
    chrome.debugger.onEvent.fire({}, 'Network.requestWillBeSent', {});
    expect(port.postMessage).not.toHaveBeenCalled();
  });

  it('stops relaying once the port is gone', async () => {
    const { chrome, port } = setup();
    port.onDisconnect.fire();
    await flush();
    port.postMessage.mockClear();
    chrome.debugger.onEvent.fire({ tabId: 3 }, 'Network.requestWillBeSent', {});
    expect(port.postMessage).not.toHaveBeenCalled();
  });
});
