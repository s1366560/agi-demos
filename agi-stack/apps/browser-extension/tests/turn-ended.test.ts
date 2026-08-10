import { describe, expect, it } from 'vitest';
import { createBridge } from '../src/handlers';
import { createChromeMock } from './chrome-mock';

function setup() {
  const { chrome } = createChromeMock();
  const bridge = createBridge(chrome);
  return { chrome, bridge };
}

function dispatchTurnEnded(bridge: ReturnType<typeof createBridge>, leases: unknown, id = 1) {
  return bridge.dispatch({ jsonrpc: '2.0', id, method: 'turnEnded', params: { leases } });
}

describe('turnEnded cleanup matrix', () => {
  it('closes unmarked agent tabs (detaching debuggers best-effort)', async () => {
    const { chrome, bridge } = setup();
    await bridge.attachTab(11);
    const response = await dispatchTurnEnded(bridge, [{ tabId: 11, origin: 'agent' }]);
    expect(response).toMatchObject({ result: { closed: 1, ungrouped: 0 } });
    expect(chrome.debugger.detach).toHaveBeenCalledWith({ tabId: 11 });
    expect(chrome.tabs.remove).toHaveBeenCalledWith(11);
    expect(chrome.tabs.ungroup).not.toHaveBeenCalled();
  });

  it('ungroups deliverable tabs but keeps them open', async () => {
    const { chrome, bridge } = setup();
    const response = await dispatchTurnEnded(bridge, [
      { tabId: 12, origin: 'agent', mark: 'deliverable' },
    ]);
    expect(response).toMatchObject({ result: { closed: 0, ungrouped: 1 } });
    expect(chrome.tabs.ungroup).toHaveBeenCalledWith(12);
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
  });

  it('keeps handoff tabs in their group', async () => {
    const { chrome, bridge } = setup();
    const response = await dispatchTurnEnded(bridge, [
      { tabId: 13, origin: 'agent', mark: 'handoff' },
    ]);
    expect(response).toMatchObject({ result: { closed: 0, ungrouped: 0 } });
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
    expect(chrome.tabs.ungroup).not.toHaveBeenCalled();
  });

  it('leaves user tabs untouched', async () => {
    const { chrome, bridge } = setup();
    const response = await dispatchTurnEnded(bridge, [
      { tabId: 14, origin: 'user' },
      { tabId: 15, origin: 'user', mark: 'deliverable' },
    ]);
    expect(response).toMatchObject({ result: { closed: 0, ungrouped: 0 } });
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
    expect(chrome.tabs.ungroup).not.toHaveBeenCalled();
  });

  it('applies the matrix per lease and counts successes', async () => {
    const { chrome, bridge } = setup();
    const response = await dispatchTurnEnded(bridge, [
      { tabId: 21, origin: 'agent' },
      { tabId: 22, origin: 'agent' },
      { tabId: 23, origin: 'agent', mark: 'deliverable' },
      { tabId: 24, origin: 'agent', mark: 'handoff' },
      { tabId: 25, origin: 'user' },
    ]);
    expect(response).toMatchObject({ result: { closed: 2, ungrouped: 1 } });
    expect(chrome.tabs.remove).toHaveBeenCalledTimes(2);
    expect(chrome.tabs.ungroup).toHaveBeenCalledTimes(1);
  });

  it('tolerates per-tab failures and counts only successes', async () => {
    const { chrome, bridge } = setup();
    chrome.tabs.remove.mockImplementation(async (tabId: number) => {
      if (tabId === 31) throw new Error('No tab with id: 31');
    });
    chrome.tabs.ungroup.mockImplementation(async (tabIds: number | number[]) => {
      if (tabIds === 33) throw new Error('No tab with id: 33');
    });
    const response = await dispatchTurnEnded(bridge, [
      { tabId: 31, origin: 'agent' }, // close fails
      { tabId: 32, origin: 'agent' }, // close succeeds
      { tabId: 33, origin: 'agent', mark: 'deliverable' }, // ungroup fails
      { tabId: 34, origin: 'agent', mark: 'deliverable' }, // ungroup succeeds
    ]);
    expect(response).toMatchObject({ result: { closed: 1, ungrouped: 1 } });
  });

  it('hides the cursor on every affected tab', async () => {
    const { chrome, bridge } = setup();
    // Establish a visible cursor state on tab 41 via a teleport moveMouse.
    chrome.tabs.get.mockResolvedValue({ id: 41, windowId: 1, active: false });
    await bridge.dispatch({
      jsonrpc: '2.0',
      id: 1,
      method: 'moveMouse',
      params: { tabId: 41, x: 10, y: 10, waitForArrival: false },
    });
    await dispatchTurnEnded(bridge, [{ tabId: 41, origin: 'agent', mark: 'handoff' }], 2);
    const states = chrome.tabs.sendMessage.mock.calls
      .map(([, message]) => message as { type: string; state?: { visible: boolean } })
      .filter((m) => m.type === 'AGENT_CURSOR_STATE');
    expect(states[0]?.state).toMatchObject({ visible: true });
    expect(states[states.length - 1]?.state).toMatchObject({ visible: false });
  });

  it('validates the leases shape', async () => {
    const { bridge } = setup();
    for (const params of [
      {},
      { leases: 'nope' },
      { leases: [{ tabId: -1, origin: 'agent' }] },
      { leases: [{ tabId: 1, origin: 'robot' }] },
      { leases: [{ tabId: 1, origin: 'agent', mark: 'keep' }] },
    ]) {
      const response = await bridge.dispatch({
        jsonrpc: '2.0',
        id: 9,
        method: 'turnEnded',
        params,
      });
      expect(response).toMatchObject({ error: { code: -32602 } });
    }
  });
});
