import { describe, expect, it } from 'vitest';
import { createBridge } from '../src/handlers';
import { startNativeTransport } from '../src/transport';
import { createChromeMock, flush } from './chrome-mock';

function setup() {
  const { chrome, port } = createChromeMock();
  const bridge = createBridge(chrome);
  const transport = startNativeTransport(chrome, bridge);
  return { chrome, port, bridge, transport };
}

describe('SW → native sendRequest', () => {
  it('posts a JSON-RPC request with a generated id and resolves with the result', async () => {
    const { port, transport } = setup();
    const promise = transport.sendRequest('getSidePanelSession', {});
    expect(port.postMessage).toHaveBeenCalledWith({
      jsonrpc: '2.0',
      id: 'sw-1',
      method: 'getSidePanelSession',
      params: {},
    });
    port.onMessage.fire({
      jsonrpc: '2.0',
      id: 'sw-1',
      result: { apiBaseUrl: 'http://127.0.0.1:8088' },
    });
    await expect(promise).resolves.toEqual({ apiBaseUrl: 'http://127.0.0.1:8088' });
  });

  it('rejects with the broker error code and message', async () => {
    const { port, transport } = setup();
    const promise = transport.sendRequest('getSidePanelSession', {});
    port.onMessage.fire({
      jsonrpc: '2.0',
      id: 'sw-1',
      error: { code: -32602, message: 'side panel session unavailable' },
    });
    await expect(promise).rejects.toMatchObject({
      code: -32602,
      message: 'side panel session unavailable',
    });
  });

  it('correlates concurrent requests by id, resolving out of order', async () => {
    const { port, transport } = setup();
    const first = transport.sendRequest('one');
    const second = transport.sendRequest('two');
    port.onMessage.fire({ jsonrpc: '2.0', id: 'sw-2', result: 'second-result' });
    await expect(second).resolves.toBe('second-result');
    expect(port.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'sw-1', method: 'one' }),
    );
    port.onMessage.fire({ jsonrpc: '2.0', id: 'sw-1', result: 'first-result' });
    await expect(first).resolves.toBe('first-result');
  });

  it('swallows broker responses with unknown ids instead of dispatching them', async () => {
    const { port } = setup();
    port.onMessage.fire({ jsonrpc: '2.0', id: 'sw-99', result: {} });
    await flush();
    expect(port.postMessage).not.toHaveBeenCalled();
  });

  it('still dispatches broker-initiated requests (id + method, no result/error)', async () => {
    const { port } = setup();
    port.onMessage.fire({ jsonrpc: '2.0', id: 7, method: 'ping' });
    await flush();
    expect(port.postMessage).toHaveBeenCalledWith({ jsonrpc: '2.0', id: 7, result: {} });
  });

  it('rejects every pending request when the port disconnects', async () => {
    const { port, transport } = setup();
    const first = transport.sendRequest('one');
    const second = transport.sendRequest('two');
    const firstAssertion = expect(first).rejects.toThrow('native port disconnected');
    const secondAssertion = expect(second).rejects.toThrow('native port disconnected');
    port.onDisconnect.fire();
    await firstAssertion;
    await secondAssertion;
  });

  it('rejects immediately when the native port is not connected', async () => {
    const { port, transport } = setup();
    port.onDisconnect.fire();
    await flush();
    await expect(transport.sendRequest('getSidePanelSession', {})).rejects.toThrow(
      'native port not connected',
    );
  });

  it('rejects a fresh request when postMessage throws mid-send', async () => {
    const { port, transport } = setup();
    port.postMessage.mockImplementation(() => {
      throw new Error('port gone');
    });
    await expect(transport.sendRequest('one')).rejects.toThrow('native port went away mid-send');
    // The failed request must not linger in the pending map: a late response is ignored.
    port.onMessage.fire({ jsonrpc: '2.0', id: 'sw-1', result: {} });
    await flush();
  });
});
