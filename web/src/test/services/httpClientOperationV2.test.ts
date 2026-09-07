import { beforeEach, describe, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({
  ready: true,
  events: [] as string[],
  options: undefined as unknown,
  captured: undefined as Record<string, any> | undefined,
  response: undefined as Promise<unknown> | undefined,
}));
vi.mock('@/plugins/webOperationAdmissionV2', () => ({
  runWebOperationV2: async (work: (op: any) => Promise<unknown>, options: any) => {
    if (!state.ready) throw new Error('generation_unavailable');
    state.options = options;
    state.events.push('acquire');
    let active = true;
    const op = {
      signal: options.signal,
      check: () => {
        if (!active || options.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      },
    };
    try {
      return await work(op);
    } finally {
      active = false;
      state.events.push('release');
    }
  },
}));
vi.mock('@/services/client/kernelHttpClient', () => {
  const run = async (_url: string, dataOrConfig: any, config?: any) => {
    state.events.push('transport');
    state.captured = config ?? dataOrConfig;
    return await (state.response ?? Promise.resolve({ ok: true }));
  };
  return { kernelHttpClient: { get: run, post: run, put: run, patch: run, delete: run } };
});
import { httpClient } from '@/services/client/httpClient';
function deferred() {
  let resolve!: (v: unknown) => void;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
describe('HTTP operation admission and Axios signal adaptation', () => {
  beforeEach(() => {
    state.ready = true;
    state.events = [];
    state.response = undefined;
    state.captured = undefined;
  });
  it('rejects ordinary business request before transport when generation unavailable', async () => {
    state.ready = false;
    await expect(httpClient.get('/projects/')).rejects.toThrow('generation_unavailable');
    expect(state.events).toEqual([]);
  });
  it('passes an explicit parent instead of forwarding operation metadata to Axios', async () => {
    const parent = {} as any;
    await httpClient.post('/projects/', {}, { operation: parent });
    expect((state.options as any).parent).toBe(parent);
    expect(state.captured?.operation).toBeUndefined();
    expect(state.events).toEqual(['acquire', 'transport', 'release']);
  });
  it('bridges generic signal and keeps lease until late transport settles', async () => {
    const pending = deferred();
    state.response = pending.promise;
    let abort!: () => void;
    const signal = {
      aborted: false,
      addEventListener: vi.fn((_event, listener) => {
        abort = listener;
      }),
      removeEventListener: vi.fn(),
    };
    const job = httpClient.get('/projects/', { signal });
    await Promise.resolve();
    abort();
    expect(state.captured?.signal.aborted).toBe(true);
    expect(state.events).toEqual(['acquire', 'transport']);
    pending.resolve({ old: true });
    await expect(job).rejects.toMatchObject({ name: 'AbortError' });
    expect(signal.removeEventListener).toHaveBeenCalledWith('abort', abort);
    expect(state.events.at(-1)).toBe('release');
  });
  it('suppresses upload progress after abort and after successful settlement', async () => {
    const pending = deferred();
    state.response = pending.promise;
    const onProgress = vi.fn();
    const abort = new AbortController();
    const job = httpClient.upload('/files', new FormData(), onProgress, { signal: abort.signal });
    const emit = state.captured!.onUploadProgress;
    emit({ loaded: 1, total: 2 });
    expect(onProgress).toHaveBeenCalledWith(50);
    abort.abort();
    emit({ loaded: 2, total: 2 });
    expect(onProgress).toHaveBeenCalledTimes(1);
    pending.resolve({});
    await expect(job).rejects.toMatchObject({ name: 'AbortError' });
    emit({ loaded: 2, total: 2 });
    expect(onProgress).toHaveBeenCalledTimes(1);
  });
});
