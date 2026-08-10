import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CURSOR_CONTENT_SCRIPT_FILE } from '../src/cursor/cursor-manager';
import { createBridge } from '../src/handlers';
import { createChromeMock, flush } from './chrome-mock';

function setup() {
  const { chrome } = createChromeMock();
  const bridge = createBridge(chrome);
  return { chrome, bridge };
}

function moveMouse(
  bridge: ReturnType<typeof createBridge>,
  params: Record<string, unknown>,
  id = 1,
) {
  return bridge.dispatch({ jsonrpc: '2.0', id, method: 'moveMouse', params });
}

describe('moveMouse validation', () => {
  it('rejects bad tabId / coordinates with -32602', async () => {
    const { bridge } = setup();
    for (const params of [
      { tabId: -1, x: 1, y: 1 },
      { tabId: 1, x: Number.NaN, y: 1 },
      { tabId: 1, x: 1, y: Number.POSITIVE_INFINITY },
      { tabId: 1, x: '1', y: 1 },
      { tabId: 1, y: 1 },
      { tabId: 1, x: 1, y: 1, waitForArrival: 'yes' },
    ]) {
      expect(await moveMouse(bridge, params)).toMatchObject({ error: { code: -32602 } });
    }
  });
});

describe('moveMouse observed vs teleport', () => {
  it('animates and waits for arrival when the tab is observed', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: true });
    chrome.windows.get.mockResolvedValue({ id: 1, type: 'normal', state: 'normal' });

    let settled = false;
    const pending = moveMouse(bridge, { tabId: 5, x: 100, y: 80 }).then((r) => {
      settled = true;
      return r;
    });
    await flush();

    expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(5, {
      type: 'AGENT_CURSOR_STATE',
      state: { visible: true, x: 100, y: 80, animateMovement: true, moveSequence: 1 },
    });
    expect(settled).toBe(false); // gated on visual arrival

    // Content script reports arrival → the handler resolves.
    chrome.runtime.onMessage.fire(
      { type: 'AGENT_CURSOR_ARRIVED', moveSequence: 1 },
      { tab: { id: 5 } },
      () => undefined,
    );
    await expect(pending).resolves.toMatchObject({ result: {} });
  });

  it('teleports and returns immediately when the tab is not active', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: false });
    const response = await moveMouse(bridge, { tabId: 5, x: 10, y: 20 });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(5, {
      type: 'AGENT_CURSOR_STATE',
      state: { visible: true, x: 10, y: 20, animateMovement: false, moveSequence: 1 },
    });
  });

  it('teleports when the window is minimized', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: true });
    chrome.windows.get.mockResolvedValue({ id: 1, type: 'normal', state: 'minimized' });
    const response = await moveMouse(bridge, { tabId: 5, x: 1, y: 2 });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(5, {
      type: 'AGENT_CURSOR_STATE',
      state: expect.objectContaining({ animateMovement: false }),
    });
  });

  it('teleports when the window is a popup', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: true });
    chrome.windows.get.mockResolvedValue({ id: 1, type: 'popup', state: 'normal' });
    const response = await moveMouse(bridge, { tabId: 5, x: 1, y: 2 });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(5, {
      type: 'AGENT_CURSOR_STATE',
      state: expect.objectContaining({ animateMovement: false }),
    });
  });

  it('waitForArrival:false skips the observability check and never waits', async () => {
    const { chrome, bridge } = setup();
    const response = await moveMouse(bridge, { tabId: 5, x: 3, y: 4, waitForArrival: false });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.tabs.get).not.toHaveBeenCalled();
    expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(5, {
      type: 'AGENT_CURSOR_STATE',
      state: { visible: true, x: 3, y: 4, animateMovement: false, moveSequence: 1 },
    });
  });
});

describe('moveMouse circuit breakers', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('resolves on the 1500ms arrival timeout instead of hanging', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: true });
    const pending = moveMouse(bridge, { tabId: 5, x: 1, y: 1 });
    await vi.advanceTimersByTimeAsync(0); // let the publish land
    const assertion = expect(pending).resolves.toMatchObject({ result: {} });
    await vi.advanceTimersByTimeAsync(1500);
    await assertion;
  });

  it('resolves immediately when the publish fails', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: true });
    chrome.tabs.sendMessage.mockRejectedValue(new Error('Receiving end does not exist'));
    const response = await moveMouse(bridge, { tabId: 5, x: 1, y: 1 });
    expect(response).toMatchObject({ result: {} });
  });

  it('resolves when the publish times out (1000ms breaker)', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: true });
    // Ping succeeds instantly; the state publish hangs forever.
    chrome.tabs.sendMessage.mockImplementation(async (_tabId: number, message: unknown) => {
      if ((message as { type?: string }).type === 'AGENT_CURSOR_PING') return undefined;
      return new Promise(() => undefined);
    });
    const pending = moveMouse(bridge, { tabId: 5, x: 1, y: 1 });
    const assertion = expect(pending).resolves.toMatchObject({ result: {} });
    await vi.advanceTimersByTimeAsync(1000);
    await assertion;
  });
});

describe('moveMouse content-script injection', () => {
  it('injects the cursor script only when the ping fails', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: false });
    chrome.tabs.sendMessage
      .mockRejectedValueOnce(new Error('no receiver')) // ping fails
      .mockResolvedValue(undefined); // state publish succeeds
    const response = await moveMouse(bridge, { tabId: 5, x: 1, y: 1, waitForArrival: false });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.scripting.executeScript).toHaveBeenCalledWith({
      target: { tabId: 5 },
      files: [CURSOR_CONTENT_SCRIPT_FILE],
    });
    expect(chrome.tabs.sendMessage).toHaveBeenCalledTimes(2);
  });

  it('does not inject when the ping succeeds', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: false });
    await moveMouse(bridge, { tabId: 5, x: 1, y: 1, waitForArrival: false });
    expect(chrome.scripting.executeScript).not.toHaveBeenCalled();
  });
});

describe('cursor state pull', () => {
  it('answers GET_AGENT_CURSOR_STATE with the last state for the tab', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.get.mockResolvedValue({ id: 5, windowId: 1, active: false });
    await moveMouse(bridge, { tabId: 5, x: 42, y: 24, waitForArrival: false });
    const sendResponse = vi.fn();
    chrome.runtime.onMessage.fire(
      { type: 'GET_AGENT_CURSOR_STATE' },
      { tab: { id: 5 } },
      sendResponse,
    );
    expect(sendResponse).toHaveBeenCalledWith({
      visible: true,
      x: 42,
      y: 24,
      animateMovement: false,
      moveSequence: 1,
    });
  });

  it('answers with a hidden default for unknown tabs', async () => {
    const { chrome } = setup();
    const sendResponse = vi.fn();
    chrome.runtime.onMessage.fire(
      { type: 'GET_AGENT_CURSOR_STATE' },
      { tab: { id: 123 } },
      sendResponse,
    );
    expect(sendResponse).toHaveBeenCalledWith(expect.objectContaining({ visible: false }));
  });
});
