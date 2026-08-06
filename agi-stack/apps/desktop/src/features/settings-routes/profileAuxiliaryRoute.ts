import type { DesktopHashLocationPort } from '../navigation/desktopHashRouteHost';
import { PROFILE_ROUTE_ID } from './profileRoutePresentationModel';

export type ProfileAuxiliaryRouteMatch = Readonly<{
  capability: typeof PROFILE_ROUTE_ID;
  tenantId: string | null;
}>;

export function matchProfileAuxiliaryRoute(
  location: string,
): ProfileAuxiliaryRouteMatch | null {
  if (typeof location !== 'string') return null;
  const trimmed = location.trim();
  const hashIndex = trimmed.indexOf('#');
  const hashPath = hashIndex >= 0 ? trimmed.slice(hashIndex + 1) : trimmed;
  const queryIndex = hashPath.indexOf('?');
  const path = queryIndex >= 0 ? hashPath.slice(0, queryIndex) : hashPath;
  const canonical = path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path;
  if (!canonical.startsWith('/')) return null;
  const rawSegments = canonical.split('/').slice(1);
  if (rawSegments.some((segment) => segment.length === 0)) return null;
  let segments: string[];
  try {
    segments = rawSegments.map((segment) => decodeURIComponent(segment));
  } catch {
    return null;
  }
  if (segments.length === 2 && segments[0] === 'tenant' && segments[1] === 'profile') {
    return Object.freeze({ capability: PROFILE_ROUTE_ID, tenantId: null });
  }
  if (
    segments.length === 3 &&
    segments[0] === 'tenant' &&
    validTenantId(segments[1]) &&
    segments[2] === 'profile'
  ) {
    return Object.freeze({ capability: PROFILE_ROUTE_ID, tenantId: segments[1] });
  }
  return null;
}

export function createProfileFilteredHashLocationPort(
  base: DesktopHashLocationPort,
): DesktopHashLocationPort {
  return Object.freeze({
    readHash: () =>
      matchProfileAuxiliaryRoute(base.readHash()) ? '' : base.readHash(),
    subscribe: (listener) => base.subscribe(listener),
  });
}

function validTenantId(value: string): boolean {
  return value.length > 0 && value === value.trim() && !value.includes('/');
}
