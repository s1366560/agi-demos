import { type ReactNode, useMemo } from 'react';
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
  Omit<DesktopHashRouteHostOptions<DesktopRouteModule>, 'location'> & {
    authenticationPassthroughRouteIds?: ReadonlySet<string>;
    children: ReactNode;
    forceLegacyChildren?: boolean;
    legacyPassthroughRouteIds?: ReadonlySet<string>;
    location: DesktopHashLocationPort;
    navigation: DesktopProductionRouterNavigationPort;
  }
>;

export type DesktopProductionRouterViewProps = Readonly<{
  authenticationPassthroughRouteIds?: ReadonlySet<string>;
  children: ReactNode;
  currentLocation?: string;
  forceLegacyChildren?: boolean;
  legacyPassthroughRouteIds?: ReadonlySet<string>;
  navigation: DesktopProductionRouterNavigationPort;
  retry: () => Promise<void>;
  state: DesktopRouteHostState<DesktopRouteModule>;
}>;

export function DesktopProductionRouter({
  authenticationPassthroughRouteIds,
  children,
  forceLegacyChildren,
  legacyPassthroughRouteIds,
  location,
  mode,
  navigation,
  permissions,
  registry,
  resolvePermissions,
  resolvePermissionSnapshot,
  resolveCapability,
  switchScope,
}: DesktopProductionRouterProps) {
  const hostOptions = useMemo<DesktopHashRouteHostOptions<DesktopRouteModule>>(
    () => ({
      location,
      mode,
      permissions,
      registry,
      resolvePermissions,
      resolvePermissionSnapshot,
      resolveCapability,
      switchScope,
    }),
    [
      location,
      mode,
      permissions,
      registry,
      resolvePermissions,
      resolvePermissionSnapshot,
      resolveCapability,
      switchScope,
    ],
  );
  const { state, retry } = useDesktopHashRouteHost(hostOptions);
  return (
    <DesktopProductionRouterView
      authenticationPassthroughRouteIds={authenticationPassthroughRouteIds}
      currentLocation={location.readHash()}
      forceLegacyChildren={forceLegacyChildren}
      legacyPassthroughRouteIds={legacyPassthroughRouteIds}
      navigation={navigation}
      retry={retry}
      state={state}
    >
      {children}
    </DesktopProductionRouterView>
  );
}

export function DesktopProductionRouterView({
  authenticationPassthroughRouteIds,
  children,
  currentLocation = '',
  forceLegacyChildren = false,
  legacyPassthroughRouteIds,
  navigation,
  retry,
  state,
}: DesktopProductionRouterViewProps) {
  const { t } = useI18n();
  const routeActive = productionRouteOwnsState(
    state,
    currentLocation,
    authenticationPassthroughRouteIds,
    forceLegacyChildren,
    legacyPassthroughRouteIds,
  );
  const routeId =
    'match' in state
      ? state.match.definition.id
      : t('desktopProductionRouter.nativeRoute');
  const routeContentOwned = Boolean(
    routeActive &&
    isLoadedRouteState(state) &&
    state.module.contentPolicy === 'route_content',
  );

  return (
    <>
      <section
        className="desktop-production-router-legacy"
        data-route-active={routeActive}
        hidden={routeActive}
        inert={routeActive ? true : undefined}
      >
        {routeContentOwned ? null : children}
      </section>
      {routeActive ? (
        <section
          className="desktop-production-route-stage"
          data-route-state={state.status}
          data-route-id={
            'match' in state ? state.match.definition.id : undefined
          }
          onKeyDown={(event) => {
            handleDesktopProductionRouteBoundaryEscape(
              state.status,
              navigation,
              event,
            );
          }}
        >
          <nav
            className="desktop-production-route-breadcrumb"
            aria-label={t('desktopProductionRouter.breadcrumb')}
          >
            <button
              type="button"
              data-action="return-workbench"
              autoFocus={
                state.status === 'malformed' || state.status === 'not_found'
              }
              onClick={() => returnToDesktopWorkbench(navigation)}
            >
              {t('desktopProductionRouter.returnWorkbench')}
            </button>
            <ChevronRightIcon aria-hidden="true" />
            <code>{routeId}</code>
          </nav>
          {renderActiveRoute(
            state,
            retry,
            routeContentOwned ? children : undefined,
          )}
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
  content?: ReactNode,
) {
  if (isLoadedRouteState(state)) return renderRouteSurface(state, content);
  return renderBoundary(state, retry);
}

function isLoadedRouteState(
  state: DesktopRouteHostState<DesktopRouteModule>,
): state is LoadedDesktopRouteState {
  return state.status === 'ready' || state.status === 'degraded';
}

function renderRouteSurface(
  state: LoadedDesktopRouteState,
  content?: ReactNode,
) {
  const Surface = state.module.Surface;
  return (
    <div className="desktop-production-route-surface">
      <Surface
        module={state.module}
        context={state.match.context}
        {...(content === undefined ? {} : { content })}
      />
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
      data-reason-code={presentation.reasonCode ?? undefined}
      role={alert ? 'alert' : 'status'}
      aria-busy={
        state.status === 'idle' || state.status === 'loading' ? true : undefined
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
        <p className="desktop-production-route-reason">
          {t(boundaryReasonMessageKey(presentation.reasonCode))}
        </p>
      ) : null}
      {state.status === 'forbidden' ? (
        <dl className="desktop-production-route-details">
          <div>
            <dt>{t('desktopProductionRouter.missingPermissions')}</dt>
            <dd>
              <code>{state.missingPermissions.join(', ')}</code>
            </dd>
          </div>
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

export function boundaryReasonMessageKey(reasonCode: string): string {
  switch (reasonCode) {
    case 'desktop_route_local_cloud_only':
      return 'desktopProductionRouter.reason.cloudRequired';
    case 'desktop_route_local_blocked_by_web_contract':
      return 'desktopProductionRouter.reason.webContractBlocked';
    case 'desktop_route_permission_denied':
      return 'desktopProductionRouter.reason.permissionDenied';
    case 'desktop_route_malformed':
      return 'desktopProductionRouter.reason.routeMalformed';
    case 'desktop_route_not_found':
      return 'desktopProductionRouter.reason.routeNotFound';
    case 'desktop_route_context_invalid':
    case 'desktop_route_context_missing':
      return 'desktopProductionRouter.reason.contextUnavailable';
    case 'desktop_route_capability_missing':
      return 'desktopProductionRouter.reason.capabilityMissing';
    case 'desktop_route_capability_scope_mismatch':
      return 'desktopProductionRouter.reason.scopeMismatch';
    case 'desktop_route_capability_actions_missing':
    case 'desktop_route_capability_authority_revision_invalid':
    case 'desktop_route_capability_authority_source_mismatch':
    case 'desktop_route_capability_authority_unobserved':
      return 'desktopProductionRouter.reason.authorityUnavailable';
    case 'desktop_route_permission_resolution_failed':
      return 'desktopProductionRouter.reason.permissionResolutionFailed';
    case 'desktop_route_capability_resolution_failed':
      return 'desktopProductionRouter.reason.capabilityResolutionFailed';
    case 'desktop_route_scope_switch_failed':
      return 'desktopProductionRouter.reason.scopeSwitchFailed';
    case 'desktop_route_module_load_failed':
      return 'desktopProductionRouter.reason.moduleLoadFailed';
    case 'desktop_route_structural_app_binding_missing':
    case 'desktop_route_structural_loader_missing':
      return 'desktopProductionRouter.reason.installationIncomplete';
    default:
      return 'desktopProductionRouter.reason.authorityUnavailable';
  }
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

export function handleDesktopProductionRouteBoundaryEscape(
  status: DesktopRouteHostState['status'],
  navigation: DesktopProductionRouterNavigationPort,
  event: Readonly<{ key: string; preventDefault: () => void }>,
): boolean {
  if (
    event.key !== 'Escape' ||
    (status !== 'malformed' && status !== 'not_found')
  ) {
    return false;
  }
  event.preventDefault();
  returnToDesktopWorkbench(navigation);
  return true;
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
  authenticationPassthroughRouteIds?: ReadonlySet<string>,
  forceLegacyChildren = false,
  legacyPassthroughRouteIds?: ReadonlySet<string>,
): boolean {
  if (forceLegacyChildren) return false;
  if (state.status === 'idle') {
    return hasNonEmptyHash(currentLocation);
  }
  if (state.status === 'malformed' || state.status === 'not_found') {
    return hasNonEmptyHash(state.location);
  }
  if (
    shouldPassThroughAuthenticationBoundary(
      state,
      authenticationPassthroughRouteIds,
    )
  ) {
    return false;
  }
  if (
    (state.status === 'ready' || state.status === 'degraded') &&
    legacyPassthroughRouteIds?.has(state.match.definition.id)
  ) {
    return false;
  }
  return true;
}

export function shouldPassThroughAuthenticationBoundary(
  state: DesktopRouteHostState<DesktopRouteModule>,
  authenticationPassthroughRouteIds?: ReadonlySet<string>,
): boolean {
  return Boolean(
    state.status === 'forbidden' &&
    authenticationPassthroughRouteIds?.has(state.match.definition.id) &&
    state.missingPermissions.includes('authenticated'),
  );
}

function hasNonEmptyHash(location: string): boolean {
  const trimmed = location.trim();
  if (!trimmed) return false;
  const hashIndex = trimmed.indexOf('#');
  const value = hashIndex >= 0 ? trimmed.slice(hashIndex + 1) : trimmed;
  return value.trim().length > 0;
}
