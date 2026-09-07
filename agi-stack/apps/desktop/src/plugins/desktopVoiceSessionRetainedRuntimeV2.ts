import {
  voiceSessionErrorV2,
  type PreparedVoiceSessionV2,
  type VoiceSessionRuntimeV2,
} from './desktopVoiceSessionContractV2';

type ResourceKind =
  | 'socket'
  | 'capture'
  | 'playback'
  | 'worklet'
  | 'port'
  | 'stream'
  | 'track'
  | 'source'
  | 'buffer-source'
  | 'audio-worklet';
// The wrapper keeps the native receiver intact. Only resources created by this session can
// be passed back into context methods; wrapped objects are unwrapped at the native boundary.
export function retainVoiceSessionRuntimeV2<T extends VoiceSessionRuntimeV2>(
  candidate: T,
  input: PreparedVoiceSessionV2,
): Readonly<{ runtime: T; dispose(): Promise<void> }> {
  let active = true;
  let disposal: Promise<void> | undefined;
  const pending = new Set<Promise<unknown>>();
  const cleanups = new Set<() => unknown>();
  const cleanupErrors: unknown[] = [];
  const underlying = new WeakMap<object, object>();
  const wrappers = new WeakMap<object, object>();
  const assertActive = () => {
    input.signal.throwIfAborted();
    if (!active) throw voiceSessionErrorV2('released');
  };
  function track<R>(promise: Promise<R>): Promise<R> {
    pending.add(promise);
    void promise.then(
      () => pending.delete(promise),
      () => pending.delete(promise),
    );
    return promise;
  }
  function unwrap(value: unknown): unknown {
    return value && typeof value === 'object' ? (underlying.get(value) ?? value) : value;
  }
  function wrap<R extends object>(raw: R, kind: ResourceKind): R {
    const known = wrappers.get(raw);
    if (known) return known as R;
    const cleanupMethods =
      kind === 'socket'
        ? ['close']
        : ['capture', 'playback'].includes(kind)
          ? ['close']
          : kind === 'track'
            ? ['stop']
            : kind === 'buffer-source'
              ? ['disconnect', 'stop']
              : ['source', 'worklet'].includes(kind)
                ? ['disconnect']
                : [];
    const cleaned = new Map<string, unknown>();
    const cleanup = (name: string): unknown => {
      if (cleaned.has(name)) return cleaned.get(name);
      cleaned.set(name, undefined);
      try {
        const method: unknown = Reflect.get(raw, name);
        if (typeof method !== 'function') throw voiceSessionErrorV2('resource_invalid');
        const value: unknown = Reflect.apply(method, raw, []);
        if (value instanceof Promise) {
          const result = track(
            value.catch((error) => {
              cleanupErrors.push(error);
              throw error;
            }),
          );
          void result.catch(() => undefined);
          cleaned.set(name, result);
          return result;
        }
        cleaned.set(name, value);
        return value;
      } catch (error) {
        cleanupErrors.push(error);
        throw error;
      }
    };
    const proxy = new Proxy({} as R, {
      get(_target, key) {
        const target = raw;
        const value: unknown = Reflect.get(target, key, target);
        if (key === 'audioWorklet' && value && typeof value === 'object')
          return wrap(value, 'audio-worklet');
        if (key === 'port' && value && typeof value === 'object') return wrap(value, 'port');
        if (typeof value !== 'function') return value;
        if (typeof key === 'string' && cleanupMethods.includes(key)) return () => cleanup(key);
        return (...args: unknown[]) => {
          // Cleanup code must be able to stop tracks even after cancellation.
          if (key !== 'getTracks') assertActive();
          if (key === 'addModule' && args[0] !== candidate.workletModuleUrl)
            throw voiceSessionErrorV2('worklet_mismatch');
          const result: unknown = Reflect.apply(value, target, args.map(unwrap));
          const project = (item: unknown): unknown => {
            if (key === 'getTracks' && Array.isArray(item))
              return item.map((track) => wrap(track, 'track'));
            if (item && typeof item === 'object') {
              if (key === 'createMediaStreamSource') return wrap(item, 'source');
              if (key === 'createBufferSource') return wrap(item, 'buffer-source');
            }
            return item;
          };
          if (result instanceof Promise)
            return track(
              result.then((item) => {
                assertActive();
                return project(item);
              }),
            );
          return project(result);
        };
      },
      set(_target, key, value) {
        const target = raw;
        if (typeof key === 'string' && key.startsWith('on')) {
          if (value !== null) assertActive();
          return Reflect.set(
            target,
            key,
            typeof value === 'function'
              ? (...args: unknown[]) => {
                  if (active && !input.signal.aborted) Reflect.apply(value, proxy, args);
                }
              : value,
            target,
          );
        }
        assertActive();
        return Reflect.set(target, key, unwrap(value), target);
      },
    });
    wrappers.set(raw, proxy);
    underlying.set(proxy, raw);
    if (kind === 'stream') {
      // Register tracks immediately, before exposing a late capture to the controller.
      const getTracks: unknown = Reflect.get(raw, 'getTracks');
      if (typeof getTracks !== 'function') throw voiceSessionErrorV2('resource_invalid');
      const tracks = Reflect.apply(getTracks, raw, []) as object[];
      for (const item of tracks) wrap(item, 'track');
    }
    if (cleanupMethods.length)
      cleanups.add(() => {
        if (kind === 'socket')
          for (const key of ['onopen', 'onmessage', 'onclose', 'onerror'])
            try {
              Reflect.set(raw, key, null);
            } catch (error) {
              cleanupErrors.push(error);
            }
        if (kind === 'worklet') {
          const port = Reflect.get(raw, 'port');
          if (port) {
            try {
              Reflect.set(port, 'onmessage', null);
            } catch (error) {
              cleanupErrors.push(error);
            }
          }
        }
        for (const name of cleanupMethods) {
          try {
            cleanup(name);
          } catch {
            /* recorded above */
          }
        }
      });
    return proxy;
  }
  const runtime = new Proxy({} as T, {
    get(_target, key) {
      const target = candidate;
      const value: unknown = Reflect.get(target, key, target);
      if (typeof value !== 'function') return value;
      return (...args: unknown[]) => {
        assertActive();
        if (key === 'createSocket') {
          const connection = input.connection;
          if (
            connection.availability !== 'available' ||
            args[0] !== connection.url ||
            !Array.isArray(args[1]) ||
            args[1].length !== connection.protocols.length ||
            args[1].some((item, index) => item !== connection.protocols[index])
          )
            throw voiceSessionErrorV2('connection_mismatch');
        }
        if (
          key === 'createWorkletNode' &&
          (!args[0] || typeof args[0] !== 'object' || !underlying.has(args[0]))
        )
          throw voiceSessionErrorV2('context_mismatch');
        const result: unknown = Reflect.apply(value, target, args.map(unwrap));
        const project = (item: unknown): unknown => {
          if (item && typeof item === 'object') {
            if (key === 'createSocket') return wrap(item, 'socket');
            if (key === 'createAudioContext' || key === 'createCaptureContext')
              return wrap(item, 'capture');
            if (key === 'createPlaybackContext') return wrap(item, 'playback');
            if (key === 'createWorkletNode') return wrap(item, 'worklet');
            if (key === 'getUserMedia') return wrap(item, 'stream');
          }
          return item;
        };
        if (result instanceof Promise)
          return track(
            result.then((item) => {
              const resource = project(item);
              if (!active || input.signal.aborted) {
                // A getUserMedia prompt cannot be physically cancelled. Close its late tracks
                // before settling the pending operation, which release() is draining.
                for (const cleanup of cleanups) {
                  try {
                    cleanup();
                  } catch (error) {
                    cleanupErrors.push(error);
                  }
                }
              }
              assertActive();
              return resource;
            }),
          );
        return project(result);
      };
    },
  });
  return Object.freeze({
    runtime,
    dispose: () => {
      if (!disposal) {
        active = false;
        for (const cleanup of cleanups) {
          try {
            cleanup();
          } catch (error) {
            cleanupErrors.push(error);
          }
        }
        disposal = (async () => {
          while (pending.size) await Promise.allSettled([...pending]);
          if (cleanupErrors.length) throw cleanupErrors[0];
        })();
        void disposal.catch(() => undefined);
      }
      return disposal;
    },
  });
}
