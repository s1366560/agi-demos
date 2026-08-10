import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';
import type { DesktopRouteContext, DesktopRouteMatch } from './desktopRouteRegistry';
import type { DesktopRoutePermissionAuthorityReasonCode } from './desktopRoutePermissionAuthority';

export type DesktopRouteRuntimeMode = 'cloud' | 'local' | 'local_online' | 'local_offline';

export type DesktopRouteAccessResult =
  | Readonly<{
      status: 'allowed';
      presentation: 'ready' | 'degraded';
      capability: DesktopCapabilityAvailability;
    }>
  | Readonly<{
      status: 'forbidden';
      reasonCode: 'desktop_route_permission_denied';
      missingPermissions: readonly string[];
    }>
  | Readonly<{
      status: 'unavailable';
      reasonCode: string;
      capability: DesktopCapabilityAvailability | null;
    }>;

export type DesktopRouteHostState<TModule = unknown> =
  | Readonly<{ status: 'idle' }>
  | Readonly<{
      status: 'malformed';
      location: string;
      reasonCode: 'desktop_route_malformed';
    }>
  | Readonly<{
      status: 'not_found';
      location: string;
      reasonCode: 'desktop_route_not_found';
    }>
  | Readonly<{
      status: 'forbidden';
      match: DesktopRouteMatch<TModule>;
      reasonCode: 'desktop_route_permission_denied';
      missingPermissions: readonly string[];
    }>
  | Readonly<{
      status: 'unavailable';
      match: DesktopRouteMatch<TModule>;
      reasonCode: string;
      capability: DesktopCapabilityAvailability | null;
    }>
  | Readonly<{
      status: 'loading';
      match: DesktopRouteMatch<TModule>;
      capability: DesktopCapabilityAvailability;
      attempt: number;
    }>
  | Readonly<{
      status: 'ready' | 'degraded';
      match: DesktopRouteMatch<TModule>;
      capability: DesktopCapabilityAvailability;
      module: TModule;
    }>
  | Readonly<{
      status: 'error';
      match: DesktopRouteMatch<TModule>;
      reasonCode:
        | 'desktop_route_permission_resolution_failed'
        | DesktopRoutePermissionAuthorityReasonCode
        | 'desktop_route_capability_resolution_failed'
        | 'desktop_route_scope_switch_failed'
        | 'desktop_route_module_load_failed';
      retryable: true;
    }>;

export type DesktopRouteAccessInput<TModule = unknown> = Readonly<{
  match: DesktopRouteMatch<TModule>;
  mode: DesktopRouteRuntimeMode;
  permissions: ReadonlySet<string>;
  capability: DesktopCapabilityAvailability | null;
}>;

const ROUTE_CONTEXT_KEYS = [
  'tenantId',
  'projectId',
  'workspaceId',
  'instanceId',
] as const satisfies readonly (keyof DesktopRouteContext)[];

const CAPABILITY_SCOPE_KEYS = {
  tenantId: 'tenant_id',
  projectId: 'project_id',
  workspaceId: 'workspace_id',
  instanceId: 'instance_id',
} as const satisfies Record<
  (typeof ROUTE_CONTEXT_KEYS)[number],
  keyof DesktopCapabilityAvailability['scope']
>;

export function evaluateDesktopRouteAccess<TModule>({
  match,
  mode,
  permissions,
  capability,
}: DesktopRouteAccessInput<TModule>): DesktopRouteAccessResult {
  const runtimeState = normalizeDesktopRouteRuntimeMode(mode);
  const missingByAlternative = match.definition.requiredPermission.map((alternative) =>
    alternative.filter((permission) => !permissions.has(permission)),
  );
  const allowed = missingByAlternative.some(
    (missingPermissions) => missingPermissions.length === 0,
  );
  if (
    runtimeState === 'local_offline' &&
    match.definition.localPolicy === 'cloud_only' &&
    permissions.has('authenticated')
  ) {
    if (
      capability?.availability === 'not_applicable' &&
      capabilityScopeMatches(match.context, capability)
    ) {
      return unavailable(
        capability.reason_code ?? 'desktop_route_capability_not_applicable',
        capability,
      );
    }
    return unavailable('desktop_route_local_cloud_only', null);
  }
  if (!allowed) {
    const missingPermissions = missingByAlternative.reduce((best, candidate) =>
      candidate.length < best.length ? candidate : best,
    );
    return Object.freeze({
      status: 'forbidden',
      reasonCode: 'desktop_route_permission_denied',
      missingPermissions: Object.freeze([...missingPermissions]),
    });
  }

  if (runtimeState !== 'cloud' && match.definition.localPolicy === 'blocked_by_web_contract') {
    return unavailable('desktop_route_local_blocked_by_web_contract', null);
  }
  if (match.definition.structuralReadiness?.status === 'unavailable') {
    return unavailable(match.definition.structuralReadiness.reasonCode, null);
  }
  if (!capability) {
    return unavailable('desktop_route_capability_missing', null);
  }
  if (isActiveCapability(capability) && capability.provenance !== 'observed') {
    return unavailable('desktop_route_capability_authority_unobserved', capability);
  }
  if (
    isActiveCapability(capability) &&
    capability.authority_source !==
      authoritySourceForRoute(runtimeState, match.definition.localPolicy)
  ) {
    return unavailable('desktop_route_capability_authority_source_mismatch', capability);
  }
  if (isActiveCapability(capability) && !isActiveAuthorityRevision(capability.authority_revision)) {
    return unavailable('desktop_route_capability_authority_revision_invalid', capability);
  }
  if (isActiveCapability(capability) && capability.allowed_actions.length === 0) {
    return unavailable('desktop_route_capability_actions_missing', capability);
  }
  if (!capabilityScopeMatches(match.context, capability)) {
    return unavailable('desktop_route_capability_scope_mismatch', capability);
  }
  if (capability.availability === 'unavailable') {
    return unavailable(
      capability.reason_code ?? 'desktop_route_capability_unavailable',
      capability,
    );
  }
  if (capability.availability === 'not_applicable') {
    return unavailable(
      capability.reason_code ?? 'desktop_route_capability_not_applicable',
      capability,
    );
  }
  return Object.freeze({
    status: 'allowed',
    presentation: capability.availability === 'degraded' ? 'degraded' : 'ready',
    capability,
  });
}

function isActiveCapability(capability: DesktopCapabilityAvailability): boolean {
  return capability.availability === 'available' || capability.availability === 'degraded';
}

function normalizeDesktopRouteRuntimeMode(
  mode: DesktopRouteRuntimeMode,
): 'cloud' | 'local_online' | 'local_offline' {
  return mode === 'local' ? 'local_offline' : mode;
}

function authoritySourceForRoute(
  runtimeState: 'cloud' | 'local_online' | 'local_offline',
  localPolicy: DesktopRouteMatch['definition']['localPolicy'],
): 'cloud_service' | 'sidecar' {
  if (runtimeState === 'cloud') return 'cloud_service';
  if (runtimeState === 'local_online' && localPolicy === 'cloud_only') {
    return 'cloud_service';
  }
  return 'sidecar';
}

function isActiveAuthorityRevision(input: number | null): input is number {
  return input !== null && Number.isSafeInteger(input) && input >= 0;
}

export function desktopRouteScopeKey(context: DesktopRouteContext): string {
  return ROUTE_CONTEXT_KEYS.flatMap((key) => {
    const value = context[key];
    return value === undefined ? [] : `${key}=${encodeURIComponent(value)}`;
  }).join('&');
}

function capabilityScopeMatches(
  context: DesktopRouteContext,
  capability: DesktopCapabilityAvailability,
): boolean {
  const active = isActiveCapability(capability);
  return ROUTE_CONTEXT_KEYS.every((contextKey) => {
    const routeValue = context[contextKey];
    const capabilityValue = capability.scope[CAPABILITY_SCOPE_KEYS[contextKey]];
    return (
      routeValue === undefined ||
      (!active && capabilityValue === null) ||
      routeValue === capabilityValue
    );
  });
}

function unavailable(
  reasonCode: string,
  capability: DesktopCapabilityAvailability | null,
): DesktopRouteAccessResult {
  return Object.freeze({
    status: 'unavailable',
    reasonCode,
    capability,
  });
}
