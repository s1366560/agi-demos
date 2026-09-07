import { act, cleanup, render, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VoiceWaveform } from '../../../../components/agent/chat/VoiceWaveform';
import { useVoiceSessionMediaV2 } from '../../../../components/agent/chat/useVoiceSessionMediaV2';
import type { WebVoiceSessionV2 } from '../../../../services/voiceRetainedSessionV2';
import type { WebOperationContextV2 } from '../../../../plugins/webOperationAdmissionV2';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function context() {
  const controller = new AbortController();
  const operation = {
    signal: controller.signal,
    check() {
      if (controller.signal.aborted) throw new DOMException('Retired', 'AbortError');
    },
    runChild: async (work: (child: unknown) => unknown) => work(operation),
  } as unknown as WebOperationContextV2;
  return { controller, operation };
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { enumerateDevices: vi.fn().mockResolvedValue([]), getUserMedia: vi.fn() },
  });
});
describe('voice UI borrows one admitted session', () => {
  it('waveform borrows the analyser and stops drawing on owner retirement', () => {
    const { operation, controller } = context();
    const getByteFrequencyData = vi.fn();
    const disconnect = vi.fn();
    const analyser = {
      frequencyBinCount: 8,
      getByteFrequencyData,
      disconnect,
    } as unknown as AnalyserNode;
    const callbacks: FrameRequestCallback[] = [];
    vi.stubGlobal(
      'requestAnimationFrame',
      vi.fn((cb) => {
        callbacks.push(cb);
        return callbacks.length;
      })
    );
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      roundRect: vi.fn(),
      fill: vi.fn(),
    } as never);
    render(<VoiceWaveform active analyser={analyser} operation={operation} />);
    expect(getByteFrequencyData).toHaveBeenCalledOnce();
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    controller.abort();
    callbacks[0]?.(1);
    expect(getByteFrequencyData).toHaveBeenCalledOnce();
    expect(disconnect).not.toHaveBeenCalled();
  });
  it('late camera capture is released without attaching to the video', async () => {
    const { operation } = context();
    const pending = deferred<{ stream: MediaStream; release: () => Promise<void> }>();
    const release = vi.fn().mockResolvedValue(undefined);
    const session = {
      operation,
      capture: vi.fn(() => pending.promise),
    } as unknown as WebVoiceSessionV2;
    const video = { current: document.createElement('video') };
    Object.defineProperty(video.current, 'srcObject', {
      configurable: true,
      writable: true,
      value: null,
    });
    const setDevices = vi.fn();
    const hook = renderHook(
      ({ enabled }) => useVoiceSessionMediaV2(session, enabled, video, setDevices),
      { initialProps: { enabled: true } }
    );
    hook.rerender({ enabled: false });
    await act(async () => pending.resolve({ stream: {} as MediaStream, release }));
    expect(release).toHaveBeenCalledOnce();
    expect(video.current.srcObject).toBeFalsy();
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
  });
  it('enumeration cannot publish after retirement and attached camera is cleared', async () => {
    const { operation, controller } = context();
    const enumeration = deferred<MediaDeviceInfo[]>();
    vi.mocked(navigator.mediaDevices.enumerateDevices).mockReturnValue(enumeration.promise);
    const stream = {} as MediaStream;
    const release = vi.fn().mockResolvedValue(undefined);
    const session = {
      operation,
      capture: vi.fn().mockResolvedValue({ stream, release }),
    } as unknown as WebVoiceSessionV2;
    const video = { current: document.createElement('video') };
    Object.defineProperty(video.current, 'srcObject', {
      configurable: true,
      writable: true,
      value: null,
    });
    const setDevices = vi.fn();
    renderHook(() => useVoiceSessionMediaV2(session, true, video, setDevices));
    await act(async () => {});
    expect(video.current.srcObject).toBe(stream);
    await act(async () => {
      controller.abort();
      enumeration.resolve([]);
    });
    expect(video.current.srcObject).toBeNull();
    expect(release).toHaveBeenCalledOnce();
    expect(setDevices).not.toHaveBeenCalled();
  });
  it('unmounted enumeration does not overwrite the replacement session devices', async () => {
    const { operation } = context();
    const pending = deferred<MediaDeviceInfo[]>();
    vi.mocked(navigator.mediaDevices.enumerateDevices).mockReturnValue(pending.promise);
    const setDevices = vi.fn();
    const session = { operation } as WebVoiceSessionV2;
    const hook = renderHook(() =>
      useVoiceSessionMediaV2(session, false, { current: null }, setDevices)
    );
    hook.unmount();
    await act(async () => pending.resolve([]));
    expect(setDevices).not.toHaveBeenCalled();
  });
});
