import { runWebOperationV2, type WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';

export type WebFetchConsumerV2<T> = (
  response: Response,
  operation: WebOperationContextV2
) => T | Promise<T>;

/** Keep the network reader private even if a consumer retains a stream reader or clone. */
function ownResponseBody(response: Response): { response: Response; close(): Promise<void> } {
  if (!response.body) return { response, close: async () => undefined };
  const reader = response.body.getReader();
  const pending = new Set<Promise<unknown>>();
  let closing = false;
  let closePromise: Promise<void> | undefined;
  let streamController: ReadableStreamDefaultController<Uint8Array>;
  const close = (): Promise<void> => {
    if (closePromise) return closePromise;
    closing = true;
    closePromise = (async () => {
      try {
        await reader.cancel();
      } finally {
        await Promise.allSettled([...pending]);
        reader.releaseLock();
      }
    })();
    return closePromise;
  };
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      streamController = controller;
    },
    async pull(controller) {
      if (closing) return;
      const read = reader.read();
      pending.add(read);
      try {
        const result = await read;
        if (closing) return;
        if (result.done) controller.close();
        else controller.enqueue(result.value);
      } catch (error) {
        if (!closing) controller.error(error);
      } finally {
        pending.delete(read);
      }
    },
    cancel: close,
  });
  const bodyResponse = new Response(stream, {
    status: 200,
    statusText: response.statusText,
    headers: response.headers,
  });
  const metadata = new Set<PropertyKey>([
    'url',
    'type',
    'redirected',
    'status',
    'statusText',
    'ok',
    'headers',
  ]);
  const withMetadata = (body: Response): Response =>
    new Proxy(body, {
      get(target, key) {
        if (metadata.has(key)) return Reflect.get(response, key, response);
        // clone tees only the owned consumer stream, never the private network reader.
        if (key === 'clone') return () => withMetadata(target.clone());
        const value: unknown = Reflect.get(target, key, target);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
  const view = withMetadata(bodyResponse);
  return {
    response: view,
    close: async () => {
      // Reject retained consumer reads independently of the consumer's reader lock.
      streamController.error(new DOMException('Response consumption completed', 'AbortError'));
      await close();
    },
  };
}

/** Response bodies belong to the admitted operation until consumed or cancelled. */
export function runWebFetchV2<T>(
  input: RequestInfo | URL,
  init: RequestInit,
  consume: WebFetchConsumerV2<T>,
  options: { parent?: WebOperationContextV2 } = {}
): Promise<T> {
  return runWebOperationV2(
    async (operation) => {
      operation.check();
      const response = ownResponseBody(await fetch(input, { ...init, signal: operation.signal }));
      let result!: T;
      let failure: { error: unknown } | undefined;
      try {
        operation.check();
        result = await consume(response.response, operation);
        operation.check();
      } catch (error) {
        failure = { error };
      }
      try {
        await response.close();
      } catch (error) {
        failure ??= { error };
      }
      if (failure) throw failure.error;
      return result;
    },
    { ...(init.signal ? { signal: init.signal } : {}), ...options }
  );
}
