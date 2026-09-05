import { afterEach, describe, expect, it, vi } from 'vitest';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
import { runWebFetchV2 } from '@/services/client/webFetchV2';
import { apiFetch } from '@/services/client/urlUtils';
import { registerAuthStateClearer } from '@/utils/tokenResolver';

const disposals: Array<() => Promise<void>> = [];
afterEach(async () => {
  for (const dispose of disposals.splice(0)) await dispose();
  vi.unstubAllGlobals();
});
function gate() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
async function fixture() {
  const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  const admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  const uninstall = installWebOperationAdmissionV2(admission);
  disposals.push(async () => {
    uninstall();
    await admission.close();
    await runtime.close();
  });
  return { runtime, admission };
}
describe('fetch consumption owns the generation lease', () => {
  it('fails closed before fetch without installed admission', async () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    await expect(runWebFetchV2('/test', {}, (response) => response.text())).rejects.toThrow(
      'web_operation_generation_unavailable'
    );
    expect(fetch).not.toHaveBeenCalled();
  });
  it('holds the lease after headers until the consumer and unread-body cancellation settle', async () => {
    const { runtime } = await fixture();
    const consumed = gate(),
      finish = gate(),
      cancelling = gate(),
      cancelled = gate();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            new ReadableStream({
              cancel() {
                cancelling.resolve();
                return cancelled.promise;
              },
            })
          )
      )
    );
    const task = runWebFetchV2('/test', {}, async () => {
      consumed.resolve();
      await finish.promise;
      return 'done';
    });
    await consumed.promise;
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    finish.resolve();
    await cancelling.promise;
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    cancelled.resolve();
    await expect(task).resolves.toBe('done');
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('rejects a late consumer result after invalidation and still cancels the body', async () => {
    const { runtime, admission } = await fixture();
    const started = gate(),
      finish = gate();
    const cancel = vi.fn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(new ReadableStream({ cancel })))
    );
    const task = runWebFetchV2('/test', {}, async () => {
      started.resolve();
      await finish.promise;
      return 'stale';
    });
    const rejection = expect(task).rejects.toMatchObject({ name: 'AbortError' });
    await started.promise;
    admission.invalidate();
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    finish.resolve();
    await rejection;
    expect(cancel).toHaveBeenCalledOnce();
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
  it('does not replay a POST when body consumption throws TypeError with retry enabled', async () => {
    await fixture();
    const fetch = vi.fn(async () => new Response('{}'));
    vi.stubGlobal('fetch', fetch);
    await expect(
      apiFetch.post(
        '/test',
        { mutation: true },
        () => {
          throw new TypeError('consumer failed');
        },
        { retry: true }
      )
    ).rejects.toThrow('consumer failed');
    expect(fetch).toHaveBeenCalledOnce();
  });
  it('holds auth error body parsing inside admission and disposes before rejection', async () => {
    const { runtime } = await fixture();
    const finish = gate(),
      reading = gate();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 403,
        statusText: 'Forbidden',
        json: async () => {
          reading.resolve();
          await finish.promise;
          return { detail: 'forbidden' };
        },
        body: null,
      }))
    );
    const task = apiFetch.get('/test', (response) => response.json());
    const rejection = expect(task).rejects.toMatchObject({ statusCode: 403 });
    await reading.promise;
    expect(runtime.getSnapshot()!.leaseCount).toBe(2);
    finish.resolve();
    await rejection;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
  });
});

it('cancels a locked consumer reader and drains the underlying network before lease release', async () => {
  const { runtime } = await fixture();
  const cancelling = gate(),
    cancelled = gate();
  const cancel = vi.fn(() => {
    cancelling.resolve();
    return cancelled.promise;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(new ReadableStream({ cancel })))
  );
  let lateRead!: Promise<ReadableStreamReadResult<Uint8Array>>;
  const task = runWebFetchV2('/test', {}, (response) => {
    const reader = response.body!.getReader();
    lateRead = reader.read();
    void lateRead.catch(() => undefined);
    return 'finished';
  });
  await cancelling.promise;
  expect(runtime.getSnapshot()!.leaseCount).toBe(1);
  await expect(lateRead).rejects.toMatchObject({ name: 'AbortError' });
  cancelled.resolve();
  await expect(task).resolves.toBe('finished');
  expect(cancel).toHaveBeenCalledOnce();
  expect(runtime.getSnapshot()!.leaseCount).toBe(0);
});
it('propagates cancellation failures but preserves the original consumer error', async () => {
  await fixture();
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          new ReadableStream({
            cancel() {
              throw new Error('cleanup failed');
            },
          })
        )
    )
  );
  await expect(runWebFetchV2('/test', {}, () => 'result')).rejects.toThrow('cleanup failed');
  await expect(
    runWebFetchV2('/test', {}, () => {
      throw new Error('primary failed');
    })
  ).rejects.toThrow('primary failed');
});
it('preserves response metadata and readable methods on the owned body', async () => {
  await fixture();
  const original = new Response('hello', {
    status: 201,
    statusText: 'Created',
    headers: { 'x-test': 'yes' },
  });
  Object.defineProperties(original, {
    url: { value: 'https://example.test/final' },
    redirected: { value: true },
    type: { value: 'cors' },
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => original)
  );
  await expect(
    runWebFetchV2('/test', {}, async (response) => {
      expect(response.url).toBe(original.url);
      expect(response.type).toBe('cors');
      expect(response.redirected).toBe(true);
      expect(response.status).toBe(201);
      expect(response.statusText).toBe('Created');
      expect(response.headers.get('x-test')).toBe('yes');
      return response.text();
    })
  ).resolves.toBe('hello');
});
it('parses the 401 body before clearing matching auth and preserves the original HTTP error', async () => {
  const { admission } = await fixture();
  const reading = gate(),
    finish = gate();
  localStorage.setItem(
    'memstack-auth-storage',
    JSON.stringify({ state: { token: 'synthetic-old' } })
  );
  const clearer = vi.fn(() => admission.invalidate());
  const unregister = registerAuthStateClearer(clearer);
  try {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        body: null,
        json: async () => {
          reading.resolve();
          await finish.promise;
          return { detail: 'session expired' };
        },
      }))
    );
    const task = apiFetch.get('/test', (response) => response.json());
    const rejection = expect(task).rejects.toMatchObject({
      statusCode: 401,
      message: 'session expired',
    });
    await reading.promise;
    expect(clearer).not.toHaveBeenCalled();
    finish.resolve();
    await rejection;
    expect(clearer).toHaveBeenCalledOnce();
  } finally {
    unregister();
    localStorage.removeItem('memstack-auth-storage');
  }
});
it('does not clear replacement auth when an earlier token receives 401', async () => {
  await fixture();
  const reading = gate(),
    finish = gate();
  localStorage.setItem(
    'memstack-auth-storage',
    JSON.stringify({ state: { token: 'synthetic-old' } })
  );
  const clearer = vi.fn();
  const unregister = registerAuthStateClearer(clearer);
  try {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        body: null,
        json: async () => {
          reading.resolve();
          await finish.promise;
          return { detail: 'old session' };
        },
      }))
    );
    const task = apiFetch.get('/test', (response) => response.json());
    const rejection = expect(task).rejects.toMatchObject({ statusCode: 401 });
    await reading.promise;
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'synthetic-new' } })
    );
    finish.resolve();
    await rejection;
    expect(clearer).not.toHaveBeenCalled();
    expect(localStorage.getItem('memstack-auth-storage')).toContain('synthetic-new');
  } finally {
    unregister();
    localStorage.removeItem('memstack-auth-storage');
  }
});

it('preserves clone metadata while retaining responsibility for all cloned body branches', async () => {
  const { runtime } = await fixture();
  const cancelling = gate(),
    cancelled = gate();
  const cancel = vi.fn(() => {
    cancelling.resolve();
    return cancelled.promise;
  });
  const original = new Response(new ReadableStream({ cancel }), {
    status: 202,
    statusText: 'Accepted',
    headers: { 'x-clone': 'same' },
  });
  Object.defineProperties(original, {
    url: { value: 'https://example.test/clone' },
    type: { value: 'cors' },
    redirected: { value: true },
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => original)
  );
  let lateRead!: Promise<ReadableStreamReadResult<Uint8Array>>;
  const task = runWebFetchV2('/test', {}, (response) => {
    const clone = response.clone().clone();
    expect(clone.status).toBe(202);
    expect(clone.statusText).toBe('Accepted');
    expect(clone.url).toBe(original.url);
    expect(clone.type).toBe('cors');
    expect(clone.redirected).toBe(true);
    expect(clone.headers.get('x-clone')).toBe('same');
    lateRead = clone.body!.getReader().read();
    void lateRead.catch(() => undefined);
    return 'done';
  });
  await cancelling.promise;
  expect(runtime.getSnapshot()!.leaseCount).toBe(1);
  await expect(lateRead).rejects.toMatchObject({ name: 'AbortError' });
  cancelled.resolve();
  await expect(task).resolves.toBe('done');
  expect(cancel).toHaveBeenCalledOnce();
  expect(runtime.getSnapshot()!.leaseCount).toBe(0);
});
