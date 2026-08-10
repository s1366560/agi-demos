import { describe, expect, it } from 'vitest';
import { createBridge } from '../src/handlers';
import { MONITOR_CONTENT_SCRIPT_FILE } from '../src/monitor';
import { createChromeMock, flush } from './chrome-mock';

function setup() {
  const { chrome } = createChromeMock();
  const bridge = createBridge(chrome);
  return { chrome, bridge };
}

describe('ensureTabGroup', () => {
  it('creates a fresh group for an unknown key and persists the mapping', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.group.mockResolvedValue(555);
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 1,
      method: 'ensureTabGroup',
      params: { key: 'run-1', title: 'Agent run 1' },
    });
    expect(response).toEqual({ jsonrpc: '2.0', id: 1, result: { groupId: 555 } });
    // chrome.tabs.group needs an anchor tab: a background placeholder is created.
    expect(chrome.tabs.create).toHaveBeenCalledWith({ url: 'about:blank', active: false });
    expect(chrome.tabs.group).toHaveBeenCalledWith({ tabIds: 99 });
    expect(chrome.tabGroups.update).toHaveBeenCalledWith(555, {
      title: 'Agent run 1',
      color: 'blue',
    });
    expect(chrome.storage.local.set).toHaveBeenCalledWith({ 'memstackTabGroup:run-1': 555 });
  });

  it('honours an explicit color', async () => {
    const { chrome, bridge } = setup();
    await bridge.dispatch({
      jsonrpc: '2.0',
      id: 2,
      method: 'ensureTabGroup',
      params: { key: 'run-2', title: 'Run', color: 'red' },
    });
    expect(chrome.tabGroups.update).toHaveBeenCalledWith(555, { title: 'Run', color: 'red' });
  });

  it('is idempotent per key: a live stored group is reused', async () => {
    const { chrome, bridge } = setup();
    chrome.storage.local.get.mockResolvedValue({ 'memstackTabGroup:run-1': 432 });
    chrome.tabGroups.get.mockResolvedValue({ id: 432 });
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 3,
      method: 'ensureTabGroup',
      params: { key: 'run-1', title: 'Run' },
    });
    expect(response).toEqual({ jsonrpc: '2.0', id: 3, result: { groupId: 432 } });
    expect(chrome.tabGroups.get).toHaveBeenCalledWith(432);
    expect(chrome.tabs.create).not.toHaveBeenCalled();
    expect(chrome.tabs.group).not.toHaveBeenCalled();
  });

  it('recreates the group when the stored id is stale and re-persists it', async () => {
    const { chrome, bridge } = setup();
    chrome.storage.local.get.mockResolvedValue({ 'memstackTabGroup:run-1': 432 });
    chrome.tabGroups.get.mockRejectedValue(new Error('No group with id: 432'));
    chrome.tabs.group.mockResolvedValue(777);
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 4,
      method: 'ensureTabGroup',
      params: { key: 'run-1', title: 'Run' },
    });
    expect(response).toEqual({ jsonrpc: '2.0', id: 4, result: { groupId: 777 } });
    expect(chrome.tabs.create).toHaveBeenCalledTimes(1);
    expect(chrome.storage.local.set).toHaveBeenCalledWith({ 'memstackTabGroup:run-1': 777 });
  });

  it('rejects invalid params with -32602', async () => {
    const { bridge } = setup();
    for (const params of [
      {},
      { key: 'k' },
      { title: 't' },
      { key: '', title: 't' },
      { key: 'k', title: 't', color: 7 },
    ]) {
      const response = await bridge.dispatch({
        jsonrpc: '2.0',
        id: 5,
        method: 'ensureTabGroup',
        params,
      });
      expect(response).toMatchObject({ error: { code: -32602 } });
    }
  });
});

describe('assignTab', () => {
  it('groups the tab and injects the foreign-frame monitor', async () => {
    const { chrome, bridge } = setup();
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 1,
      method: 'assignTab',
      params: { tabId: 7, groupId: 555 },
    });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.tabs.group).toHaveBeenCalledWith({ tabIds: 7, groupId: 555 });
    await flush();
    expect(chrome.scripting.executeScript).toHaveBeenCalledWith({
      target: { tabId: 7, allFrames: true },
      files: [MONITOR_CONTENT_SCRIPT_FILE],
    });
  });

  it('maps a missing/invalid group to -32602', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.group.mockRejectedValue(new Error('No group with id: 999'));
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 2,
      method: 'assignTab',
      params: { tabId: 7, groupId: 999 },
    });
    expect(response).toMatchObject({ error: { code: -32602 } });
  });

  it('validates params', async () => {
    const { bridge } = setup();
    for (const params of [{ tabId: 7 }, { groupId: 1 }, { tabId: -1, groupId: 1 }]) {
      const response = await bridge.dispatch({
        jsonrpc: '2.0',
        id: 3,
        method: 'assignTab',
        params,
      });
      expect(response).toMatchObject({ error: { code: -32602 } });
    }
  });
});

describe('createTab', () => {
  it('injects the foreign-frame monitor into the claimed tab', async () => {
    const { chrome, bridge } = setup();
    await bridge.dispatch({ jsonrpc: '2.0', id: 1, method: 'createTab' });
    await flush();
    expect(chrome.scripting.executeScript).toHaveBeenCalledWith({
      target: { tabId: 99, allFrames: true },
      files: [MONITOR_CONTENT_SCRIPT_FILE],
    });
  });
});

describe('ungroupTab / closeTab / focusTab', () => {
  it('ungroupTab calls chrome.tabs.ungroup', async () => {
    const { chrome, bridge } = setup();
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 1,
      method: 'ungroupTab',
      params: { tabId: 7 },
    });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.tabs.ungroup).toHaveBeenCalledWith(7);
  });

  it('closeTab detaches the debugger first when attached', async () => {
    const { chrome, bridge } = setup();
    await bridge.attachTab(7);
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 2,
      method: 'closeTab',
      params: { tabId: 7 },
    });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.debugger.detach).toHaveBeenCalledWith({ tabId: 7 });
    expect(chrome.tabs.remove).toHaveBeenCalledWith(7);
    expect(bridge.attachedTabs.has(7)).toBe(false);
  });

  it('closeTab without an attached debugger skips the detach', async () => {
    const { chrome, bridge } = setup();
    await bridge.dispatch({ jsonrpc: '2.0', id: 3, method: 'closeTab', params: { tabId: 8 } });
    expect(chrome.debugger.detach).not.toHaveBeenCalled();
    expect(chrome.tabs.remove).toHaveBeenCalledWith(8);
  });

  it('closeTab still removes the tab when the detach fails', async () => {
    const { chrome, bridge } = setup();
    await bridge.attachTab(7);
    chrome.debugger.detach.mockRejectedValue(new Error('gone'));
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 4,
      method: 'closeTab',
      params: { tabId: 7 },
    });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.tabs.remove).toHaveBeenCalledWith(7);
  });

  it('focusTab activates the tab without focusing the window', async () => {
    const { chrome, bridge } = setup();
    const response = await bridge.dispatch({
      jsonrpc: '2.0',
      id: 5,
      method: 'focusTab',
      params: { tabId: 7 },
    });
    expect(response).toMatchObject({ result: {} });
    expect(chrome.tabs.update).toHaveBeenCalledWith(7, { active: true });
    expect(chrome.windows.get).not.toHaveBeenCalled();
  });
});
