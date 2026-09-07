import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.hoisted(() => {
  Object.assign(globalThis, {
    WebSocket: class {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
    },
  });
});
import RFB from '@/vendor/kasmvnc/core/rfb.js';
import Display from '@/vendor/kasmvnc/core/display.js';
import TightDecoder from '@/vendor/kasmvnc/core/decoders/tight.js';
beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    fillRect: vi.fn(),
  });
});
afterEach(() => {
  delete navigator.clipboard.read;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
function create() {
  const target = document.createElement('div');
  document.body.append(target);
  const rfb = new RFB(target, document.createElement('textarea'), 'ws://localhost/kasm');
  return { rfb, target };
}
it('real RFB retires before deferred connect without creating a socket', async () => {
  const Socket = vi.fn();
  vi.stubGlobal('WebSocket', Socket);
  const { rfb, target } = create();
  const dispose = rfb.dispose();
  expect(rfb.dispose()).toBe(dispose);
  await dispose;
  await vi.advanceTimersByTimeAsync(10000);
  expect(Socket).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
  target.remove();
});
it('real Display stops the latest recurring frame after frames have already run', async () => {
  const display = new Display(document.createElement('canvas'));
  await vi.advanceTimersByTimeAsync(100);
  display.dispose();
  expect(vi.getTimerCount()).toBe(0);
  display._pushAsyncFrame();
  expect(vi.getTimerCount()).toBe(0);
});
it('RFB continues peer, worker, display cleanup after socket close throws and preserves failure', async () => {
  const { rfb, target } = create();
  const error = new Error('socket close failed');
  rfb._sock.close = () => {
    throw error;
  };
  const peerClose = vi.fn();
  const channelClose = vi.fn();
  rfb._udpPeer = { close: peerClose };
  rfb._udpChannel = { close: channelClose };
  const result = rfb.dispose();
  await expect(result).rejects.toBeInstanceOf(AggregateError);
  await expect(rfb.dispose()).rejects.toMatchObject({ errors: [error] });
  expect(peerClose).toHaveBeenCalledOnce();
  expect(channelClose).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
  target.remove();
});
it('QOI disposal terminates every real decoder worker even if one termination fails', async () => {
  const terminate = vi.fn().mockImplementationOnce(() => {
    throw new Error('worker failure');
  });
  class Worker {
    onmessage = null;
    terminate = terminate;
    postMessage() {}
  }
  vi.stubGlobal('Worker', Worker);
  const decoder = new TightDecoder({});
  decoder.enableQOI = true;
  const count = decoder._workers.length;
  const callbacks = decoder._workers.map((worker) => worker.onmessage);
  await expect(decoder.dispose()).rejects.toBeInstanceOf(AggregateError);
  expect(terminate).toHaveBeenCalledTimes(count);
  for (const callback of callbacks) callback?.({ data: { result: 0 } });
  await expect(decoder.dispose()).rejects.toBeInstanceOf(AggregateError);
  expect(terminate).toHaveBeenCalledTimes(count);
});
it('RTC offer completion after dispose is drained without setLocalDescription or socket writes', async () => {
  const { rfb, target } = create();
  let finish;
  const offer = new Promise((resolve) => {
    finish = resolve;
  });
  const peer = { createOffer: () => offer, setLocalDescription: vi.fn(), close: vi.fn() };
  rfb._udpPeer = peer;
  rfb._sendUdpUpgrade();
  let settled = false;
  const drain = rfb.dispose().then(() => {
    settled = true;
  });
  await Promise.resolve();
  expect(settled).toBe(false);
  expect(peer.close).toHaveBeenCalledOnce();
  finish({});
  await drain;
  expect(peer.setLocalDescription).not.toHaveBeenCalled();
  target.remove();
});
it('connected real vendor retires RTC and removes focus listeners without treating WS close as settled', async () => {
  class Socket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;
    binaryType = 'arraybuffer';
    bufferedAmount = 0;
    extensions = '';
    protocol = '';
    url = '';
    readyState = 0;
    onopen = null;
    onclose = null;
    onerror = null;
    onmessage = null;
    send = vi.fn();
    close = vi.fn(() => {
      this.readyState = 2;
    });
  }
  class Peer {
    static instances = [];
    channel = { close: vi.fn(), onmessage: null, onerror: null };
    close = vi.fn();
    createDataChannel = () => this.channel;
    constructor() {
      Peer.instances.push(this);
    }
  }
  vi.stubGlobal('WebSocket', Socket);
  vi.stubGlobal('RTCPeerConnection', Peer);
  const remove = vi.spyOn(window, 'removeEventListener');
  const { rfb, target } = create();
  await vi.advanceTimersByTimeAsync(1);
  expect(Peer.instances).toHaveLength(1);
  const socket = rfb._sock._websocket;
  await rfb.dispose();
  expect(socket.readyState).toBe(2); // Adapter must independently await the physical close event.
  expect(Peer.instances[0].close).toHaveBeenCalledOnce();
  expect(Peer.instances[0].channel.close).toHaveBeenCalledOnce();
  expect(remove).toHaveBeenCalledWith('blur', rfb._eventHandlers.handleFocusChange);
  expect(vi.getTimerCount()).toBe(0);
  target.remove();
});
it('partial constructor failure exposes cleanup and cancels already allocated display resources', async () => {
  const target = document.createElement('div');
  const options = {
    get showDotCursor() {
      throw new Error('options failure');
    },
  };
  let failure;
  try {
    new RFB(target, document.createElement('textarea'), 'ws://localhost/kasm', options);
  } catch (error) {
    failure = error;
  }
  expect(failure?.name).toBe('RfbInitializationError');
  await failure?.disposal;
  expect(vi.getTimerCount()).toBe(0);
});
it('legacy disconnect also clears timers and keyboard delayed modifiers', async () => {
  const { rfb, target } = create();
  // Exercise the real ungrab timer cleanup after a keyboard handler has armed AltGr.
  const send = vi.fn();
  rfb._keyboard.onkeyevent = send;
  rfb._keyboard._altGrTimeout = setTimeout(() => send('late key'), 100);
  rfb._keyboard._focusTimeout = setTimeout(() => send('late focus'), 1);
  rfb._rfbConnectionState = 'connecting';
  rfb.disconnect();
  await rfb.dispose();
  await vi.advanceTimersByTimeAsync(5000);
  expect(send).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
  target.remove();
});

it('QOI disposal waits for every pending termination before releasing buffers', async () => {
  let finish;
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  class Worker {
    postMessage() {}
    terminate() {
      return pending;
    }
  }
  vi.stubGlobal('Worker', Worker);
  const decoder = new TightDecoder({});
  decoder.enableQOI = true;
  let settled = false;
  const drain = decoder.dispose().then(() => {
    settled = true;
  });
  await Promise.resolve();
  expect(settled).toBe(false);
  finish();
  await drain;
  expect(decoder._arrs).toBeNull();
});

it('default clipboard flags do not silently enable system clipboard reads', async () => {
  const read = vi.fn();
  navigator.clipboard.read = read;
  const { rfb, target } = create();
  rfb._resendClipboardNextUserDrivenEvent = true;
  await rfb.checkLocalClipboard();
  expect(read).not.toHaveBeenCalled();
  await rfb.dispose();
  target.remove();
});

it('enabled clipboard read is drained and its late result cannot start blob reads', async () => {
  let finish;
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  const read = vi.fn(() => pending);
  navigator.clipboard.read = read;
  const { rfb, target } = create();
  rfb.clipboardUp = rfb.clipboardSeamless = rfb.clipboardBinary = true;
  rfb._rfbConnectionState = 'connected';
  rfb._resendClipboardNextUserDrivenEvent = true;
  const request = rfb.checkLocalClipboard();
  await Promise.resolve();
  expect(read).toHaveBeenCalledOnce();
  let settled = false;
  const disposal = rfb.dispose().then(() => {
    settled = true;
  });
  await Promise.resolve();
  expect(settled).toBe(false);
  const getType = vi.fn();
  finish([{ types: ['text/plain'], getType }]);
  await Promise.all([disposal, request]);
  expect(getType).not.toHaveBeenCalled();
  target.remove();
});

it.each(['getType', 'arrayBuffer'])(
  'clipboard %s resolution after retirement cannot send',
  async (stage) => {
    let finish;
    const pending = new Promise((resolve) => {
      finish = resolve;
    });
    const arrayBuffer = vi.fn(() =>
      stage === 'arrayBuffer' ? pending : Promise.resolve(new ArrayBuffer(1))
    );
    const getType = vi.fn(() => (stage === 'getType' ? pending : Promise.resolve({ arrayBuffer })));
    const { rfb, target } = create();
    rfb._rfbConnectionState = 'connected';
    const send = vi.spyOn(RFB.messages, 'sendBinaryClipboard');
    const request = rfb.clipboardPasteDataFrom([{ types: ['text/plain'], getType }]);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(getType).toHaveBeenCalledOnce();
    if (stage === 'arrayBuffer') expect(arrayBuffer).toHaveBeenCalledOnce();
    let settled = false;
    const disposal = rfb.dispose().then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    finish(stage === 'getType' ? { arrayBuffer } : new ArrayBuffer(1));
    await Promise.all([request, disposal]);
    expect(send).not.toHaveBeenCalled();
    if (stage === 'getType') expect(arrayBuffer).not.toHaveBeenCalled();
    const post = vi.spyOn(window.parent, 'postMessage');
    rfb._focusCanvas({});
    expect(post).not.toHaveBeenCalled();
    target.remove();
  }
);

it('late clipboard rejection is observed and drained as business failure, not cleanup failure', async () => {
  let rejectRead;
  const pending = new Promise((_, reject) => {
    rejectRead = reject;
  });
  const { rfb, target } = create();
  rfb._rfbConnectionState = 'connected';
  const request = rfb.clipboardPasteDataFrom([{ types: ['text/plain'], getType: () => pending }]);
  const observed = expect(request).rejects.toThrow('clipboard permission denied');
  await Promise.resolve();
  await Promise.resolve();
  const disposal = rfb.dispose();
  rejectRead(new Error('clipboard permission denied'));
  await observed;
  await expect(disposal).resolves.toBeUndefined();
  target.remove();
});
