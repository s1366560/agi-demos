import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';
import {
  evaluateDesktopRouteAccess,
  type DesktopRouteHostState,
  type DesktopRouteRuntimeMode,
} from './desktopRouteHostModel';
import {
  restoreDesktopRoute,
  type DesktopRouteContext,
  type DesktopRouteMatch,
  type DesktopRouteRegistry,
} from './desktopRouteRegistry';

export type DesktopHashLocationPort = Readonly<{
  readHash: () => string;
  subscribe: (listener: () => void) => () => void;
}>;

export type DesktopRouteCapabilityResolver = (
  capability: string,
  context: DesktopRouteContext,
) => DesktopCapabilityAvailability | null;

export type DesktopRoutePermissionResolver = (
  context: DesktopRouteContext,
) => ReadonlySet<string>;

export type DesktopRouteScopeSwitcher = (
  context: DesktopRouteContext,
  signal: AbortSignal,
) => void | Promise<void>;

export type DesktopHashRouteHostOptions<TModule> = Readonly<{
  registry: DesktopRouteRegistry<TModule>;
  location: DesktopHashLocationPort;
  mode: DesktopRouteRuntimeMode;
  permissions: ReadonlySet<string>;
  resolvePermissions?: DesktopRoutePermissionResolver;
  resolveCapability: DesktopRouteCapabilityResolver;
  switchScope: DesktopRouteScopeSwitcher;
}>;

export type DesktopHashRouteHost<TModule> = Readonly<{
  getState: () => DesktopRouteHostState<TModule>;
  subscribe: (
    listener: (state: DesktopRouteHostState<TModule>) => void,
  ) => () => void;
  start: () => Promise<void>;
  stop: () => void;
  retry: () => Promise<void>;
}>;

type HashChangeTarget = Readonly<{
  location: Readonly<{ hash: string }>;
  addEventListener: (type: 'hashchange', listener: () => void) => void;
  removeEventListener: (type: 'hashchange', listener: () => void) => void;
}>;

export function createBrowserDesktopHashLocationPort(
  target: HashChangeTarget = window,
): DesktopHashLocationPort {
  return Object.freeze({
    readHash: () => target.location.hash,
    subscribe: (listener) => {
      target.addEventListener('hashchange', listener);
      return () => target.removeEventListener('hashchange', listener);
    },
  });
}

export function createDesktopHashRouteHost<TModule>(
  options: DesktopHashRouteHostOptions<TModule>,
): DesktopHashRouteHost<TModule> {
  let state: DesktopRouteHostState<TModule> = Object.freeze({ status: 'idle' });
  const listeners = new Set<
    (nextState: DesktopRouteHostState<TModule>) => void
  >();
  let unsubscribeLocation: (() => void) | null = null;
  let scopeController: AbortController | null = null;
  let transitionRevision = 0;
  let attempt = 0;
  let started = false;

  const emit = (nextState: DesktopRouteHostState<TModule>) => {
    state = Object.freeze(nextState);
    for (const listener of [...listeners]) listener(state);
  };

  const currentTransition = (revision: number, signal: AbortSignal) =>
    started && transitionRevision === revision && !signal.aborted;

  const emitUnavailable = (
    match: DesktopRouteMatch<TModule>,
    reasonCode: string,
    capability: DesktopCapabilityAvailability | null,
  ) => {
    emit({
      status: 'unavailable',
      match,
      reasonCode,
      capability,
    });
  };

  const resolveCurrentHash = async () => {
    const location = options.location.readHash();
    const revision = ++transitionRevision;
    scopeController?.abort();
    scopeController = null;

    const restored = restoreDesktopRoute(options.registry, location);
    if (restored.status === 'not_found') {
      if (restored.reasonCode === 'desktop_route_malformed') {
        emit({
          status: 'malformed',
          location,
          reasonCode: restored.reasonCode,
        });
      } else {
        emit({
          status: 'not_found',
          location,
          reasonCode: restored.reasonCode,
        });
      }
      return;
    }
    const { match } = restored;

    let permissions: ReadonlySet<string>;
    try {
      permissions = options.resolvePermissions
        ? options.resolvePermissions(match.context)
        : options.permissions;
      if (!permissions || typeof permissions.has !== 'function') {
        throw new Error('desktop_route_permissions_invalid');
      }
    } catch {
      emit({
        status: 'error',
        match,
        reasonCode: 'desktop_route_permission_resolution_failed',
        retryable: true,
      });
      return;
    }

    const preflight = evaluateDesktopRouteAccess({
      match,
      mode: options.mode,
      permissions,
      capability: null,
    });
    if (preflight.status === 'forbidden') {
      emit({
        status: 'forbidden',
        match,
        reasonCode: preflight.reasonCode,
        missingPermissions: preflight.missingPermissions,
      });
      return;
    }
    if (
      preflight.status === 'unavailable' &&
      preflight.reasonCode !== 'desktop_route_capability_missing'
    ) {
      emitUnavailable(match, preflight.reasonCode, preflight.capability);
      return;
    }

    let capability: DesktopCapabilityAvailability | null;
    try {
      capability = options.resolveCapability(
        match.definition.capability,
        match.context,
      );
    } catch {
      emit({
        status: 'error',
        match,
        reasonCode: 'desktop_route_capability_resolution_failed',
        retryable: true,
      });
      return;
    }
    const access = evaluateDesktopRouteAccess({
      match,
      mode: options.mode,
      permissions,
      capability,
    });
    if (access.status === 'forbidden') {
      emit({
        status: 'forbidden',
        match,
        reasonCode: access.reasonCode,
        missingPermissions: access.missingPermissions,
      });
      return;
    }
    if (access.status === 'unavailable') {
      emitUnavailable(match, access.reasonCode, access.capability);
      return;
    }

    const controller = new AbortController();
    scopeController = controller;
    attempt += 1;
    emit({
      status: 'loading',
      match,
      capability: access.capability,
      attempt,
    });

    try {
      await options.switchScope(match.context, controller.signal);
    } catch {
      if (!currentTransition(revision, controller.signal)) return;
      emit({
        status: 'error',
        match,
        reasonCode: 'desktop_route_scope_switch_failed',
        retryable: true,
      });
      return;
    }
    if (!currentTransition(revision, controller.signal)) return;

    let loadedModule: TModule;
    try {
      loadedModule = await match.definition.loader();
    } catch {
      if (!currentTransition(revision, controller.signal)) return;
      emit({
        status: 'error',
        match,
        reasonCode: 'desktop_route_module_load_failed',
        retryable: true,
      });
      return;
    }
    if (!currentTransition(revision, controller.signal)) return;
    emit({
      status: access.presentation,
      match,
      capability: access.capability,
      module: loadedModule,
    });
  };

  const onHashChange = () => {
    void resolveCurrentHash();
  };

  return Object.freeze({
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    start: async () => {
      if (!started) {
        started = true;
        unsubscribeLocation = options.location.subscribe(onHashChange);
      }
      await resolveCurrentHash();
    },
    stop: () => {
      if (!started) return;
      started = false;
      transitionRevision += 1;
      scopeController?.abort();
      scopeController = null;
      unsubscribeLocation?.();
      unsubscribeLocation = null;
    },
    retry: async () => {
      if (!started) {
        started = true;
        unsubscribeLocation = options.location.subscribe(onHashChange);
      }
      await resolveCurrentHash();
    },
  });
}
