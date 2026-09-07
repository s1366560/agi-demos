import { useCallback, useLayoutEffect, useMemo, useRef } from 'react';
import type { DesktopRuntimeConfig } from '../../types';

type Controller = { stop(): void };
type Lease<R> = { runtime: R; release(): Promise<void> };
type Session<C extends Controller> = {
  abort: AbortController;
  controller: C | null;
  releaseLease: (() => Promise<void>) | null;
  released: Promise<void>;
  settle: () => void;
  releasing: boolean;
  active: boolean;
};

/** Keeps the controller and its microphone/socket resource lease in one lifetime. */
export function useVoiceSessionLeaseV2<C extends Controller>(
  config: DesktopRuntimeConfig | null,
  connection: unknown,
  operations: unknown,
  reset: () => void,
) {
  const context = useMemo(
    () => ({ mounted: false, session: null as Session<C> | null }),
    [JSON.stringify(config), JSON.stringify(connection), operations],
  );
  const currentContext = useRef(context);
  currentContext.current = context;
  const release = useCallback((session: Session<C>) => {
    if (!session.active && session.releasing) return session.released;
    session.active = false;
    try {
      session.controller?.stop();
    } catch {
      console.warn('Voice controller cleanup failed');
    } finally {
      session.abort.abort();
    }
    if (session.releaseLease && !session.releasing) {
      session.releasing = true;
      void Promise.resolve()
        .then(session.releaseLease)
        .catch(() => {
          // Cleanup must not create an unhandled rejection or expose runtime data.
          console.warn('Voice session lease cleanup failed');
        })
        .finally(session.settle);
    }
    return session.released;
  }, []);
  useLayoutEffect(() => {
    context.mounted = true;
    reset();
    return () => {
      context.mounted = false;
      if (context.session) void release(context.session);
    };
  }, [context, release]);
  const isContextCurrent = () => context.mounted && currentContext.current === context;
  const current = () => {
    const session = context.session;
    if (!isContextCurrent() || !session?.active || session.abort.signal.aborted) return null;
    return {
      controller: session.controller,
      isActive: () =>
        isContextCurrent() &&
        context.session === session &&
        session.active &&
        !session.abort.signal.aborted,
    };
  };
  const stop = useCallback(async () => {
    if (!context.mounted || currentContext.current !== context) return;
    if (context.session) await release(context.session);
  }, [context, release]);
  async function start<R>(
    acquire: (signal: AbortSignal) => Promise<Lease<R>>,
    construct: (runtime: R, guard: { isActive(): boolean; finish(): void }) => C,
    connect: (controller: C) => Promise<boolean>,
  ): Promise<boolean> {
    if (!isContextCurrent()) return false;
    const previous = context.session;
    const previousReleased = previous ? release(previous) : Promise.resolve();
    let settle!: () => void;
    const released = new Promise<void>((resolve) => {
      settle = resolve;
    });
    const session: Session<C> = {
      abort: new AbortController(),
      controller: null,
      releaseLease: null,
      released,
      settle,
      releasing: false,
      active: true,
    };
    context.session = session;
    const isActive = () =>
      isContextCurrent() &&
      context.session === session &&
      session.active &&
      !session.abort.signal.aborted;
    try {
      await previousReleased;
      if (!isActive()) {
        settle();
        return false;
      }
      const lease = await acquire(session.abort.signal);
      session.releaseLease = () => lease.release();
      if (!isActive()) {
        await release(session);
        return false;
      }
      session.controller = construct(lease.runtime, {
        isActive,
        finish: () => {
          void release(session);
        },
      });
      const result = await connect(session.controller);
      if (!result || !isActive()) {
        await release(session);
        return false;
      }
      return true;
    } catch (error) {
      const active = isActive();
      if (session.releaseLease) await release(session);
      else {
        session.active = false;
        session.abort.abort();
        settle();
      }
      if (active && isContextCurrent() && context.session === session) throw error;
      return false;
    }
  }
  return { start, stop, current, isContextCurrent };
}
