import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from 'react';

import {
  createDesktopHashRouteHost,
  type DesktopHashRouteHostOptions,
} from './desktopHashRouteHost';
import {
  desktopRouteCapabilityObservationUnchanged,
  type DesktopRouteHostState,
} from './desktopRouteHostModel';

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
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const adapterRef = useRef<DesktopHashRouteHostReactAdapter<TModule> | null>(null);
  const stateRef = useRef<DesktopRouteHostState<TModule>>({ status: 'idle' });
  const retainedMode = useRef(options.mode);
  const retainedPermissions = useRef(options.permissions);
  const adapter = useMemo(() => {
    const current = stateRef.current;
    const previous = adapterRef.current;
    if (
      previous &&
      retainedMode.current === options.mode &&
      samePermissionSet(retainedPermissions.current, options.permissions) &&
      shouldRetainDesktopRouteHost(current, options)
    ) {
      return previous;
    }
    const liveOptions = new Proxy({} as DesktopHashRouteHostOptions<TModule>, {
      get(_target, property: string) {
        return optionsRef.current[property as keyof DesktopHashRouteHostOptions<TModule>];
      },
    });
    const created = createDesktopHashRouteHostReactAdapter(liveOptions);
    adapterRef.current = created;
    retainedMode.current = options.mode;
    retainedPermissions.current = options.permissions;
    return created;
  }, [options]);
  const state = useSyncExternalStore(
    adapter.subscribe,
    adapter.getSnapshot,
    adapter.getSnapshot,
  );
  stateRef.current = state;
  const retry = useCallback(() => adapter.retry(), [adapter]);

  useEffect(() => {
    void adapter.start();
    return adapter.stop;
  }, [adapter]);

  return useMemo(() => ({ state, retry }), [retry, state]);
}

function samePermissionSet(
  current: ReadonlySet<string>,
  next: ReadonlySet<string>,
): boolean {
  if (current.size !== next.size) return false;
  for (const permission of current) {
    if (!next.has(permission)) return false;
  }
  return true;
}

function shouldRetainDesktopRouteHost<TModule>(
  state: DesktopRouteHostState<TModule>,
  options: DesktopHashRouteHostOptions<TModule>,
): boolean {
  if (state.status !== 'ready' && state.status !== 'degraded' && state.status !== 'loading') {
    return false;
  }
  return desktopRouteCapabilityObservationUnchanged(
    state.capability,
    options.resolveCapability(state.match.definition.capability, state.match.context),
  );
}
