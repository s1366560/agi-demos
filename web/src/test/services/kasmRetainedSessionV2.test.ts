import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  WebOperationCleanupErrorV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
import { KasmRetainedSessionV2, type KasmAttemptContextV2 } from '@/services/kasmRetainedSessionV2';
class Socket extends EventTarget {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: ((e: Event) => void) | null = null;
  onclose: ((e: Event) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readonly sent = vi.fn();
  send(data: unknown) {
    this.sent(data);
  }
  closeCalls = 0;
  failClose = false;
  constructor(
    readonly url: string,
    readonly protocols: string[]
  ) {
    super();
    Socket.instances.push(this);
  }
  emit(name: 'open' | 'close' | 'error') {
    const e = new Event(name);
    this.dispatchEvent(e);
    this[`on${name}`]?.(e);
  }
  open() {
    this.readyState = 1;
    this.emit('open');
  }
  close() {
    this.closeCalls++;
    if (this.failClose) throw new Error('physical close failed');
    this.readyState = 2;
  }
  finish() {
    this.readyState = 3;
    this.emit('close');
  }
}
const tick = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
};
describe('Kasm retained session actual Loader', () => {
  let runtime: RendererPluginRuntimeV2;
  let admission: WebOperationAdmissionV2;
  let uninstall: () => void;
  let cleanupFailure: boolean;
  beforeEach(async () => {
    runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(profile);
    admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    uninstall = installWebOperationAdmissionV2(admission);
    cleanupFailure = false;
    Socket.instances = [];
    vi.stubGlobal('WebSocket', Socket);
    vi.useFakeTimers();
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'kasm-fixture-token' } })
    );
  });
  afterEach(async () => {
    try {
      admission.setEnabled(false);
      for (const socket of Socket.instances) socket.finish();
      if (cleanupFailure) await expect(admission.close()).rejects.toThrow();
      else await admission.close();
    } finally {
      uninstall();
      await runtime.close();
      vi.unstubAllGlobals();
      vi.useRealTimers();
      localStorage.clear();
    }
  });
  function make() {
    const attempts: KasmAttemptContextV2[] = [];
    const disposals: ReturnType<typeof vi.fn>[] = [];
    const cleanup = vi.fn(),
      onStateChange = vi.fn(),
      onDisconnect = vi.fn(),
      onError = vi.fn();
    const createAttempt = vi.fn(
      (_socket: WebSocket, _operation: unknown, attempt: KasmAttemptContextV2) => {
        attempts.push(attempt);
        const dispose = vi.fn();
        disposals.push(dispose);
        return { dispose };
      }
    );
    const session = new KasmRetainedSessionV2({
      projectId: 'project-a',
      sandboxId: 'sandbox-a',
      wsUrl: 'ws://localhost/kasm',
      createAttempt,
      onStateChange,
      onDisconnect,
      onError,
      onAdmitted: () => cleanup,
    });
    return {
      session,
      attempts,
      disposals,
      cleanup,
      createAttempt,
      onStateChange,
      onDisconnect,
      onError,
    };
  }
  async function open() {
    const value = make(),
      ready = value.session.connect();
    await tick();
    const socket = Socket.instances[0]!;
    socket.open();
    await tick();
    value.attempts[0]!.connected();
    await ready;
    return { ...value, socket };
  }
  it('disabled admission constructs neither socket nor RFB attempt', async () => {
    admission.setEnabled(false);
    const value = make();
    await expect(value.session.connect()).rejects.toThrow();
    void value.session.disconnect().catch(() => undefined);
    expect(Socket.instances).toHaveLength(0);
    expect(value.createAttempt).not.toHaveBeenCalled();
  });
  it('CONNECTING owner retirement rejects late open and retains lease until actual close', async () => {
    const value = make();
    void value.session.connect().catch(() => undefined);
    await tick();
    const socket = Socket.instances[0]!;
    admission.setEnabled(false);
    let settled = false;
    const stopping = value.session.disconnect().then(() => {
      settled = true;
    });
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    expect(settled).toBe(false);
    socket.open();
    await tick();
    expect(value.onStateChange).not.toHaveBeenCalledWith('connected');
    expect(socket.closeCalls).toBeGreaterThanOrEqual(2);
    socket.finish();
    await stopping;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('RFB disconnect and three-second timeout do not substitute for physical close', async () => {
    const value = await open();
    value.attempts[0]!.disconnected('rfb timeout');
    await vi.advanceTimersByTimeAsync(3000);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    expect(Socket.instances).toHaveLength(1);
    expect(value.disposals[0]).toHaveBeenCalledOnce();
    const stopping = value.session.disconnect();
    value.socket.finish();
    await stopping;
  });
  it('close failure runs other cleanup and persists after actual close', async () => {
    const value = await open();
    cleanupFailure = true;
    value.socket.failClose = true;
    const stopping = value.session.disconnect();
    let settled = false;
    void stopping.catch(() => {
      settled = true;
    });
    await tick();
    expect(value.disposals[0]).toHaveBeenCalledOnce();
    expect(value.cleanup).toHaveBeenCalledOnce();
    expect(settled).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    value.socket.finish();
    await expect(stopping).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await expect(value.session.disconnect()).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await vi.advanceTimersByTimeAsync(60000);
    expect(Socket.instances).toHaveLength(1);
  });
  it('retry freezes authentication and neither replays input nor accepts old callbacks', async () => {
    const value = await open();
    value.socket.send('user input');
    const old = value.attempts[0]!;
    old.disconnected('network');
    value.socket.finish();
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'changed-token' } })
    );
    await tick();
    await vi.advanceTimersByTimeAsync(1000);
    const next = Socket.instances[1]!;
    expect(next.protocols).toEqual(value.socket.protocols);
    next.open();
    await tick();
    value.attempts[1]!.connected();
    const states = value.onStateChange.mock.calls.length,
      errors = value.onError.mock.calls.length,
      disconnects = value.onDisconnect.mock.calls.length;
    expect(() => old.connected()).toThrow();
    expect(() => old.disconnected('stale')).toThrow();
    expect(() => old.fail(new Error('stale'))).toThrow();
    expect(() => value.socket.send('late input')).toThrow();
    expect(value.socket.sent).toHaveBeenCalledExactlyOnceWith('user input');
    await tick();
    expect(value.onStateChange).toHaveBeenCalledTimes(states);
    expect(value.onError).toHaveBeenCalledTimes(errors);
    expect(value.onDisconnect).toHaveBeenCalledTimes(disconnects);
    expect(next.sent).not.toHaveBeenCalled();
    const stopping = value.session.disconnect();
    next.finish();
    await stopping;
  });
  it('actual socket close still waits for asynchronous attempt disposal', async () => {
    const value = await open();
    let complete!: () => void;
    value.disposals[0]!.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve;
        })
    );
    const stopping = value.session.disconnect();
    value.socket.finish();
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    complete();
    await stopping;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('RFB constructor failure closes its allocated socket before releasing the parent', async () => {
    const value = make();
    value.createAttempt.mockImplementationOnce(() => {
      throw new Error('RFB constructor failed');
    });
    const ready = value.session.connect();
    const rejected = expect(ready).rejects.toThrow('RFB constructor failed');
    await tick();
    const socket = Socket.instances[0]!;
    expect(socket.closeCalls).toBeGreaterThan(0);
    expect(value.cleanup).toHaveBeenCalledOnce();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.finish();
    await rejected;
    await expect(value.session.disconnect()).rejects.toThrow('RFB constructor failed');
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('parent cleanup failure stays observable after child disposal and physical close', async () => {
    const value = await open();
    cleanupFailure = true;
    value.cleanup.mockImplementation(() => {
      throw new Error('parent cleanup failed');
    });
    const stopping = value.session.disconnect();
    const rejected = expect(stopping).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    expect(value.disposals[0]).toHaveBeenCalledOnce();
    expect(value.socket.closeCalls).toBeGreaterThan(0);
    value.socket.finish();
    await rejected;
    await expect(value.session.disconnect()).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
  });
  it('attempt retirement aborts and drains its child before same-parent retry', async () => {
    const value = await open();
    let childSignal!: AbortSignal;
    let finish!: () => void;
    const child = value.attempts[0]!.runChild(async (operation) => {
      childSignal = operation.signal;
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      return 'late clipboard result';
    });
    const cancelled = expect(child).rejects.toMatchObject({ name: 'AbortError' });
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(2);
    value.attempts[0]!.disconnected('attempt only');
    expect(childSignal.aborted).toBe(true);
    value.socket.finish();
    await vi.advanceTimersByTimeAsync(60000);
    expect(runtime.getSnapshot()!.leaseCount).toBe(2);
    expect(Socket.instances).toHaveLength(1);
    finish();
    await cancelled;
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(Socket.instances).toHaveLength(2);
    const next = Socket.instances[1]!;
    next.open();
    value.attempts[1]!.connected();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    const stopping = value.session.disconnect();
    next.finish();
    await stopping;
  });
  it('attempt child cleanup failure persists and prevents retry after actual close', async () => {
    const value = await open();
    cleanupFailure = true;
    let finish!: () => void;
    const child = value.attempts[0]!.runChild(async () => {
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      throw new WebOperationCleanupErrorV2([new Error('clipboard cleanup failed')]);
    });
    const failed = expect(child).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await tick();
    value.attempts[0]!.disconnected('attempt only');
    value.socket.finish();
    await vi.advanceTimersByTimeAsync(60000);
    expect(Socket.instances).toHaveLength(1);
    expect(runtime.getSnapshot()!.leaseCount).toBe(2);
    finish();
    await failed;
    await tick();
    await expect(value.session.done).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await expect(value.session.disconnect()).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await vi.advanceTimersByTimeAsync(60000);
    expect(Socket.instances).toHaveLength(1);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('owner retirement cancels backoff and prevents cross-owner reconnect', async () => {
    const value = await open();
    value.attempts[0]!.disconnected('network');
    value.socket.finish();
    await tick();
    admission.setEnabled(false);
    admission.setEnabled(true);
    await value.session.disconnect();
    await vi.advanceTimersByTimeAsync(60000);
    expect(Socket.instances).toHaveLength(1);
    await expect(value.session.connect()).rejects.toThrow();
  });
});
