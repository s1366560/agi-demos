import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';

import { createWebSocketAuthProtocols } from '@/services/client/urlUtils';
import { WebSocketConnection } from '@/services/agent/wsConnection';

class ManualWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  static instances: ManualWebSocket[] = [];

  url: string;
  protocols: string | string[] | undefined;
  readyState = ManualWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  sentMessages: string[] = [];
  autoClose = true;
  closeCalls = 0;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    ManualWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sentMessages.push(data);
  }

  close(code = 1000, reason = ''): void {
    this.closeCalls++;
    this.readyState = ManualWebSocket.CLOSING;
    if (this.autoClose) this.finishClose(code, reason);
  }

  finishClose(code = 1000, reason = ''): void {
    this.readyState = ManualWebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }

  open(): void {
    this.readyState = ManualWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }
}

describe('WebSocketConnection reconnect recovery', () => {
  let runtime: RendererPluginRuntimeV2;
  let admission: WebOperationAdmissionV2;
  let uninstall: () => void;
  let expectedCleanupFailure: Error | undefined;
  beforeEach(async () => {
    expectedCleanupFailure = undefined;
    runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(profile);
    admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    uninstall = installWebOperationAdmissionV2(admission);
    vi.useFakeTimers();
    ManualWebSocket.instances = [];
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'agent-ws-test-token' } })
    );
    vi.stubGlobal('WebSocket', ManualWebSocket);
  });

  afterEach(async () => {
    try {
      admission.setEnabled(false);
      for (const socket of ManualWebSocket.instances) socket.finishClose();
      if (expectedCleanupFailure) {
        await expect(admission.close()).rejects.toMatchObject({
          name: 'AggregateError',
          errors: [expectedCleanupFailure],
        });
      } else {
        await admission.close();
      }
    } finally {
      uninstall();
      try {
        await runtime.close();
      } finally {
        localStorage.clear();
        vi.unstubAllGlobals();
        vi.useRealTimers();
      }
    }
  });

  it('does not let a pre-open close pin the reconnect path to a stale promise', async () => {
    const onReconnect = vi.fn();
    const connection = new WebSocketConnection({
      sessionId: 'session-1',
      onReconnect,
    });

    const firstConnect = connection.connect();
    await Promise.resolve();
    expect(ManualWebSocket.instances).toHaveLength(1);

    ManualWebSocket.instances[0]?.close(1006, 'network-reset');
    await expect(firstConnect).rejects.toThrow('WebSocket closed before connection opened: 1006');

    await vi.advanceTimersByTimeAsync(1000);
    expect(ManualWebSocket.instances).toHaveLength(2);

    ManualWebSocket.instances[1]?.open();
    expect(connection.getStatus()).toBe('connected');
    expect(connection.isConnected()).toBe(true);
    expect(onReconnect).toHaveBeenCalledTimes(1);

    await connection.disconnect();
  });

  it('sends the server-supported heartbeat message while connected', async () => {
    const connection = new WebSocketConnection({
      sessionId: 'session-heartbeat',
    });

    const connectPromise = connection.connect();
    await Promise.resolve();
    const socket = ManualWebSocket.instances[0];
    expect(socket).toBeDefined();
    socket?.open();
    await expect(connectPromise).resolves.toBeUndefined();

    await vi.advanceTimersByTimeAsync(30000);

    expect(socket?.sentMessages.map((message) => JSON.parse(message))).toContainEqual({
      type: 'heartbeat',
    });

    await connection.disconnect();
  });
  it('disabled generation starts zero sockets', async () => {
    admission.setEnabled(false);
    const connection = new WebSocketConnection({ sessionId: 'disabled' });
    await expect(connection.connect()).rejects.toThrow('web_operation_generation_unavailable');
    expect(ManualWebSocket.instances).toHaveLength(0);
  });

  it('real Loader lease survives onopen and drains CONNECTING cancellation until actual close', async () => {
    const connection = new WebSocketConnection({ sessionId: 'pending' });
    const opening = connection.connect();
    const rejected = expect(opening).rejects.toMatchObject({ name: 'AbortError' });
    await Promise.resolve();
    const socket = ManualWebSocket.instances[0]!;
    socket.autoClose = false;
    let done = false;
    const stopping = connection.disconnect().then(() => {
      done = true;
    });
    await rejected;
    expect(done).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.open();
    expect(connection.isConnected()).toBe(false);
    expect(socket.closeCalls).toBeGreaterThan(1);
    socket.finishClose();
    await stopping;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });

  it('error does not release or reconnect until close; retry uses same generation and captured token', async () => {
    const connection = new WebSocketConnection({ sessionId: 'retry' });
    const opened = connection.connect();
    await Promise.resolve();
    const socket = ManualWebSocket.instances[0]!;
    socket.open();
    await opened;
    const context = connection.getOperationContext();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.autoClose = false;
    socket.onerror?.(new Event('error'));
    await vi.advanceTimersByTimeAsync(2000);
    expect(ManualWebSocket.instances).toHaveLength(1);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'different-token' } })
    );
    socket.finishClose();
    await vi.advanceTimersByTimeAsync(1000);
    const next = ManualWebSocket.instances[1]!;
    expect(next.protocols).toEqual(socket.protocols);
    next.open();
    expect(connection.getOperationContext()).toBe(context);
    await connection.disconnect();
  });

  it('old socket callbacks cannot retire or emit through a replacement attempt', async () => {
    const messages = vi.fn(),
      connection = new WebSocketConnection({ sessionId: 'late', onMessage: messages });
    const opening = connection.connect();
    await Promise.resolve();
    const old = ManualWebSocket.instances[0]!;
    old.open();
    await opening;
    const message = old.onmessage!,
      close = old.onclose!;
    old.close();
    await vi.advanceTimersByTimeAsync(1000);
    const next = ManualWebSocket.instances[1]!;
    next.open();
    message({ data: '{"type":"old"}' } as MessageEvent);
    close({ code: 1006 } as CloseEvent);
    expect(messages).not.toHaveBeenCalled();
    expect(connection.isConnected()).toBe(true);
    await connection.disconnect();
  });

  it('retirement revokes context synchronously and explicit new connect waits old socket drain', async () => {
    const connection = new WebSocketConnection({ sessionId: 'retire' }),
      retired = vi.fn();
    connection.onRetired((context) => {
      expect(connection.getOperationContext()).toBeUndefined();
      retired(context);
    });
    const opening = connection.connect();
    await Promise.resolve();
    const old = ManualWebSocket.instances[0]!;
    old.open();
    await opening;
    const context = connection.getOperationContext();
    old.autoClose = false;
    admission.invalidate();
    expect(retired).toHaveBeenCalledWith(context);
    expect(connection.send({ type: 'forbidden' })).toBe(false);
    const nextOpening = connection.connect();
    await Promise.resolve();
    expect(ManualWebSocket.instances).toHaveLength(1);
    old.finishClose();
    await vi.advanceTimersByTimeAsync(0);
    expect(ManualWebSocket.instances).toHaveLength(2);
    ManualWebSocket.instances[1]!.open();
    await nextOpening;
    await connection.disconnect();
    expect(retired).toHaveBeenCalledTimes(2);
  });

  it('retry exhaustion releases the one operation without readmitting or leaving timers', async () => {
    const connection = new WebSocketConnection({ sessionId: 'exhaust' });
    const opening = connection.connect();
    const rejected = expect(opening).rejects.toThrow('closed before');
    await Promise.resolve();
    ManualWebSocket.instances[0]!.close(1006);
    await rejected;
    for (let i = 0; i < 5; i++) {
      await vi.advanceTimersByTimeAsync(1000 * 2 ** i);
      ManualWebSocket.instances.at(-1)!.close(1006);
    }
    await vi.advanceTimersByTimeAsync(0);
    expect(ManualWebSocket.instances).toHaveLength(6);
    expect(connection.getOperationContext()).toBeUndefined();
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('a synchronous connecting listener retirement prevents socket construction', async () => {
    const connection = new WebSocketConnection({ sessionId: 'listener' });
    connection.onStatusChange((status) => {
      if (status === 'connecting') void connection.disconnect();
    });
    await expect(connection.connect()).rejects.toMatchObject({ name: 'AbortError' });
    await connection.disconnect();
    expect(ManualWebSocket.instances).toHaveLength(0);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });

  it('connect during reconnection waits for the replacement socket to open', async () => {
    const connection = new WebSocketConnection({ sessionId: 'ready-again' });
    const first = connection.connect();
    await Promise.resolve();
    ManualWebSocket.instances[0]!.open();
    await first;
    ManualWebSocket.instances[0]!.close();
    let ready = false;
    const second = connection.connect().then(() => {
      ready = true;
    });
    await Promise.resolve();
    expect(ready).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(ready).toBe(false);
    ManualWebSocket.instances[1]!.open();
    await second;
    expect(ready).toBe(true);
    await connection.disconnect();
  });

  it('owner change while a new connect waits for retired socket rejects with zero new sockets', async () => {
    const connection = new WebSocketConnection({ sessionId: 'owner-wait' });
    const first = connection.connect();
    await Promise.resolve();
    const socket = ManualWebSocket.instances[0]!;
    socket.open();
    await first;
    socket.autoClose = false;
    const stop = connection.disconnect();
    const next = connection.connect();
    const rejected = expect(next).rejects.toMatchObject({ name: 'AbortError' });
    admission.invalidate();
    socket.finishClose();
    await stop;
    await rejected;
    expect(ManualWebSocket.instances).toHaveLength(1);
  });

  it('disconnect preserves a non-cancellation operation failure', async () => {
    admission.setEnabled(false);
    const connection = new WebSocketConnection({ sessionId: 'failure' });
    await expect(connection.connect()).rejects.toThrow('web_operation_generation_unavailable');
    await expect(connection.disconnect()).rejects.toThrow('web_operation_generation_unavailable');
  });

  it('actual generation release failure remains visible from disconnect after socket closes', async () => {
    uninstall();
    await admission.close();
    const cleanupFailure = new Error('release-failed');
    expectedCleanupFailure = cleanupFailure;
    admission = new WebOperationAdmissionV2({
      getSnapshot: runtime.getSnapshot,
      subscribe: runtime.subscribe,
      acquire: () => {
        const lease = runtime.acquire();
        const release = lease.release.bind(lease);
        lease.release = async () => {
          await release();
          throw cleanupFailure;
        };
        return lease;
      },
    });
    admission.setEnabled(true);
    uninstall = installWebOperationAdmissionV2(admission);
    const connection = new WebSocketConnection({ sessionId: 'cleanup-failure' });
    const opened = connection.connect();
    await Promise.resolve();
    ManualWebSocket.instances[0]!.open();
    await opened;
    await expect(connection.disconnect()).rejects.toBeInstanceOf(AggregateError);
    expect(ManualWebSocket.instances[0]!.readyState).toBe(ManualWebSocket.CLOSED);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('connect between native CLOSING and close event keeps its pending readiness promise', async () => {
    const connection = new WebSocketConnection({ sessionId: 'closing-gap' });
    const first = connection.connect();
    await Promise.resolve();
    const socket = ManualWebSocket.instances[0]!;
    socket.open();
    await first;
    socket.autoClose = false;
    socket.close();
    let ready = false;
    const second = connection.connect().then(() => {
      ready = true;
    });
    socket.finishClose();
    await vi.advanceTimersByTimeAsync(1000);
    expect(ready).toBe(false);
    ManualWebSocket.instances[1]!.open();
    await second;
    expect(ready).toBe(true);
    await connection.disconnect();
  });
  it('A to B to C while A drains opens only C and does not reuse B pending connect', async () => {
    const connection = new WebSocketConnection({ sessionId: 'owner-chain' });
    const a = connection.connect();
    await Promise.resolve();
    const old = ManualWebSocket.instances[0]!;
    old.open();
    await a;
    old.autoClose = false;
    admission.invalidate();
    localStorage.setItem('memstack-auth-storage', JSON.stringify({ state: { token: 'token-B' } }));
    const b = connection.connect();
    const rejected = expect(b).rejects.toMatchObject({ name: 'AbortError' });
    admission.invalidate();
    localStorage.setItem('memstack-auth-storage', JSON.stringify({ state: { token: 'token-C' } }));
    const c = connection.connect();
    expect(c).not.toBe(b);
    old.finishClose();
    await vi.advanceTimersByTimeAsync(0);
    await rejected;
    expect(ManualWebSocket.instances).toHaveLength(2);
    const latest = ManualWebSocket.instances[1]!;
    expect(latest.protocols).toEqual(createWebSocketAuthProtocols('token-C'));
    latest.open();
    await c;
    await connection.disconnect();
  });
  it('close invocation failure holds the lease until actual close then rejects disconnect', async () => {
    const connection = new WebSocketConnection({ sessionId: 'close-throws' });
    const opening = connection.connect();
    const cancelled = expect(opening).rejects.toMatchObject({ name: 'AbortError' });
    await Promise.resolve();
    const socket = ManualWebSocket.instances[0]!;
    const failure = new Error('native-close-failed');
    socket.close = () => {
      throw failure;
    };
    let settled = false;
    const stop = connection.disconnect();
    void stop.then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      }
    );
    await cancelled;
    expect(settled).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.open();
    expect(settled).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.finishClose();
    await expect(stop).rejects.toBe(failure);
    await expect(connection.disconnect()).rejects.toBe(failure);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
});
