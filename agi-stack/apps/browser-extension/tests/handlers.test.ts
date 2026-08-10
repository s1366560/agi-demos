import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createBridge } from '../src/handlers';
import { createChromeMock } from './chrome-mock';

function setup() {
  const { chrome } = createChromeMock();
  const bridge = createBridge(chrome);
  return { chrome, bridge };
}

describe('dispatcher', () => {
  it('answers hello with the pinned extension id and capabilities', async () => {
    const { bridge } = setup();
    const response = await bridge.dispatch({ jsonrpc: '2.0', id: 1, method: 'hello', params: {} });
    expect(response).toEqual({
      jsonrpc: '2.0',
      id: 1,
      result: {
        protocolVersion: 1,
        extensionId: 'enbljdpbhdllbbkcjhccmbgpkfmcdkkl',
        capabilities: ['cdp', 'tabs', 'events'],
      },
    });
  });

  it('answers ping with an empty result', async () => {
    const { bridge } = setup();
    const response = await bridge.dispatch({ jsonrpc: '2.0', id: 2, method: 'ping' });
    expect(response).toEqual({ jsonrpc: '2.0', id: 2, result: {} });
  });

  it('returns -32601 for unknown methods', async () => {
    const { bridge } = setup();
    const response = await bridge.dispatch({ jsonrpc: '2.0', id: 3, method: 'nope' });
    expect(response).toMatchObject({ id: 3, error: { code: -32601 } });
  });

  it('ignores malformed inbound messages', async () => {
    const { bridge } = setup();
    expect(await bridge.dispatch('garbage')).toBeNull();
    expect(await bridge.dispatch(null)).toBeNull();
    expect(await bridge.dispatch({ jsonrpc: '2.0', method: 'ping' })).toBeNull();
    expect(await bridge.dispatch({ jsonrpc: '2.0', id: 1, method: 42 })).toBeNull();
  });
});

describe('param validation (-32602)', () => {
  it('rejects non-positive or non-integer tabIds', async () => {
    const { bridge } = setup();
    for (const tabId of [-1, 0, 1.5, '3', undefined]) {
      const response = await bridge.dispatch({
        jsonrpc: '2.0',
        id: 10,
        method: 'attach',
        params: { tabId },
      });
      expect(response).toMatchObject({ error: { code: -32602 } });
    }
  });

  it('rejects missing params objects', async () => {
    const { bridge } = setup();
    const response = await bridge.dispatch({ jsonrpc: '2.0', id: 11, method: 'attach' });
    expect(response).toMatchObject({ error: { code: -32602 } });
  });

  it('rejects malformed CDP method names', async () => {
    const { bridge } = setup();
    for (const method of ['foo', 'runtime.evaluate', 'Runtime', 'Runtime.', 42]) {
      const response = await bridge.dispatch({
        jsonrpc: '2.0',
        id: 12,
        method: 'executeCdp',
        params: { tabId: 1, method },
      });
      expect(response).toMatchObject({ error: { code: -32602 } });
    }
  });

  it('rejects non-object executeCdp params.params', async () => {
    const { bridge } = setup();
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 13,
      method: 'executeCdp',
      params: { tabId: 1, method: 'Runtime.evaluate', params: 'nope' },
    });
    expect(response).toMatchObject({ error: { code: -32602 } });
  });
});

describe('attach/detach', () => {
  it('attach is idempotent', async () => {
    const { chrome, bridge } = setup();
    await bridge.dispatch({ jsonrpc: '2.0', id: 1, method: 'attach', params: { tabId: 7 } });
    const second = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 2,
      method: 'attach',
      params: { tabId: 7 },
    });
    expect(second).toMatchObject({ result: {} });
    expect(chrome.debugger.attach).toHaveBeenCalledTimes(1);
    expect(chrome.debugger.attach).toHaveBeenCalledWith({ tabId: 7 }, '1.3');
    expect(bridge.attachedTabs.has(7)).toBe(true);
  });

  it('detach removes the tab and is a no-op when not attached', async () => {
    const { chrome, bridge } = setup();
    await bridge.dispatch({ jsonrpc: '2.0', id: 1, method: 'attach', params: { tabId: 7 } });
    await bridge.dispatch({ jsonrpc: '2.0', id: 2, method: 'detach', params: { tabId: 7 } });
    expect(chrome.debugger.detach).toHaveBeenCalledWith({ tabId: 7 });
    expect(bridge.attachedTabs.has(7)).toBe(false);

    const again = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 3,
      method: 'detach',
      params: { tabId: 7 },
    });
    expect(again).toMatchObject({ result: {} });
    expect(chrome.debugger.detach).toHaveBeenCalledTimes(1);
  });
});

describe('executeCdp', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('implicitly attaches to an unattached tab and wraps the result', async () => {
    const { chrome, bridge } = setup();
    chrome.debugger.sendCommand.mockResolvedValue({ value: 42 });
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 5,
      method: 'executeCdp',
      params: { tabId: 3, method: 'Runtime.evaluate', params: { expression: '1+1' } },
    });
    expect(response).toEqual({ jsonrpc: '2.0', id: 5, result: { result: { value: 42 } } });
    expect(chrome.debugger.attach).toHaveBeenCalledWith({ tabId: 3 }, '1.3');
    expect(chrome.debugger.sendCommand).toHaveBeenCalledWith({ tabId: 3 }, 'Runtime.evaluate', {
      expression: '1+1',
    });
    expect(bridge.attachedTabs.has(3)).toBe(true);
  });

  it('times out after 10s, auto-detaches, and returns code 1', async () => {
    const { chrome, bridge } = setup();
    chrome.debugger.sendCommand.mockReturnValue(new Promise(() => undefined));
    const pending = bridge.dispatch({
      jsonrpc: '2.0',
      id: 6,
      method: 'executeCdp',
      params: { tabId: 5, method: 'Page.captureScreenshot' },
    });
    const assertion = expect(pending).resolves.toMatchObject({
      id: 6,
      error: { code: 1, message: expect.stringContaining('cdp command timeout') },
    });
    await vi.advanceTimersByTimeAsync(10_000);
    await assertion;
    expect(chrome.debugger.detach).toHaveBeenCalledWith({ tabId: 5 });
    expect(bridge.attachedTabs.has(5)).toBe(false);
  });

  it('does not time out when the command resolves in time', async () => {
    const { chrome, bridge } = setup();
    chrome.debugger.sendCommand.mockResolvedValue({});
    const pending = bridge.dispatch({
      jsonrpc: '2.0',
      id: 7,
      method: 'executeCdp',
      params: { tabId: 5, method: 'Runtime.evaluate' },
    });
    await vi.advanceTimersByTimeAsync(9_999);
    await expect(pending).resolves.toMatchObject({ result: { result: {} } });
    expect(chrome.debugger.detach).not.toHaveBeenCalled();
    expect(bridge.attachedTabs.has(5)).toBe(true);
  });
});

describe('tabs', () => {
  it('getTabs filters internal schemes and maps fields', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.query.mockResolvedValue([
      { id: 1, windowId: 10, title: 'Docs', url: 'https://example.com/docs', active: true },
      { id: 2, windowId: 10, title: 'Settings', url: 'chrome://settings', active: false },
      { id: 3, windowId: 10, title: 'Ext', url: 'chrome-extension://abc/popup.html', active: false },
      { id: 4, windowId: 10, title: 'Edge', url: 'edge://flags', active: false },
      { id: 5, windowId: 10, title: '', url: 'about:blank', active: false },
      { id: 6, windowId: 11, title: 'Plain', url: '', active: false },
      { windowId: 11, title: 'No id', url: 'https://x.test' },
    ]);
    const response = await bridge.dispatch({ jsonrpc: '2.0', id: 20, method: 'getTabs' });
    expect(response).toEqual({
      jsonrpc: '2.0',
      id: 20,
      result: {
        tabs: [
          { tabId: 1, windowId: 10, title: 'Docs', url: 'https://example.com/docs', active: true },
          { tabId: 6, windowId: 11, title: 'Plain', url: '', active: false },
        ],
      },
    });
  });

  it('createTab defaults to a background about:blank tab', async () => {
    const { chrome, bridge } = setup();
    const response = await bridge.dispatch({ jsonrpc: '2.0', id: 21, method: 'createTab' });
    expect(chrome.tabs.create).toHaveBeenCalledWith({ url: 'about:blank', active: false });
    expect(response).toEqual({ jsonrpc: '2.0', id: 21, result: { tabId: 99 } });
  });

  it('createTab honours an explicit url and validates its type', async () => {
    const { chrome, bridge } = setup();
    await bridge.dispatch({
      jsonrpc: '2.0',
      id: 22,
      method: 'createTab',
      params: { url: 'https://example.com' },
    });
    expect(chrome.tabs.create).toHaveBeenCalledWith({
      url: 'https://example.com',
      active: false,
    });
    const bad = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 23,
      method: 'createTab',
      params: { url: 42 },
    });
    expect(bad).toMatchObject({ error: { code: -32602 } });
  });
});
