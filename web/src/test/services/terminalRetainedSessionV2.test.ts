import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  WebOperationCleanupErrorV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
import {
  TerminalRetainedSessionV2,
  type TerminalRetainedSessionOptionsV2,
} from '@/services/terminalRetainedSessionV2';
class Socket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = vi.fn();
  closeCalls = 0;
  failClose = false;
  constructor(
    readonly url: string,
    readonly protocols: string[]
  ) {
    Socket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  message(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
  close() {
    this.closeCalls++;
    if (this.failClose) throw new Error('close failed');
    this.readyState = 2;
  }
  finish(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}
const tick = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};
describe('Terminal retained session real Loader lifecycle', () => {
  let runtime: RendererPluginRuntimeV2;
  let admission: WebOperationAdmissionV2;
  let uninstall: () => void;
  beforeEach(async () => {
    runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(profile);
    admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    uninstall = installWebOperationAdmissionV2(admission);
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'terminal-test-token' } })
    );
    vi.useFakeTimers();
    Socket.instances = [];
    vi.stubGlobal('WebSocket', Socket);
  });
  afterEach(async () => {
    admission.setEnabled(false);
    for (const socket of Socket.instances) socket.finish();
    await admission.close().catch(() => undefined);
    uninstall();
    await runtime.close();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    localStorage.clear();
  });
  function make(overrides: Partial<TerminalRetainedSessionOptionsV2> = {}) {
    const options = {
      sandboxId: 'sandbox-a',
      projectId: 'project-a',
      onConnect: vi.fn(),
      onOutput: vi.fn(),
      onDisconnect: vi.fn(),
      onError: vi.fn(),
      ...overrides,
    };
    return { session: new TerminalRetainedSessionV2(options), options };
  }
  async function open(overrides: Partial<TerminalRetainedSessionOptionsV2> = {}) {
    const created = make(overrides);
    const ready = created.session.connect();
    await tick();
    const socket = Socket.instances.at(-1)!;
    socket.open();
    socket.message({ type: 'connected', session_id: 'pty-a', cols: 80, rows: 24 });
    await ready;
    return { ...created, socket };
  }
  it('disabled admission creates zero socket and zero xterm initialization', async () => {
    admission.setEnabled(false);
    const onAdmitted = vi.fn();
    const { session } = make({ onAdmitted });
    await expect(session.connect()).rejects.toThrow();
    await expect(session.disconnect()).rejects.toThrow();
    expect(Socket.instances).toHaveLength(0);
    expect(onAdmitted).not.toHaveBeenCalled();
  });
  it('constructor is inert and readiness requires connected frame, not socket open', async () => {
    const { session, options } = make();
    expect(Socket.instances).toHaveLength(0);
    let ready = false;
    const opening = session.connect().then(() => {
      ready = true;
    });
    await tick();
    const socket = Socket.instances[0]!;
    socket.open();
    await tick();
    expect(ready).toBe(false);
    expect(session.sendInput('early')).toBe(false);
    socket.message({ type: 'connected', session_id: 'pty-a' });
    await opening;
    expect(options.onConnect).toHaveBeenCalledWith('pty-a');
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    const stopping = session.disconnect();
    socket.finish();
    await stopping;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('same generation retries reuse captured token and adopted session, without input replay', async () => {
    const { session, socket } = await open();
    const protocols = socket.protocols;
    expect(session.sendInput('one\n')).toBe(true);
    socket.finish(1006);
    expect(session.sendInput('offline\n')).toBe(false);
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'changed-token-without-owner-event' } })
    );
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    let ready = false;
    const again = session.connect().then(() => {
      ready = true;
    });
    await vi.advanceTimersByTimeAsync(3000);
    const next = Socket.instances[1]!;
    expect(next.protocols).toEqual(protocols);
    expect(new URL(next.url).searchParams.get('session_id')).toBe('pty-a');
    expect(ready).toBe(false);
    next.open();
    next.message({ type: 'connected', session_id: 'pty-a' });
    await again;
    expect(next.send).not.toHaveBeenCalled();
    expect(session.sendInput('two\n')).toBe(true);
    expect(next.send).toHaveBeenCalledExactlyOnceWith(
      JSON.stringify({ type: 'input', data: 'two\n' })
    );
    const stopped = session.disconnect();
    next.finish();
    await stopped;
  });
  it('CONNECTING cancellation waits actual close and rejects late open', async () => {
    const { session } = make();
    void session.connect().catch(() => undefined);
    await tick();
    const socket = Socket.instances[0]!;
    let settled = false;
    const stopped = session.disconnect().then(() => {
      settled = true;
    });
    await tick();
    expect(settled).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.open();
    expect(socket.closeCalls).toBeGreaterThan(1);
    socket.finish();
    await stopped;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('owner retirement cancels backoff and old callbacks; new owner needs a new instance', async () => {
    const { session, socket, options } = await open();
    const stale = socket.onmessage;
    socket.finish(1006);
    await tick();
    admission.setEnabled(false);
    admission.setEnabled(true);
    await session.disconnect();
    await vi.advanceTimersByTimeAsync(60000);
    stale?.({ data: JSON.stringify({ type: 'output', data: 'late' }) });
    expect(options.onOutput).not.toHaveBeenCalled();
    expect(Socket.instances).toHaveLength(1);
    await expect(session.connect()).rejects.toThrow();
    const fresh = await open();
    const stopped = fresh.session.disconnect();
    fresh.socket.finish();
    await stopped;
  });
  it('onerror is not actual close and normal network failure does not mark cleanup', async () => {
    const { session, socket } = await open();
    socket.onerror?.();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.finish();
    await expect(session.disconnect()).rejects.toThrow('WebSocket connection error');
    await expect(admission.close()).resolves.toBeUndefined();
  });
  it('close failure remains observable after actual close and repeated disconnect', async () => {
    const { session, socket } = await open();
    socket.failClose = true;
    const stopped = session.disconnect();
    let settled = false;
    void stopped.catch(() => {
      settled = true;
    });
    await tick();
    expect(settled).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.finish();
    await expect(stopped).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await expect(session.disconnect()).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
  });
  it('xterm cleanup runs synchronously but asynchronous completion retains the generation', async () => {
    let finish!: () => void;
    const cleanup = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        })
    );
    const { session, socket } = await open({ onAdmitted: () => cleanup });
    const stopped = session.disconnect();
    expect(cleanup).toHaveBeenCalledOnce();
    socket.finish();
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    finish();
    await stopped;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('cleanup registered after synchronous onAdmitted retirement still runs exactly once', async () => {
    const cleanup = vi.fn();
    let session!: TerminalRetainedSessionV2;
    ({ session } = make({
      onAdmitted: () => {
        void session.disconnect();
        return cleanup;
      },
    }));
    await expect(session.connect()).rejects.toThrow();
    await session.disconnect();
    expect(cleanup).toHaveBeenCalledOnce();
    expect(Socket.instances).toHaveLength(0);
  });
  it('retries five times under one lease and stops without creating a sixth retry', async () => {
    const { session } = make();
    const ready = session.connect().catch((error) => error);
    await tick();
    for (const delay of [3000, 6000, 12000, 24000, 30000]) {
      Socket.instances.at(-1)!.finish(1006);
      await tick();
      await vi.advanceTimersByTimeAsync(delay);
    }
    expect(Socket.instances).toHaveLength(6);
    Socket.instances.at(-1)!.finish(1006);
    await tick();
    await expect(session.disconnect()).rejects.toThrow('Unable to reconnect');
    expect(await ready).toBeInstanceOf(Error);
    await vi.advanceTimersByTimeAsync(90000);
    expect(Socket.instances).toHaveLength(6);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('old captured message handlers cannot write after reconnect and heartbeat/resize stop on retirement', async () => {
    const { session, socket, options } = await open();
    const stale = socket.onmessage;
    socket.finish(1006);
    await tick();
    await vi.advanceTimersByTimeAsync(3000);
    const next = Socket.instances[1]!;
    next.open();
    next.message({ type: 'connected', session_id: 'pty-a' });
    stale?.({ data: JSON.stringify({ type: 'output', data: 'old' }) });
    expect(options.onOutput).not.toHaveBeenCalled();
    expect(session.resize(120, 40)).toBe(true);
    await vi.advanceTimersByTimeAsync(30000);
    expect(next.send).toHaveBeenCalledWith(JSON.stringify({ type: 'ping' }));
    const count = next.send.mock.calls.length;
    const stopped = session.disconnect();
    expect(session.resize(100, 30)).toBe(false);
    await vi.advanceTimersByTimeAsync(60000);
    expect(next.send).toHaveBeenCalledTimes(count);
    next.finish();
    await stopped;
  });
  it('admitted UI cleanup failures persist after actual close and are not swallowed by connect catch', async () => {
    const { session, socket } = await open({
      onAdmitted: () => () => {
        throw new Error('xterm disposal failed');
      },
    });
    const stopped = session.disconnect();
    socket.finish();
    await expect(stopped).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    await expect(session.disconnect()).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
  });
  it('constructor owner cannot be reused after an owner transition', async () => {
    const { session } = make();
    admission.setEnabled(false);
    admission.setEnabled(true);
    await expect(session.connect()).rejects.toThrow();
    await session.disconnect();
    expect(Socket.instances).toHaveLength(0);
  });
  it('final business errors reach UI before its cleanup invalidates callbacks', async () => {
    let active = true;
    const visible = vi.fn();
    const { session, socket } = await open({
      onAdmitted: () => () => {
        active = false;
      },
      onError: (error) => {
        if (active) visible(error.message);
      },
    });
    socket.finish(1006);
    await tick();
    for (const delay of [3000, 6000, 12000, 24000, 30000]) {
      await vi.advanceTimersByTimeAsync(delay);
      Socket.instances.at(-1)!.finish(1006);
      await tick();
    }
    await expect(session.disconnect()).rejects.toThrow('Unable to reconnect');
    expect(visible).toHaveBeenCalledWith(
      'Unable to reconnect after several attempts. Please retry manually.'
    );
    expect(active).toBe(false);
  });
});
