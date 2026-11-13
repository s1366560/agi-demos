import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppBridge } from '@mcp-ui/client';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import type { JSONRPCMessage } from '@modelcontextprotocol/sdk/types.js';
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import { WebOperationAdmissionV2 } from '../../plugins/webOperationAdmissionV2';
import { BrowserWebSocketTransport } from '../../services/mcp/BrowserWebSocketTransport';

class Socket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static current: Socket;
  readyState = Socket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  sent: Array<{ method?: string; id?: number }> = [];
  constructor() {
    Socket.current = this;
  }
  open() {
    this.readyState = Socket.OPEN;
    this.onopen?.();
  }
  send(data: string) {
    const message = JSON.parse(data);
    this.sent.push(message);
    if (message.method === 'initialize')
      queueMicrotask(() =>
        this.onmessage?.({
          data: JSON.stringify({
            jsonrpc: '2.0',
            id: message.id,
            result: {
              protocolVersion: '2025-03-26',
              capabilities: { tools: {} },
              serverInfo: { name: 'fixture', version: '1' },
            },
          }),
        })
      );
  }
  close() {
    this.readyState = Socket.CLOSING;
  }
  finish() {
    this.readyState = Socket.CLOSED;
    this.onclose?.();
  }
}
class FrameTransport implements Transport {
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage) => void;
  sent: JSONRPCMessage[] = [];
  async start() {}
  async send(message: JSONRPCMessage) {
    this.sent.push(message);
  }
  async close() {
    this.onclose?.();
  }
  call(id: number) {
    this.onmessage?.({
      jsonrpc: '2.0',
      id,
      method: 'tools/call',
      params: { name: 'mutate', arguments: {} },
    });
  }
}
afterEach(() => vi.unstubAllGlobals());
describe('actual MCP SDK and official AppBridge retirement', () => {
  it('rejects pending iframe RPC and stale Client calls without replay while real lease waits for close', async () => {
    vi.stubGlobal('WebSocket', Socket);
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(profile);
    const admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    const client = new Client({ name: 'host', version: '1' });
    const frame = new FrameTransport();
    const bridge = new AppBridge(client, { name: 'host', version: '1' }, { serverTools: {} });
    let started!: () => void;
    const ready = new Promise<void>((resolve) => {
      started = resolve;
    });
    const operation = admission.run(async (context) => {
      const transport = new BrowserWebSocketTransport({
        url: 'ws://fixture.invalid/mcp',
        operation: context,
      });
      const connected = client.connect(transport);
      Socket.current.open();
      await connected;
      await bridge.connect(frame);
      started();
      await new Promise<void>((resolve) =>
        context.signal.addEventListener('abort', () => resolve(), { once: true })
      );
      // SDK logical onclose clears its transport; physical drain needs the retained reference.
      await Promise.all([client.close(), transport.close()]);
      context.check();
    });
    const retired = expect(operation).rejects.toMatchObject({ name: 'AbortError' });
    try {
      await ready;
      frame.call(1);
      await vi.waitFor(() =>
        expect(Socket.current.sent.filter((m) => m.method === 'tools/call')).toHaveLength(1)
      );
      admission.invalidate();
      await vi.waitFor(() =>
        expect(frame.sent).toContainEqual(
          expect.objectContaining({ id: 1, error: expect.any(Object) })
        )
      );
      expect(runtime.getSnapshot()!.leaseCount).toBe(1);
      frame.call(2);
      await vi.waitFor(() =>
        expect(frame.sent).toContainEqual(
          expect.objectContaining({ id: 2, error: expect.any(Object) })
        )
      );
      await expect(client.callTool({ name: 'mutate', arguments: {} })).rejects.toThrow();
      expect(Socket.current.sent.filter((m) => m.method === 'tools/call')).toHaveLength(1);
      Socket.current.finish();
      await retired;
      expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    } finally {
      admission.invalidate();
      Socket.current?.finish();
      await Promise.allSettled([operation]);
      await bridge.close();
      await admission.close();
      await runtime.close();
    }
  });
});
