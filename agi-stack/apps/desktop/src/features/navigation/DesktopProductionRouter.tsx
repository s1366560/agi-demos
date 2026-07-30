import {
  type ReactNode,
  useMemo,
} from 'react';
import {
  ChevronRightIcon,
  ExclamationTriangleIcon,
  LockClosedIcon,
  MagnifyingGlassIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  DesktopHashLocationPort,
  DesktopHashRouteHostOptions,
} from './desktopHashRouteHost';
import type { DesktopRouteHostState } from './desktopRouteHostModel';
import type { DesktopRouteModule } from './desktopRouteModule';
import type { DesktopRouteRegistry } from './desktopRouteRegistry';
import { useDesktopHashRouteHost } from './useDesktopHashRouteHost';
import './DesktopProductionRouter.css';

export type DesktopProductionRouterNavigationPort = Readonly<{
  clearHash: () => void;
}>;

export type DesktopProductionRouterProps = Readonly<
  Omit<
    DesktopHashRouteHostOptions<DesktopRouteModule>,
    'location'
  > & {
    children: ReactNode;
    location: DesktopHashLocationPort;
    navigation: DesktopProductionRouterNavigationPort;
  }
>;

export type DesktopProductionRouterViewProps = Readonly<{
  children: ReactNode;
  currentLocation?: string;
  navigation: DesktopProductionRouterNavigationPort;
  registry: DesktopRouteRegistry<DesktopRouteModule>;
  retry: () => Promise<void>;
  state: DesktopRouteHostState<DesktopRouteModule>;
}>;

export function DesktopProductionRouter({
  children,
  location,
  mode,
  navigation,
  permissions,
  registry,
  resolvePermissions,
  resolveCapability,
  switchScope,
}: DesktopProductionRouterProps) {
  const hostOptions = useMemo<
    DesktopHashRouteHostOptions<DesktopRouteModule>
  >(
    () => ({
      location,
      mode,
      permissions,
      registry,
      resolvePermissions,
      resolveCapability,
      switchScope,
    }),
    [
      location,
      mode,
      permissions,
      registry,
      resolvePermissions,
      resolveCapability,
      switchScope,
    ],
  );
  const { state, retry } = useDesktopHashRouteHost(hostOptions);
  return (
    <DesktopProductionRouterView
      currentLocation={location.readHash()}
      navigation={navigation}
      registry={registry}
      retry={retry}
      state={state}
    >
      {children}
    </DesktopProductionRouterView>
  );
}

export function DesktopProductionRouterView({
  children,
  currentLocation = '',
  navigation,
  registry,
  retry,
  state,
}: DesktopProductionRouterViewProps) {
  const { t } = useI18n();
  const routeActive = productionRouteOwnsState(
    state,
    currentLocation,
    registry,
  );
  const routeId =
    'match' in state
      ? state.match.definition.id
      : t('desktopProductionRouter.nativeRoute');

  return (
    <>
      <section
        className="desktop-production-router-legacy"
        data-route-active={routeActive}
        hidden={routeActive}
        inert={routeActive ? true : undefined}
      >
        {children}
      </section>
      {routeActive ? (
        <section
          className="desktop-production-route-stage"
          data-route-state={state.status}
          data-route-id={'match' in state ? state.match.definition.id : undefined}
        >
          <nav
            className="desktop-production-route-breadcrumb"
            aria-label={t('desktopProductionRouter.breadcrumb')}
          >
            <button
              type="button"
              data-action="return-workbench"
              onClick={() => returnToDesktopWorkbench(navigation)}
            >
              {t('desktopProductionRouter.returnWorkbench')}
            </button>
            <ChevronRightIcon aria-hidden="true" />
            <code>{routeId}</code>
          </nav>
          {renderActiveRoute(state, retry)}
        </section>
      ) : null}
    </>
  );
}

type LoadedDesktopRouteState = Extract<
  DesktopRouteHostState<DesktopRouteModule>,
  Readonly<{ status: 'ready' | 'degraded' }>
>;

type BoundaryDesktopRouteState = Exclude<
  DesktopRouteHostState<DesktopRouteModule>,
  LoadedDesktopRouteState
>;

function renderActiveRoute(
  state: DesktopRouteHostState<DesktopRouteModule>,
  retry: () => Promise<void>,
) {
  if (isLoadedRouteState(state)) return renderRouteSurface(state);
  return renderBoundary(state, retry);
}

function isLoadedRouteState(
  state: DesktopRouteHostState<DesktopRouteModule>,
): state is LoadedDesktopRouteState {
  return state.status === 'ready' || state.status === 'degraded';
}

function renderRouteSurface(
  state: LoadedDesktopRouteState,
) {
  const Surface = state.module.Surface;
  return (
    <div className="desktop-production-route-surface">
      <Surface module={state.module} context={state.match.context} />
    </div>
  );
}

function renderBoundary(
  state: BoundaryDesktopRouteState,
  retry: () => Promise<void>,
) {
  const boundary = boundaryPresentation(state);
  return (
    <RouteBoundary
      key={`${state.status}:${boundary.reasonCode ?? 'pending'}`}
      state={state}
      presentation={boundary}
      retry={retry}
    />
  );
}

type RouteBoundaryPresentation = Readonly<{
  descriptionKey: string;
  reasonCode: string | null;
  retryVisible: boolean;
  titleKey: string;
}>;

function RouteBoundary({
  presentation,
  retry,
  state,
}: Readonly<{
  presentation: RouteBoundaryPresentation;
  retry: () => Promise<void>;
  state: BoundaryDesktopRouteState;
}>) {
  const { t } = useI18n();
  const alert =
    state.status === 'error' ||
    state.status === 'forbidden' ||
    state.status === 'malformed';
  const Icon = boundaryIcon(state.status);
  return (
    <div
      className="desktop-production-route-boundary"
      role={alert ? 'alert' : 'status'}
      aria-busy={
        state.status === 'idle' || state.status === 'loading'
          ? true
          : undefined
      }
    >
      <span
        className="desktop-production-route-boundary-icon"
        data-boundary-state={state.status}
      >
        <Icon aria-hidden="true" />
      </span>
      <span className="desktop-production-route-eyebrow">
        {t('desktopProductionRouter.eyebrow')}
      </span>
      <h1>{t(presentation.titleKey)}</h1>
      <p>{t(presentation.descriptionKey)}</p>
      {'match' in state ? (
        <code className="desktop-production-route-identity">
          {state.match.definition.id}
        </code>
      ) : null}
      {presentation.reasonCode ? (
        <dl className="desktop-production-route-details">
          <div>
            <dt>{t('desktopProductionRouter.reasonCode')}</dt>
            <dd>
              <code>{presentation.reasonCode}</code>
            </dd>
          </div>
          {state.status === 'forbidden' ? (
            <div>
              <dt>{t('desktopProductionRouter.missingPermissions')}</dt>
              <dd>
                <code>{state.missingPermissions.join(', ')}</code>
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {presentation.retryVisible ? (
        <button
          className="desktop-production-route-retry"
          type="button"
          data-action="retry-route"
          onClick={() => void retryDesktopProductionRoute(retry)}
        >
          <ReloadIcon aria-hidden="true" />
          {t('common.retry')}
        </button>
      ) : null}
    </div>
  );
}

function boundaryPresentation(
  state: BoundaryDesktopRouteState,
): RouteBoundaryPresentation {
  switch (state.status) {
    case 'idle':
    case 'loading':
      return {
        titleKey: 'desktopProductionRouter.loading.title',
        descriptionKey: 'desktopProductionRouter.loading.description',
        reasonCode: null,
        retryVisible: false,
      };
    case 'forbidden':
      return {
        titleKey: 'desktopProductionRouter.forbidden.title',
        descriptionKey: 'desktopProductionRouter.forbidden.description',
        reasonCode: state.reasonCode,
        retryVisible: false,
      };
    case 'unavailable':
      return {
        titleKey: 'desktopProductionRouter.unavailable.title',
        descriptionKey: 'desktopProductionRouter.unavailable.description',
        reasonCode: state.reasonCode,
        retryVisible: true,
      };
    case 'error':
      return {
        titleKey: 'desktopProductionRouter.error.title',
        descriptionKey: 'desktopProductionRouter.error.description',
        reasonCode: state.reasonCode,
        retryVisible: state.retryable,
      };
    case 'malformed':
      return {
        titleKey: 'desktopProductionRouter.malformed.title',
        descriptionKey: 'desktopProductionRouter.malformed.description',
        reasonCode: state.reasonCode,
        retryVisible: false,
      };
    case 'not_found':
      return {
        titleKey: 'desktopProductionRouter.notFound.title',
        descriptionKey: 'desktopProductionRouter.notFound.description',
        reasonCode: state.reasonCode,
        retryVisible: false,
      };
  }
}

export function returnToDesktopWorkbench(
  navigation: DesktopProductionRouterNavigationPort,
): void {
  navigation.clearHash();
}

export function retryDesktopProductionRoute(
  retry: () => Promise<void>,
): Promise<void> {
  return retry();
}

function boundaryIcon(status: DesktopRouteHostState['status']) {
  if (status === 'forbidden') return LockClosedIcon;
  if (status === 'not_found') return MagnifyingGlassIcon;
  return ExclamationTriangleIcon;
}

function productionRouteOwnsState(
  state: DesktopRouteHostState<DesktopRouteModule>,
  currentLocation: string,
  registry: DesktopRouteRegistry<DesktopRouteModule>,
): boolean {
  if (state.status === 'idle') {
    return matchesCanonicalNamespace(currentLocation, registry);
  }
  if (state.status === 'malformed' || state.status === 'not_found') {
    return matchesCanonicalNamespace(state.location, registry);
  }
  return true;
}

function matchesCanonicalNamespace(
  location: string,
  registry: DesktopRouteRegistry<DesktopRouteModule>,
): boolean {
  const path = hashPath(location);
  if (!path) return false;
  return canonicalNamespaces(registry).some(
    (namespace) =>
      path === namespace || path.startsWith(`${namespace}/`),
  );
}

function canonicalNamespaces(
  registry: DesktopRouteRegistry<DesktopRouteModule>,
): readonly string[] {
  return [
    ...new Set(
      registry.definitions.flatMap((definition) => {
        const firstSegment = definition.path
          .split('/')
          .find((segment) => segment.length > 0);
        if (!firstSegment || firstSegment.startsWith(':')) return [];
        return `/${firstSegment}`;
      }),
    ),
  ];
}

function hashPath(location: string): string {
  const trimmed = location.trim();
  if (!trimmed) return '';
  const hashIndex = trimmed.indexOf('#');
  const value = hashIndex >= 0 ? trimmed.slice(hashIndex + 1) : trimmed;
  const queryIndex = value.indexOf('?');
  return queryIndex >= 0 ? value.slice(0, queryIndex) : value;
}
