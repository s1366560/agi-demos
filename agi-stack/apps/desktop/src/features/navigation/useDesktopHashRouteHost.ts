import {
  useCallback,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from 'react';

import {
  createDesktopHashRouteHost,
  type DesktopHashRouteHostOptions,
} from './desktopHashRouteHost';
import type { DesktopRouteHostState } from './desktopRouteHostModel';

export type DesktopHashRouteHostReactAdapter<TModule> = Readonly<{
  getSnapshot: () => DesktopRouteHostState<TModule>;
  subscribe: (listener: () => void) => () => void;
  start: () => Promise<void>;
  stop: () => void;
  retry: () => Promise<void>;
}>;

export type DesktopHashRouteHostHookState<TModule> = Readonly<{
  state: DesktopRouteHostState<TModule>;
  retry: () => Promise<void>;
}>;

export function createDesktopHashRouteHostReactAdapter<TModule>(
  options: DesktopHashRouteHostOptions<TModule>,
): DesktopHashRouteHostReactAdapter<TModule> {
  const host = createDesktopHashRouteHost(options);
  return Object.freeze({
    getSnapshot: host.getState,
    subscribe: (listener) => host.subscribe(() => listener()),
    start: host.start,
    stop: host.stop,
    retry: host.retry,
  });
}

export function useDesktopHashRouteHost<TModule>(
  options: DesktopHashRouteHostOptions<TModule>,
): DesktopHashRouteHostHookState<TModule> {
  const adapter = useMemo(
    () => createDesktopHashRouteHostReactAdapter(options),
    [options],
  );
  const state = useSyncExternalStore(
    adapter.subscribe,
    adapter.getSnapshot,
    adapter.getSnapshot,
  );
  const retry = useCallback(() => adapter.retry(), [adapter]);

  useEffect(() => {
    void adapter.start();
    return adapter.stop;
  }, [adapter]);

  return useMemo(() => ({ state, retry }), [retry, state]);
}
