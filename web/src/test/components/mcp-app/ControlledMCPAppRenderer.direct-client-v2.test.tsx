import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { PostMessageTransport } from '@mcp-ui/client';
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js';
import type { JSONRPCMessage } from '@modelcontextprotocol/sdk/types.js';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';
import ControlledMCPAppRendererV2 from '@/components/mcp-app/ControlledMCPAppRendererV2';
class Upstream implements Transport {
  onmessage?: (message: JSONRPCMessage) => void;
  onclose?: () => void;
  onerror?: (error: Error) => void;
  readonly sent: JSONRPCMessage[] = [];
  async start() {}
  async close() {
    this.onclose?.();
  }
  async send(message: JSONRPCMessage) {
    this.sent.push(message);
    if ('method' in message && message.method === 'initialize' && 'id' in message)
      queueMicrotask(() =>
        this.onmessage?.({
          jsonrpc: '2.0',
          id: message.id,
          result: {
            protocolVersion: '2025-03-26',
            capabilities: { tools: {} },
            serverInfo: { name: 'upstream', version: '1' },
          },
        })
      );
  }
}
const sandbox = { url: new URL('https://mcp-frame.example/proxy') };
async function flush() {
  await act(async () => {
    for (let i = 0; i < 30; i++) await Promise.resolve();
  });
}
async function fixture() {
  const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  const admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  let operation!: WebOperationContextV2;
  let ready!: () => void;
  const admitted = new Promise<void>((resolve) => {
    ready = resolve;
  });
  const parent = admission.run(async (context) => {
    operation = context;
    ready();
    await new Promise<void>((resolve) =>
      context.signal.addEventListener('abort', () => resolve(), { once: true })
    );
    context.check();
  });
  void parent.catch(() => undefined);
  await admitted;
  const client = new Client({ name: 'parent-owned-client', version: '1' });
  const upstream = new Upstream();
  await client.connect(upstream);
  const ui = render(
    <ControlledMCPAppRendererV2
      operation={operation}
      client={client}
      toolName="tool"
      html="<p>frame</p>"
      sandbox={sandbox}
    />
  );
  await flush();
  const frame = ui.container.querySelector('iframe')!;
  const frameWindow = frame.contentWindow!;
  act(() =>
    window.dispatchEvent(
      new MessageEvent('message', {
        source: frameWindow,
        origin: sandbox.url.origin,
        data: { jsonrpc: '2.0', method: 'ui/notifications/sandbox-proxy-ready' },
      })
    )
  );
  await flush();
  function send(id: number) {
    window.dispatchEvent(
      new MessageEvent('message', {
        source: frameWindow,
        origin: sandbox.url.origin,
        data: {
          jsonrpc: '2.0',
          id,
          method: 'tools/call',
          params: { name: 'mutate', arguments: { value: id } },
        },
      })
    );
  }
  return {
    runtime,
    admission,
    operation,
    client,
    upstream,
    ui,
    frameWindow,
    send,
    async close() {
      ui.unmount();
      await client.close();
      admission.invalidate();
      await Promise.allSettled([parent]);
      await admission.close();
      await runtime.close();
    },
  };
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
describe('official AppBridge direct forwarding with frame-only retirement', () => {
  it('unmount cancels forwarded RPC immediately while the real parent/client remain usable', async () => {
    const bridgeClose = vi.spyOn(PostMessageTransport.prototype, 'close');
    const f = await fixture();
    vi.useFakeTimers();
    const post = vi.spyOn(f.frameWindow, 'postMessage');
    const clientClose = vi.spyOn(f.client, 'close');
    try {
      act(() => f.send(101));
      await flush();
      const request = f.upstream.sent.find(
        (message) => 'method' in message && message.method === 'tools/call'
      )!;
      expect(request).toBeDefined();
      expect(vi.getTimerCount()).toBe(1);
      expect(f.runtime.getSnapshot()!.leaseCount).toBe(2);
      f.ui.unmount();
      // Protocol.close synchronously removes the frame listener and aborts the request handler signal.
      expect(bridgeClose).toHaveBeenCalledOnce();
      expect(clientClose).not.toHaveBeenCalled();
      expect(
        f.upstream.sent.filter(
          (message) => 'method' in message && message.method === 'notifications/cancelled'
        )
      ).toHaveLength(1);
      expect(vi.getTimerCount()).toBe(0);
      const sentToFrame = post.mock.calls.length;
      act(() => {
        f.send(102);
        if ('id' in request)
          f.upstream.onmessage?.({
            jsonrpc: '2.0',
            id: request.id,
            result: { content: [{ type: 'text', text: 'late result' }] },
          });
      });
      await flush();
      expect(post).toHaveBeenCalledTimes(sentToFrame);
      expect(
        f.upstream.sent.filter((message) => 'method' in message && message.method === 'tools/call')
      ).toHaveLength(1);
      expect(f.operation.signal.aborted).toBe(false);
      expect(() => f.operation.check()).not.toThrow();
      expect(f.runtime.getSnapshot()!.leaseCount).toBe(1);
      const next = f.client.callTool({ name: 'another-frame-tool', arguments: {} });
      await flush();
      const last = f.upstream.sent.findLast(
        (message) => 'method' in message && message.method === 'tools/call'
      )!;
      if ('id' in last)
        f.upstream.onmessage?.({
          jsonrpc: '2.0',
          id: last.id,
          result: { content: [{ type: 'text', text: 'parent still active' }] },
        });
      await expect(next).resolves.toMatchObject({ content: [{ text: 'parent still active' }] });
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      await f.close();
    }
  });
  it('queued iframe RPC cannot dispatch after synchronous frame unmount', async () => {
    const f = await fixture();
    vi.useFakeTimers();
    try {
      act(() => {
        f.send(201);
        f.ui.unmount();
      });
      await flush();
      expect(
        f.upstream.sent.filter((message) => 'method' in message && message.method === 'tools/call')
      ).toHaveLength(0);
      expect(vi.getTimerCount()).toBe(0);
      expect(f.runtime.getSnapshot()!.leaseCount).toBe(1);
      expect(() => f.operation.check()).not.toThrow();
    } finally {
      await f.close();
    }
  });
});
