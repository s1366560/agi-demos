import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
import { WebVoiceSessionV2 } from '@/services/voiceRetainedSessionV2';
import { act, renderHook, cleanup } from '@testing-library/react';
import { StrictMode, createElement } from 'react';
import { useVoiceChat } from '@/hooks/useVoiceChat';
import { useVoiceTranscribe } from '@/hooks/useVoiceTranscribe';

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
class Socket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  send = vi.fn();
  failClose = false;
  closeCalls = 0;
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
  close() {
    this.closeCalls++;
    this.readyState = 2;
    if (this.failClose) throw new Error('close failed');
  }
  finish() {
    this.readyState = 3;
    this.onclose?.();
  }
}
const tick = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};
describe('voice retained operation with real Loader', () => {
  let runtime: RendererPluginRuntimeV2;
  let admission: WebOperationAdmissionV2;
  let uninstall: () => void;
  let gum: ReturnType<typeof vi.fn>;
  let audioClose: ReturnType<typeof vi.fn>;
  let addModule: ReturnType<typeof vi.fn>;
  let track: { stop: ReturnType<typeof vi.fn> };
  let stream: MediaStream;
  let contexts: number;
  beforeEach(async () => {
    runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(profile);
    admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    uninstall = installWebOperationAdmissionV2(admission);
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'voice-test-token' } })
    );
    Socket.instances = [];
    vi.stubGlobal('WebSocket', Socket);
    contexts = 0;
    track = { stop: vi.fn() };
    stream = { getTracks: () => [track] } as unknown as MediaStream;
    gum = vi.fn().mockResolvedValue(stream);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: gum } });
    audioClose = vi.fn().mockResolvedValue(undefined);
    addModule = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal(
      'AudioContext',
      class {
        state = 'running';
        sampleRate = 48000;
        audioWorklet = { addModule };
        constructor() {
          contexts++;
        }
        close = audioClose;
        createMediaStreamSource = () => ({ connect: vi.fn(), disconnect: vi.fn() });
        createAnalyser = () => ({ disconnect: vi.fn() });
      }
    );
    vi.stubGlobal(
      'AudioWorkletNode',
      class {
        port = { postMessage: vi.fn(), onmessage: null };
        disconnect = vi.fn();
      }
    );
  });
  afterEach(async () => {
    cleanup();
    admission.setEnabled(false);
    for (const socket of Socket.instances) socket.finish();
    await admission.close().catch(() => undefined);
    uninstall();
    await runtime.close();
    vi.unstubAllGlobals();
    localStorage.clear();
  });
  function session() {
    return new WebVoiceSessionV2({
      projectId: 'p1',
      conversationId: 'c1',
      speaker: 'speaker',
      changed: vi.fn(),
      message: vi.fn(),
      error: vi.fn(),
    });
  }
  async function open() {
    const value = session();
    await tick();
    Socket.instances[0]!.open();
    await value.ready;
    return value;
  }
  it('disabled admission creates zero sockets and zero media', async () => {
    admission.setEnabled(false);
    const value = session();
    await expect(value.ready).rejects.toThrow();
    await expect(value.done).rejects.toThrow();
    expect(Socket.instances).toHaveLength(0);
    expect(gum).not.toHaveBeenCalled();
    expect(contexts).toBe(0);
  });
  it('holds real generation until actual close, including CONNECTING cancellation and late open', async () => {
    const value = session();
    await tick();
    let settled = false;
    const stopped = value.stop().then(() => {
      settled = true;
    });
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    expect(settled).toBe(false);
    Socket.instances[0]!.open();
    expect(Socket.instances[0]!.send).not.toHaveBeenCalled();
    expect(Socket.instances[0]!.closeCalls).toBeGreaterThan(1);
    Socket.instances[0]!.finish();
    await stopped;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    expect(gum).not.toHaveBeenCalled();
  });
  it('drains late microphone permission and AudioContext.close after actual socket close', async () => {
    const value = await open();
    const permission = deferred<MediaStream>();
    gum.mockReturnValue(permission.promise);
    const closed = deferred<undefined>();
    audioClose.mockReturnValue(closed.promise);
    const recording = value.startRecording().catch((e) => e);
    await tick();
    expect(gum).toHaveBeenCalledOnce();
    let settled = false;
    const stopped = value.stop().then(() => {
      settled = true;
    });
    Socket.instances[0]!.finish();
    await tick();
    expect(settled).toBe(false);
    permission.resolve(stream);
    await recording;
    await tick();
    expect(track.stop).toHaveBeenCalledOnce();
    expect(audioClose).toHaveBeenCalledOnce();
    expect(settled).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBeGreaterThan(0);
    closed.resolve(undefined);
    await stopped;
    expect(value.getSnapshot().recording).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('cancel during worklet load prevents the next microphone request', async () => {
    const value = await open();
    const loaded = deferred<undefined>();
    addModule.mockReturnValue(loaded.promise);
    const recording = value.startRecording().catch((e) => e);
    await tick();
    const stopped = value.stop();
    Socket.instances[0]!.finish();
    loaded.resolve(undefined);
    await recording;
    await stopped;
    expect(gum).not.toHaveBeenCalled();
    expect(audioClose).toHaveBeenCalledOnce();
  });
  it('retains camera child until release and drains it on parent cancellation', async () => {
    const value = await open();
    const camera = await value.capture({ video: true });
    expect(camera.stream).toBe(stream);
    expect(runtime.getSnapshot()!.leaseCount).toBe(2);
    await camera.release();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    expect(track.stop).toHaveBeenCalledOnce();
    const late = deferred<MediaStream>();
    gum.mockReturnValue(late.promise);
    const pending = value.capture({ video: true }).catch((e) => e);
    await tick();
    const stopped = value.stop();
    Socket.instances[0]!.finish();
    late.resolve(stream);
    await pending;
    await stopped;
    expect(track.stop).toHaveBeenCalledTimes(2);
  });
  it('reports close failure only after actual close and repeats the same failed disconnect', async () => {
    const value = await open();
    Socket.instances[0]!.failClose = true;
    const stopped = value.stop();
    let settled = false;
    void stopped.catch(() => {
      settled = true;
    });
    await tick();
    expect(settled).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    Socket.instances[0]!.finish();
    await expect(stopped).rejects.toThrow('cleanup');
    await expect(value.stop()).rejects.toThrow('cleanup');
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('preserves a camera cleanup failure in parent disconnect even if caller catches release', async () => {
    const value = await open();
    const camera = await value.capture({ video: true });
    track.stop.mockImplementation(() => {
      throw new Error('track stop failed');
    });
    await expect(camera.release()).rejects.toThrow('cleanup');
    const stopped = value.stop();
    Socket.instances[0]!.finish();
    await expect(stopped).rejects.toThrow();
  });
  it('hook captures callbacks and aborts on scope change; old events cannot write new scope', async () => {
    const old = vi.fn(),
      next = vi.fn();
    const hook = renderHook(
      ({ conversationId, onAsrFinal }) =>
        useVoiceChat({ projectId: 'p1', conversationId, onAsrFinal }),
      { initialProps: { conversationId: 'c1', onAsrFinal: old } }
    );
    let connected!: Promise<void>;
    await act(async () => {
      connected = hook.result.current.connect();
      await tick();
    });
    await act(async () => {
      Socket.instances[0]!.open();
      await connected;
    });
    hook.rerender({ conversationId: 'c1', onAsrFinal: next });
    act(() =>
      Socket.instances[0]!.onmessage?.({
        data: JSON.stringify({ type: 'asr_final', text: 'first' }),
      })
    );
    expect(old).toHaveBeenCalledWith('first');
    expect(next).not.toHaveBeenCalled();
    const stale = Socket.instances[0]!.onmessage;
    hook.rerender({ conversationId: 'c2', onAsrFinal: next });
    expect(hook.result.current.isConnected).toBe(false);
    stale?.({ data: JSON.stringify({ type: 'asr_final', text: 'late' }) });
    expect(old).toHaveBeenCalledTimes(1);
    expect(next).not.toHaveBeenCalled();
    expect(Socket.instances).toHaveLength(1);
    Socket.instances[0]!.finish();
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('transcription unmount stops recording and retains cleanup through socket close', async () => {
    const hook = renderHook(() => useVoiceTranscribe({ projectId: 'p1', conversationId: 'c1' }));
    let started!: Promise<boolean>;
    await act(async () => {
      started = hook.result.current.toggle();
      await tick();
    });
    await act(async () => {
      Socket.instances[0]!.open();
      expect(await started).toBe(true);
    });
    expect(hook.result.current.isListening).toBe(true);
    hook.unmount();
    expect(track.stop).toHaveBeenCalledOnce();
    expect(runtime.getSnapshot()!.leaseCount).toBeGreaterThan(0);
    Socket.instances[0]!.finish();
    await tick();
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('does not mark ordinary socket network failures as resource cleanup failures', async () => {
    const value = await open();
    Socket.instances[0]!.onerror?.();
    Socket.instances[0]!.finish();
    await expect(value.done).rejects.toThrow('WebSocket connection error');
    await expect(admission.close()).resolves.toBeUndefined();
  });
  it('remembers manually caught AudioContext.close failure until parent disconnect', async () => {
    const value = await open();
    await value.startRecording();
    audioClose.mockRejectedValue(new Error('audio close failed'));
    await expect(value.stopRecording()).rejects.toThrow('cleanup');
    await expect(value.stopRecording()).rejects.toThrow('cleanup');
    const stopped = value.stop();
    Socket.instances[0]!.finish();
    await expect(stopped).rejects.toThrow('cleanup');
  });
  it('explicit stop cancels an intent waiting for old socket drain', async () => {
    const hook = renderHook(
      ({ conversationId }) => useVoiceChat({ projectId: 'p1', conversationId }),
      { initialProps: { conversationId: 'c1' } }
    );
    let first!: Promise<void>;
    await act(async () => {
      first = hook.result.current.connect();
      await tick();
    });
    await act(async () => {
      Socket.instances[0]!.open();
      await first;
    });
    hook.rerender({ conversationId: 'c2' });
    let pending!: Promise<void>;
    await act(async () => {
      pending = hook.result.current.connect();
      void pending.catch(() => undefined);
      await tick();
    });
    let stopped!: Promise<void>;
    act(() => {
      stopped = hook.result.current.disconnect();
    });
    Socket.instances[0]!.finish();
    await stopped;
    await expect(pending).rejects.toThrow();
    expect(Socket.instances).toHaveLength(1);
  });
  it('old transcription startup cannot stop a newer intent after explicit stop', async () => {
    const permission = deferred<MediaStream>();
    gum.mockReturnValueOnce(permission.promise);
    const hook = renderHook(() => useVoiceTranscribe({ projectId: 'p1', conversationId: 'c1' }));
    let first!: Promise<boolean>;
    await act(async () => {
      first = hook.result.current.toggle();
      await tick();
    });
    await act(async () => {
      Socket.instances[0]!.open();
      await tick();
    });
    let stopped!: Promise<void>;
    let second!: Promise<boolean>;
    await act(async () => {
      stopped = hook.result.current.stop();
      second = hook.result.current.toggle();
      await tick();
    });
    await act(async () => {
      Socket.instances[0]!.finish();
      permission.resolve(stream);
      expect(await first).toBe(false);
      await stopped;
      await tick();
    });
    expect(Socket.instances).toHaveLength(2);
    await act(async () => {
      Socket.instances[1]!.open();
      expect(await second).toBe(true);
    });
    expect(hook.result.current.isListening).toBe(true);
    let ending!: Promise<void>;
    act(() => {
      ending = hook.result.current.stop();
    });
    Socket.instances[1]!.finish();
    await ending;
  });
  it('StrictMode creates no automatic microphone and owner retirement does not resume recording', async () => {
    const hook = renderHook(() => useVoiceChat({ projectId: 'p1', conversationId: 'c1' }), {
      wrapper: ({ children }) => createElement(StrictMode, null, children),
    });
    expect(Socket.instances).toHaveLength(0);
    expect(gum).not.toHaveBeenCalled();
    let opened!: Promise<void>;
    await act(async () => {
      opened = hook.result.current.connect();
      await tick();
    });
    await act(async () => {
      Socket.instances[0]!.open();
      await opened;
      await hook.result.current.startRecording();
    });
    act(() => {
      admission.setEnabled(false);
      admission.setEnabled(true);
    });
    expect(hook.result.current.isRecording).toBe(false);
    expect(track.stop).toHaveBeenCalledOnce();
    Socket.instances[0]!.finish();
    await tick();
    expect(Socket.instances).toHaveLength(1);
    expect(gum).toHaveBeenCalledOnce();
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
});
