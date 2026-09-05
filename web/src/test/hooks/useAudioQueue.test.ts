import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import { WebOperationAdmissionV2 } from '@/plugins/webOperationAdmissionV2';

import { useAudioQueue } from '@/hooks/useAudioQueue';
import type { WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
function operation() {
  const controller = new AbortController();
  const children: Promise<unknown>[] = [];
  const context = {
    signal: controller.signal,
    owner: {},
    generation: {},
    check() {
      if (controller.signal.aborted) throw new DOMException('Retired', 'AbortError');
    },
    runChild<T>(work: (child: WebOperationContextV2) => Promise<T>) {
      const task = Promise.resolve().then(() => work(context as WebOperationContextV2));
      children.push(task);
      return task;
    },
  } as WebOperationContextV2;
  return { context, controller, children };
}
function audioMock() {
  const decoded = deferred<AudioBuffer>();
  const closed = deferred<void>();
  const source = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    onended: null,
  };
  const audio = {
    state: 'running',
    currentTime: 0,
    destination: {},
    resume: vi.fn().mockResolvedValue(undefined),
    decodeAudioData: vi.fn(() => decoded.promise),
    createBufferSource: vi.fn(() => source),
    close: vi.fn(() => closed.promise),
  };
  const ctor = vi.fn(function () {
    return audio;
  });
  vi.stubGlobal('AudioContext', ctor);
  return { decoded, closed, source, audio, ctor };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('voice playback ownership', () => {
  it('stops late decode and retains child until decode and close finish', async () => {
    const mock = audioMock();
    const owner = operation();
    const { result } = renderHook(() => useAudioQueue());
    let job!: Promise<void>;
    await act(async () => {
      job = result.current.enqueueChunk(new ArrayBuffer(1), owner.context);
    });
    const observed = job.catch((error: unknown) => error);
    expect(mock.audio.decodeAudioData).toHaveBeenCalledTimes(1);
    let settled = false;
    let stopped!: Promise<void>;
    act(() => {
      stopped = result.current.stop().then(() => {
        settled = true;
      });
    });
    expect(settled).toBe(false);
    await act(async () => {
      mock.decoded.resolve({ duration: 1 } as AudioBuffer);
      await observed;
    });
    expect(mock.audio.createBufferSource).not.toHaveBeenCalled();
    expect(mock.audio.close).toHaveBeenCalledTimes(1);
    expect(settled).toBe(false);
    await act(async () => {
      mock.closed.resolve();
      await stopped;
    });
    expect(settled).toBe(true);
  });
  it('allocates nothing for a retired parent', async () => {
    const mock = audioMock();
    const owner = operation();
    owner.controller.abort();
    const { result } = renderHook(() => useAudioQueue());
    await expect(
      result.current.enqueueChunk(new ArrayBuffer(1), owner.context)
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(mock.ctor).not.toHaveBeenCalled();
  });
  it('drains stop before child setup without waiting on its own admission', async () => {
    const mock = audioMock();
    const owner = operation();
    const { result } = renderHook(() => useAudioQueue());
    const job = result.current
      .enqueueChunk(new ArrayBuffer(1), owner.context)
      .catch((error: unknown) => error);
    await act(async () => {
      await result.current.stop();
    });
    expect(await job).toMatchObject({ name: 'AbortError' });
    expect(mock.ctor).not.toHaveBeenCalled();
  });
  it('aborts playback synchronously when parent retires and reports close failure', async () => {
    const mock = audioMock();
    const owner = operation();
    const { result } = renderHook(() => useAudioQueue());
    mock.decoded.resolve({ duration: 1 } as AudioBuffer);
    await act(async () => {
      await result.current.enqueueChunk(new ArrayBuffer(1), owner.context);
    });
    expect(mock.source.start).toHaveBeenCalledTimes(1);
    act(() => {
      owner.controller.abort();
    });
    expect(mock.source.stop).toHaveBeenCalledTimes(1);
    const stopped = result.current.stop();
    const rejected = expect(stopped).rejects.toMatchObject({
      message: 'Voice playback cleanup failed',
    });
    await act(async () => {
      mock.closed.reject(new Error('close refused'));
      await rejected;
    });
    await expect(result.current.stop()).rejects.toMatchObject({
      message: 'Voice playback cleanup failed',
    });
  });
});

describe('playback asynchronous setup', () => {
  it('does not decode or play after retirement while resuming the audio device', async () => {
    const mock = audioMock();
    const owner = operation();
    const resumed = deferred<void>();
    mock.audio.state = 'suspended';
    mock.audio.resume.mockImplementation(() => resumed.promise);
    const { result } = renderHook(() => useAudioQueue());
    let chunk!: Promise<unknown>;
    await act(async () => {
      chunk = result.current
        .enqueueChunk(new ArrayBuffer(1), owner.context)
        .catch((error: unknown) => error);
    });
    act(() => {
      owner.controller.abort();
    });
    const drain = result.current.stop();
    await act(async () => {
      resumed.resolve();
      await chunk;
    });
    expect(mock.audio.decodeAudioData).not.toHaveBeenCalled();
    expect(mock.audio.close).toHaveBeenCalledTimes(1);
    await act(async () => {
      mock.closed.resolve();
      await drain;
    });
  });
  it('reports an audio constructor failure without deadlocking queued work', async () => {
    const mock = audioMock();
    mock.ctor.mockImplementation(function () {
      throw new Error('Audio unavailable');
    });
    const owner = operation();
    const { result } = renderHook(() => useAudioQueue());
    let chunk!: Promise<unknown>;
    await act(async () => {
      chunk = result.current
        .enqueueChunk(new ArrayBuffer(1), owner.context)
        .catch((error: unknown) => error);
    });
    await chunk;
    await expect(result.current.stop()).rejects.toMatchObject({
      message: 'Voice playback cleanup failed',
    });
    expect(mock.audio.close).not.toHaveBeenCalled();
  });
});

describe('playback with production generation leases', () => {
  it('holds the retired generation until a pending decode and audio close have drained', async () => {
    const mock = audioMock();
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(profile);
    const admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    const generation = runtime.getSnapshot()!;
    const started = deferred<WebOperationContextV2>();
    const finished = deferred<void>();
    const parent = admission.run(async (operation) => {
      started.resolve(operation);
      await finished.promise;
    });
    const observed = parent.catch((error: unknown) => error);
    const operation = await started.promise;
    const { result } = renderHook(() => useAudioQueue());
    let chunk!: Promise<unknown>;
    await act(async () => {
      chunk = result.current
        .enqueueChunk(new ArrayBuffer(1), operation)
        .catch((error: unknown) => error);
    });
    expect(generation.leaseCount).toBe(2);
    act(() => {
      admission.invalidate();
      finished.resolve();
    });
    let closed = false;
    const drain = admission.close().then(() => {
      closed = true;
    });
    await act(async () => {
      mock.decoded.resolve({ duration: 1 } as AudioBuffer);
      await chunk;
    });
    expect(closed).toBe(false);
    expect(generation.leaseCount).toBe(2);
    expect(mock.source.start).not.toHaveBeenCalled();
    await act(async () => {
      mock.closed.resolve();
      await drain;
    });
    expect(await observed).toMatchObject({ name: 'AbortError' });
    expect(generation.leaseCount).toBe(0);
    await runtime.close();
  });
});
