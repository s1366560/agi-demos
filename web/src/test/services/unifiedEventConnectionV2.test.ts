import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
import { unifiedEventService as service } from '@/services/unifiedEventService';
const auth = vi.hoisted(() => ({ token: 'synthetic-a' }));
vi.mock('@/utils/tokenResolver', () => ({ getAuthToken: () => auth.token }));
vi.mock('@/utils/logger', () => ({ logger: { debug: vi.fn(), error: vi.fn() } }));
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
  sent: string[] = [];
  constructor(
    readonly url: string,
    readonly protocols: string[]
  ) {
    Socket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  close() {
    this.readyState = 2;
  }
  closed() {
    this.readyState = 3;
    this.onclose?.({ code: 1000 });
  }
  message(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}
let runtime: RendererPluginRuntimeV2, admission: WebOperationAdmissionV2, uninstall: () => void;
beforeEach(async () => {
  vi.useFakeTimers();
  Socket.instances = [];
  auth.token = 'synthetic-a';
  vi.stubGlobal('WebSocket', Socket);
  runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  uninstall = installWebOperationAdmissionV2(admission);
});
afterEach(async () => {
  const stop = service.disconnect();
  for (const socket of Socket.instances) socket.closed();
  await stop.catch(() => undefined);
  uninstall();
  await admission.close();
  await runtime.close();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const flush = () => vi.advanceTimersByTimeAsync(0);
async function connected() {
  const ready = service.connect();
  await flush();
  const socket = Socket.instances.at(-1)!;
  socket.open();
  await ready;
  return socket;
}
describe('Unified events retain one operation through socket retirement', () => {
  it('rejects disabled admission before subscription or socket creation', async () => {
    admission.setEnabled(false);
    service.subscribeProject('p', vi.fn());
    await expect(service.connect()).rejects.toThrow('web_operation_generation_unavailable');
    expect(Socket.instances).toHaveLength(0);
    expect(service.getStats().totalTopics).toBe(0);
  });
  it('retains its lease after open and until the actual close event, including repeated disconnect', async () => {
    const socket = await connected();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    let firstDone = false,
      secondDone = false;
    const first = service.disconnect().then(() => {
      firstDone = true;
    });
    const second = service.disconnect().then(() => {
      secondDone = true;
    });
    await flush();
    expect(firstDone).toBe(false);
    expect(secondDone).toBe(false);
    expect(service.send({ type: 'heartbeat' })).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    socket.closed();
    await Promise.all([first, second]);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('does not treat onerror as a closed socket', async () => {
    const socket = await connected();
    socket.onerror?.();
    await flush();
    expect(socket.readyState).toBe(Socket.CLOSING);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    const stopped = service.disconnect();
    socket.closed();
    await stopped;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('reconnects under the same captured token and waits for the replacement open', async () => {
    const first = await connected();
    first.closed();
    auth.token = 'synthetic-b';
    let ready = false;
    const reconnect = service.connect().then(() => {
      ready = true;
    });
    await vi.advanceTimersByTimeAsync(1000);
    expect(ready).toBe(false);
    const second = Socket.instances[1]!;
    expect(second.protocols).toEqual(['memstack.auth', 'synthetic-a']);
    second.open();
    await reconnect;
    expect(ready).toBe(true);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
  });
  it('waits for old owner closure and prevents old unsubscribe from deleting a new owner topic', async () => {
    const oldHandler = vi.fn(),
      newHandler = vi.fn();
    const unsubscribeOld = service.subscribeProject('same', oldHandler);
    const firstReady = service.connect();
    await flush();
    const first = Socket.instances[0]!;
    first.open();
    await firstReady;
    admission.invalidate();
    auth.token = 'synthetic-b';
    service.subscribeProject('same', newHandler);
    const newReady = service.connect();
    await flush();
    expect(Socket.instances).toHaveLength(1);
    unsubscribeOld();
    expect(service.getStats().totalTopics).toBe(1);
    first.closed();
    await flush();
    const second = Socket.instances[1]!;
    expect(second.protocols[1]).toBe('synthetic-b');
    second.open();
    await newReady;
    second.message({
      type: 'conversation_created',
      project_id: 'same',
      routing_key: 'project:same',
    });
    expect(oldHandler).not.toHaveBeenCalled();
    expect(newHandler).toHaveBeenCalledOnce();
  });
  it('cancels a pending reconnect on owner retirement instead of invoking new admission', async () => {
    const socket = await connected();
    socket.closed();
    admission.invalidate();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(Socket.instances).toHaveLength(1);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('rejects a superseded owner waiting for the previous actual close without creating its socket', async () => {
    const first = await connected();
    admission.invalidate();
    const waiting = service.connect();
    const rejection = expect(waiting).rejects.toMatchObject({ name: 'AbortError' });
    await flush();
    admission.invalidate();
    first.closed();
    await rejection;
    await flush();
    expect(Socket.instances).toHaveLength(1);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
});

it('keeps the newest C connect intent when B was awaiting A close', async () => {
  const first = await connected();
  admission.invalidate();
  auth.token = 'synthetic-b';
  const middle = service.connect();
  const rejected = expect(middle).rejects.toMatchObject({ name: 'AbortError' });
  await flush();
  admission.invalidate();
  auth.token = 'synthetic-c';
  let thirdReady = false;
  const newest = service.connect().then(() => {
    thirdReady = true;
  });
  await flush();
  expect(Socket.instances).toHaveLength(1);
  expect(thirdReady).toBe(false);
  first.closed();
  await rejected;
  await flush();
  const last = Socket.instances[1]!;
  expect(last.protocols[1]).toBe('synthetic-c');
  last.open();
  await newest;
  expect(service.isConnected()).toBe(true);
  expect(runtime.getSnapshot()!.leaseCount).toBe(1);
});

it('reports close failure only after the socket actually closes', async () => {
  const socket = await connected();
  vi.spyOn(socket, 'close').mockImplementation(() => {
    throw new Error('close failed');
  });
  const stop = service.disconnect();
  const rejection = expect(stop).rejects.toThrow('close failed');
  await flush();
  expect(runtime.getSnapshot()!.leaseCount).toBe(1);
  socket.closed();
  await rejection;
  expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  await expect(service.disconnect()).rejects.toThrow('close failed');
});

it('does not construct a socket when a connecting status listener synchronously disconnects', async () => {
  const remove = service.onStatusChange((status) => {
    if (status === 'connecting') void service.disconnect();
  });
  try {
    const ready = service.connect();
    const rejection = expect(ready).rejects.toMatchObject({ name: 'AbortError' });
    await rejection;
    await flush();
    expect(Socket.instances).toHaveLength(0);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  } finally {
    remove();
  }
});

it('pins event fanout to its inbound owner across reentrant owner replacement', async () => {
  const laterOldHandler = vi.fn(),
    newHandler = vi.fn();
  service.subscribe('project:fanout:created', () => {
    admission.invalidate();
    service.subscribeProject('fanout', newHandler);
  });
  service.subscribe('project:fanout:created', laterOldHandler);
  const ready = service.connect();
  await flush();
  const socket = Socket.instances[0]!;
  socket.open();
  await ready;
  socket.message({
    type: 'conversation_created',
    routing_key: 'project:fanout:created',
    project_id: 'fanout',
  });
  expect(laterOldHandler).not.toHaveBeenCalled();
  expect(newHandler).not.toHaveBeenCalled();
});
