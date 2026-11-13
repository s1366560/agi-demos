import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
  runWebOperationV2,
  WebOperationCleanupErrorV2,
} from '@/plugins/webOperationAdmissionV2';
import { BrowserWebSocketTransport } from '@/services/mcp/BrowserWebSocketTransport';
import {
  MCPAppRetainedSessionV2,
  type MCPAppSessionSnapshotV2,
} from '@/services/mcp/MCPAppRetainedSessionV2';
import { projectSandboxService } from '@/services/projectSandboxService';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useMCPClient } from '@/hooks/useMCPClient';
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
class Socket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  autoInitialize = true;
  failClose = false;
  closeCalls = 0;
  sent: Record<string, unknown>[] = [];
  constructor(readonly url: string) {
    Socket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  message(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
  send(data: string) {
    const message = JSON.parse(data) as Record<string, unknown>;
    this.sent.push(message);
    if (this.autoInitialize && message.method === 'initialize')
      void Promise.resolve().then(() =>
        this.message({
          jsonrpc: '2.0',
          id: message.id,
          result: {
            protocolVersion: '2025-06-18',
            capabilities: { tools: {}, resources: {} },
            serverInfo: { name: 'test', version: '1' },
          },
        })
      );
  }
  close() {
    this.closeCalls++;
    if (this.failClose) throw new Error('socket close failed');
    this.readyState = 2;
  }
  finish() {
    this.readyState = 3;
    this.onclose?.();
  }
}
const tick = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
};
describe('MCP App real SDK and Loader retained lifetime', () => {
  let runtime: RendererPluginRuntimeV2;
  let admission: WebOperationAdmissionV2;
  let uninstall: () => void;
  beforeEach(async () => {
    runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(profile);
    admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    uninstall = installWebOperationAdmissionV2(admission);
    vi.useFakeTimers();
    Socket.instances = [];
    vi.stubGlobal('WebSocket', Socket);
    vi.spyOn(projectSandboxService, 'ensureProxyAuthCookie').mockResolvedValue(undefined);
  });
  afterEach(async () => {
    cleanup();
    admission.setEnabled(false);
    for (const socket of Socket.instances) socket.finish();
    await admission.close().catch(() => undefined);
    uninstall();
    await runtime.close();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });
  function make(options: Record<string, unknown> = {}) {
    const snapshots: MCPAppSessionSnapshotV2[] = [];
    const session = new MCPAppRetainedSessionV2({
      projectId: 'p1',
      appId: 'app1',
      serverName: 'server1',
      enabled: true,
      maxAttempts: 0,
      initialDelayMs: 1000,
      maxDelayMs: 30000,
      gracePeriodMs: 3000,
      changed: (snapshot) => {
        snapshots.push(snapshot);
      },
      ...options,
    });
    return { session, snapshots };
  }
  async function open(options: Record<string, unknown> = {}) {
    const created = make(options);
    await tick();
    const socket = Socket.instances.at(-1)!;
    socket.open();
    await tick();
    expect(created.snapshots.at(-1)!.status).toBe('connected');
    return { ...created, socket };
  }
  it('disabled Loader admission performs zero cookie HTTP, WS, and UI initialization', async () => {
    admission.setEnabled(false);
    const onAdmitted = vi.fn();
    const { session } = make({ onAdmitted });
    await expect(session.done).rejects.toThrow();
    expect(projectSandboxService.ensureProxyAuthCookie).not.toHaveBeenCalled();
    expect(Socket.instances).toHaveLength(0);
    expect(onAdmitted).not.toHaveBeenCalled();
  });
  it('cookie completion after owner retirement cannot open a WebSocket or enable fallback', async () => {
    const cookie = deferred<void>();
    vi.mocked(projectSandboxService.ensureProxyAuthCookie).mockReturnValue(cookie.promise);
    const { session, snapshots } = make();
    await tick();
    expect(projectSandboxService.ensureProxyAuthCookie).toHaveBeenCalledWith(
      'p1',
      expect.objectContaining({ operation: expect.any(Object), signal: expect.any(AbortSignal) })
    );
    const stop = session.disconnect();
    cookie.resolve();
    await stop;
    expect(Socket.instances).toHaveLength(0);
    expect(snapshots.at(-1)!.canFallback).toBe(false);
  });
  it('real SDK pending tool RPC rejects at retirement while physical close still holds lease', async () => {
    const { session, socket, snapshots } = await open();
    const client = snapshots.at(-1)!.client!;
    const pending = client.callTool({ name: 'mutate', arguments: {} });
    void pending.catch(() => undefined);
    await tick();
    const stopped = session.disconnect();
    await expect(pending).rejects.toThrow('Connection closed');
    await client.close();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    expect(socket.readyState).toBe(2);
    socket.finish();
    await stopped;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    expect(socket.sent.filter((v) => v.method === 'tools/call')).toHaveLength(1);
  });
  it('CONNECTING retirement stores socket immediately and drains late open', async () => {
    const { session } = make();
    await tick();
    const socket = Socket.instances[0]!;
    const stopped = session.disconnect();
    let settled = false;
    void stopped.then(() => {
      settled = true;
    });
    await tick();
    expect(settled).toBe(false);
    socket.open();
    expect(socket.closeCalls).toBeGreaterThan(1);
    expect(socket.sent).toHaveLength(0);
    socket.finish();
    await stopped;
  });
  it('20 second SDK handshake timeout closes and drains before permitting HTTP fallback', async () => {
    const { session, snapshots } = make();
    await tick();
    const socket = Socket.instances[0]!;
    socket.autoInitialize = false;
    socket.open();
    await tick();
    await vi.advanceTimersByTimeAsync(20000);
    expect(socket.readyState).toBe(2);
    expect(snapshots.at(-1)!.canFallback).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.finish();
    await tick();
    expect(snapshots.at(-1)!.canFallback).toBe(true);
    expect(snapshots.at(-1)!.operation).not.toBeNull();
    await session.disconnect();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('network reconnect creates fresh SDK in same generation and never replays pending mutation', async () => {
    const { session, socket, snapshots } = await open({ maxAttempts: 1 });
    const first = snapshots.at(-1)!;
    const pending = first.client!.callTool({ name: 'mutate', arguments: {} });
    void pending.catch(() => undefined);
    await tick();
    socket.finish();
    await expect(pending).rejects.toThrow();
    await tick();
    await vi.advanceTimersByTimeAsync(1000);
    const second = Socket.instances[1]!;
    second.open();
    await tick();
    const next = snapshots.at(-1)!;
    expect(next.client).not.toBe(first.client);
    expect(next.operation).toBe(first.operation);
    expect(second.sent.some((v) => v.method === 'tools/call')).toBe(false);
    const stopped = session.disconnect();
    second.finish();
    await stopped;
    expect(vi.getTimerCount()).toBe(0);
  });
  it('manual reconnect resolves for new SDK attempt only after old actual close', async () => {
    const { session, socket, snapshots } = await open();
    let ready = false;
    const retry = session.reconnect().then(() => {
      ready = true;
    });
    await tick();
    expect(Socket.instances).toHaveLength(1);
    expect(ready).toBe(false);
    socket.finish();
    await tick();
    const next = Socket.instances[1]!;
    next.open();
    await retry;
    expect(snapshots.at(-1)!.status).toBe('connected');
    const stopped = session.disconnect();
    next.finish();
    await stopped;
  });
  it('socket cleanup failure remains observable after logical SDK close and repeated disconnect', async () => {
    const { session, socket } = await open();
    socket.failClose = true;
    const stopped = session.disconnect();
    void stopped.catch(() => undefined);
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.finish();
    await expect(stopped).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await expect(session.disconnect()).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
  });
  it('HTTP-only App mode retains operation and UI teardown completion', async () => {
    const closed = deferred<void>();
    const dispose = vi.fn(() => closed.promise);
    const { session, snapshots } = make({ enabled: false, onAdmitted: () => dispose });
    await tick();
    expect(snapshots.at(-1)!.canFallback).toBe(true);
    expect(Socket.instances).toHaveLength(0);
    const stopped = session.disconnect();
    expect(dispose).toHaveBeenCalledOnce();
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    closed.resolve();
    await stopped;
  });
  it('hook server/app identity change retires old client immediately without stale fallback', async () => {
    const hook = renderHook(
      ({ appId }) =>
        useMCPClient({
          projectId: 'p1',
          serverName: 'server1',
          appId,
          enabled: true,
          reconnectionConfig: { maxAttempts: 0 },
        }),
      { initialProps: { appId: 'app1' } }
    );
    await act(async () => {
      await tick();
      Socket.instances[0]!.open();
      await tick();
    });
    const old = hook.result.current.client!;
    hook.rerender({ appId: 'app2' });
    expect(hook.result.current.client).toBeNull();
    expect(hook.result.current.canFallback).toBe(false);
    await act(async () => {
      await expect(old.callTool({ name: 'old' })).rejects.toThrow();
      Socket.instances[0]!.finish();
      await tick();
      Socket.instances[1]!.open();
      await tick();
    });
    expect(hook.result.current.client).not.toBe(old);
    hook.unmount();
    Socket.instances[1]!.finish();
    await tick();
  });
  it('raw transport start rejects early close and SDK close callback is exactly once', async () => {
    let transport!: BrowserWebSocketTransport;
    const onclose = vi.fn();
    const ready = deferred<void>();
    const done = runWebOperationV2(async (operation) => {
      transport = new BrowserWebSocketTransport({ url: 'ws://localhost/mcp', operation });
      transport.onclose = onclose;
      const start = transport.start();
      ready.resolve();
      await expect(start).rejects.toThrow();
      await transport.close();
    });
    await ready.promise;
    Socket.instances[0]!.finish();
    await done;
    await transport.close();
    expect(onclose).toHaveBeenCalledOnce();
  });
  it('fallback permission is checked live when direct connection resumes', async () => {
    const { session, snapshots } = make();
    await tick();
    const first = Socket.instances[0]!;
    first.finish();
    await tick();
    expect(snapshots.at(-1)!.canFallback).toBe(true);
    const operation = session.assertFallback();
    const retry = session.reconnect();
    await tick();
    expect(() => session.assertFallback()).toThrow('unavailable');
    const next = Socket.instances[1]!;
    next.open();
    await retry;
    expect(snapshots.at(-1)!.operation).toBe(operation);
    expect(() => session.assertFallback()).toThrow('unavailable');
    const stopped = session.disconnect();
    next.finish();
    await stopped;
  });
  it('SDK initialize failure with a failing physical close stays handled and observable', async () => {
    const { session } = make();
    await tick();
    const socket = Socket.instances[0]!;
    socket.autoInitialize = false;
    socket.open();
    await tick();
    socket.failClose = true;
    const init = socket.sent.find((message) => message.method === 'initialize')!;
    socket.message({
      jsonrpc: '2.0',
      id: init.id,
      error: { code: -32603, message: 'initialize failed' },
    });
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.finish();
    await expect(session.done).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('owner retirement clears reconnect timers without enabling HTTP fallback', async () => {
    const { session, socket, snapshots } = await open({ maxAttempts: 5 });
    socket.finish();
    await tick();
    admission.setEnabled(false);
    admission.setEnabled(true);
    await session.done;
    await vi.advanceTimersByTimeAsync(120000);
    expect(Socket.instances).toHaveLength(1);
    expect(snapshots.at(-1)!.retired).toBe(true);
    expect(snapshots.at(-1)!.canFallback).toBe(false);
    expect(() => session.assertFallback()).toThrow();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('App frame cleanup failures remain observable after SDK and physical close', async () => {
    const { session, socket } = await open({
      onAdmitted: () => () => {
        throw new WebOperationCleanupErrorV2([new Error('frame dispose failed')]);
      },
    });
    const stopped = session.disconnect();
    socket.finish();
    await expect(stopped).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await expect(session.disconnect()).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
  });
});
