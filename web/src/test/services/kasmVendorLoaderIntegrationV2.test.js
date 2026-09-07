import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.hoisted(() => {
  globalThis.WebSocket = class {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;
  };
});
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
import { KasmRetainedSessionV2 } from '@/services/kasmRetainedSessionV2';
import RFB from '@/vendor/kasmvnc/core/rfb.js';

// Only browser device boundaries are simulated: RFB, Websock, service and Loader are real.
class RawSocket extends EventTarget {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];
  readyState = 0;
  binaryType = 'arraybuffer';
  protocol = '';
  bufferedAmount = 0;
  extensions = '';
  onopen = null;
  onmessage = null;
  onclose = null;
  onerror = null;
  sent = [];
  constructor(url, protocols) {
    super();
    this.url = url;
    this.protocols = protocols;
    RawSocket.instances.push(this);
  }
  send(bytes) {
    this.sent.push(new Uint8Array(bytes).slice());
  }
  close() {
    this.readyState = 2;
  }
  open() {
    this.readyState = 1;
    const event = new Event('open');
    this.dispatchEvent(event);
  }
  receive(bytes) {
    this.onmessage?.({ data: bytes.buffer });
  }
  finish() {
    this.readyState = 3;
    const event = new Event('close');
    this.dispatchEvent(event);
  }
}
class Peer {
  static instances = [];
  channel = { binaryType: '', onmessage: null, onerror: null, close: vi.fn() };
  close = vi.fn();
  createDataChannel = vi.fn(() => this.channel);
  constructor() {
    Peer.instances.push(this);
  }
}
const tick = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
};
let runtime, admission, detach, target;
beforeEach(async () => {
  runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  detach = installWebOperationAdmissionV2(admission);
  localStorage.setItem(
    'memstack-auth-storage',
    JSON.stringify({ state: { token: 'kasm-integration-fixture' } })
  );
  vi.useFakeTimers();
  RawSocket.instances = [];
  Peer.instances = [];
  vi.stubGlobal('WebSocket', RawSocket);
  vi.stubGlobal('RTCPeerConnection', Peer);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    fillRect: vi.fn(),
  });
  target = document.createElement('div');
  document.body.append(target);
});
afterEach(async () => {
  try {
    admission.setEnabled(false);
    for (const socket of RawSocket.instances) socket.finish();
    await admission.close();
  } finally {
    detach();
    await runtime.close();
    target.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    localStorage.clear();
  }
});
it('real vendor negotiates on the admitted raw socket and retires before lease release at actual close', async () => {
  const receivedSockets = [];
  const session = new KasmRetainedSessionV2({
    projectId: 'project-a',
    sandboxId: 'sandbox-a',
    wsUrl: 'ws://localhost/kasm',
    onStateChange: vi.fn(),
    createAttempt(socket, operation, attempt) {
      operation.check();
      receivedSockets.push(socket);
      const rfb = new RFB(target, document.createElement('textarea'), socket);
      rfb.addEventListener('connect', () => attempt.connected());
      rfb.addEventListener('disconnect', () => {
        if (!attempt.signal.aborted) attempt.disconnected();
      });
      return { dispose: () => rfb.dispose() };
    },
  });
  const connecting = session.connect();
  const cancelled = expect(connecting).rejects.toMatchObject({ name: 'AbortError' });
  await tick();
  expect(runtime.getSnapshot().leaseCount).toBe(1);
  expect(RawSocket.instances).toHaveLength(1);
  const socket = RawSocket.instances[0];
  expect(receivedSockets).toEqual([socket]);
  await vi.advanceTimersByTimeAsync(1); // Real RFB deferred connect attaches Websock to raw channel.
  expect(RawSocket.instances).toHaveLength(1);
  expect(Peer.instances).toHaveLength(1);
  expect(Peer.instances[0].createDataChannel).toHaveBeenCalledOnce();
  socket.open();
  socket.receive(new TextEncoder().encode('RFB 003.008\n'));
  expect(socket.sent).toHaveLength(1);
  expect(new TextDecoder().decode(socket.sent[0])).toBe('RFB 003.008\n');
  expect(runtime.getSnapshot().leaseCount).toBe(1);
  admission.setEnabled(false);
  await cancelled;
  let settled = false;
  const stopping = session.disconnect().then(() => {
    settled = true;
  });
  await tick();
  expect(Peer.instances[0].close).toHaveBeenCalledOnce();
  expect(Peer.instances[0].channel.close).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
  expect(socket.readyState).toBe(RawSocket.CLOSING);
  expect(settled).toBe(false);
  expect(runtime.getSnapshot().leaseCount).toBe(1);
  socket.receive(new TextEncoder().encode('RFB 003.008\n'));
  expect(socket.sent).toHaveLength(1);
  socket.finish();
  await stopping;
  expect(runtime.getSnapshot().leaseCount).toBe(0);
  await vi.advanceTimersByTimeAsync(60000);
  expect(RawSocket.instances).toHaveLength(1);
  expect(vi.getTimerCount()).toBe(0);
});
