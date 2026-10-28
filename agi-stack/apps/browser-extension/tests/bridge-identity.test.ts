import { describe, expect, it } from 'vitest';
import { createBridge, type Bridge } from '../src/handlers';
import { createChromeMock } from './chrome-mock';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

async function hello(bridge: Bridge, id = 1): Promise<Record<string, unknown>> {
  const response = await bridge.dispatch({ jsonrpc: '2.0', id, method: 'hello', params: {} });
  expect(response).toHaveProperty('result');
  return (response as { result: Record<string, unknown> }).result;
}

function profile() {
  const { chrome } = createChromeMock();
  const stored: Record<string, unknown> = {};
  chrome.storage.local.get.mockImplementation(async (key) => ({ [key]: stored[key] }));
  chrome.storage.local.set.mockImplementation(async (items) => { Object.assign(stored, items); });
  return { chrome, stored };
}

describe('browser identity handshake', () => {
  it('retains a profile identity while rotating the extension instance on worker restart', async () => {
    const { chrome } = profile();
    const firstWorker = createBridge(chrome);
    const first = await hello(firstWorker);
    const reconnect = await hello(firstWorker, 2);
    const secondWorker = await hello(createBridge(chrome));
    expect(first.profileId).toMatch(uuid);
    expect(first.extensionInstanceId).toMatch(uuid);
    expect(reconnect.profileId).toBe(first.profileId);
    expect(reconnect.extensionInstanceId).toBe(first.extensionInstanceId);
    expect(secondWorker.profileId).toBe(first.profileId);
    expect(secondWorker.extensionInstanceId).not.toBe(first.extensionInstanceId);
    expect(chrome.storage.local.set).toHaveBeenCalledTimes(1);
  });

  it('gives separate browser profiles independent identities even with matching tab ids', async () => {
    const first = profile(), second = profile(), edge = profile();
    for (const fixture of [first, second, edge]) {
      fixture.chrome.tabs.query.mockResolvedValue([{ id: 7, url: 'https://example.test/' }]);
    }
    const firstIdentity = await hello(createBridge(first.chrome));
    const secondIdentity = await hello(createBridge(second.chrome));
    const edgeIdentity = await hello(createBridge(edge.chrome, 'edge'));
    expect(new Set([firstIdentity.profileId, secondIdentity.profileId, edgeIdentity.profileId]).size).toBe(3);
    expect(edgeIdentity.backend).toBe('edge-extension');
  });

  it('does not publish an identity until persistence completes and shares concurrent initialization', async () => {
    const { chrome, stored } = profile();
    let release!: () => void, started!: () => void;
    const persisted = new Promise<void>((resolve) => { release = resolve; });
    const storing = new Promise<void>((resolve) => { started = resolve; });
    chrome.storage.local.set.mockImplementation(async (items) => {
      started();
      await persisted;
      Object.assign(stored, items);
    });
    const bridge = createBridge(chrome);
    let finished = false;
    const replies = Promise.all([hello(bridge), hello(bridge, 2)]).then((values) => {
      finished = true;
      return values;
    });
    await storing;
    expect(finished).toBe(false);
    expect(chrome.storage.local.get).toHaveBeenCalledTimes(1);
    expect(chrome.storage.local.set).toHaveBeenCalledTimes(1);
    release();
    const [first, second] = await replies;
    expect(first).toEqual(second);
  });

  it('rejects failed persistence without exposing an ephemeral profile and can retry safely', async () => {
    const { chrome } = profile();
    chrome.storage.local.set.mockRejectedValueOnce(new Error('profile storage unavailable'));
    const bridge = createBridge(chrome);
    const failed = await bridge.dispatch({ jsonrpc: '2.0', id: 1, method: 'hello', params: {} });
    expect(failed).toMatchObject({ error: { code: -32603, message: 'profile storage unavailable' } });
    expect(failed).not.toHaveProperty('result');
    const recovered = await hello(bridge, 2);
    expect(recovered.profileId).toMatch(uuid);
    expect(chrome.storage.local.set).toHaveBeenCalledTimes(2);
  });
});
