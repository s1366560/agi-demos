export const WEB_CONTROL_PLANE_DESTINATIONS = Object.freeze(
  [
    'tenant-overview',
    'agent-workspace',
    'project-overview',
    'project-memories',
    'project-graph',
    'project-settings',
  ] as const,
);

export type WebControlPlaneDestination =
  (typeof WEB_CONTROL_PLANE_DESTINATIONS)[number];

export type WebControlPlaneRequest = {
  destination: WebControlPlaneDestination;
  tenantId: string;
  projectId: string;
};

export const SIGNED_WEB_CONTROL_PLANE_ORIGIN: string | null = 'https://app.memstack.ai';

export type WebControlPlaneCapability = Readonly<{
  availability: 'available' | 'unavailable';
  contractVersion: 1;
  reasonCode:
    | 'web_control_plane_configured'
    | 'web_control_plane_origin_invalid'
    | 'web_control_plane_origin_unconfigured';
  source: 'development_override' | 'none' | 'signed_build';
}>;

export type DesktopNativeCapabilitySnapshot = Readonly<{
  contractVersion: 1;
  webControlPlane: WebControlPlaneCapability;
  workspaceCore: DesktopWorkspaceCoreCapability;
}>;

export type DesktopWorkspaceCoreCapability = Readonly<{
  state: 'starting' | 'running' | 'restartScheduled' | 'failed' | 'stopped';
  healthy: boolean;
  restartAttempts: number;
  restartGeneration: number;
  cutoverState: 'legacy-only' | 'importing' | 'core-authoritative' | 'core-unavailable';
  terminalFailureReason: string | null;
}>;

export type WebControlPlaneConfiguration = Readonly<{
  capability: WebControlPlaneCapability;
  origin: string | null;
}>;

const destinationSet = new Set<string>(WEB_CONTROL_PLANE_DESTINATIONS);

function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname.toLowerCase();
  return (
    normalized === 'localhost' ||
    normalized === '127.0.0.1' ||
    normalized === '[::1]' ||
    normalized === '::1'
  );
}

function configuredOrigin(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0 || /\s/u.test(value)) {
    throw new Error('web control-plane origin is invalid');
  }
  let origin: URL;
  try {
    origin = new URL(value);
  } catch {
    throw new Error('web control-plane origin is invalid');
  }
  if (
    origin.protocol !== 'https:' &&
    !(origin.protocol === 'http:' && isLoopbackHost(origin.hostname))
  ) {
    throw new Error('web control-plane origin must use HTTPS or loopback HTTP');
  }
  if (
    origin.username ||
    origin.password ||
    origin.pathname !== '/' ||
    origin.search ||
    origin.hash
  ) {
    throw new Error(
      'web control-plane origin must not contain credentials, paths, queries, or fragments',
    );
  }
  return origin.origin;
}

export function resolveWebControlPlaneConfiguration({
  developmentOrigin,
  isPackaged,
  signedOrigin,
}: {
  developmentOrigin?: unknown;
  isPackaged: boolean;
  signedOrigin: unknown;
}): WebControlPlaneConfiguration {
  const sourceValue =
    !isPackaged && developmentOrigin !== undefined
      ? {
          origin: developmentOrigin,
          source: 'development_override' as const,
        }
      : {
          origin: signedOrigin,
          source: 'signed_build' as const,
        };

  if (
    sourceValue.origin === null ||
    sourceValue.origin === undefined ||
    sourceValue.origin === ''
  ) {
    return Object.freeze({
      capability: Object.freeze({
        availability: 'unavailable',
        contractVersion: 1,
        reasonCode: 'web_control_plane_origin_unconfigured',
        source: 'none',
      }),
      origin: null,
    });
  }

  try {
    const origin = configuredOrigin(sourceValue.origin);
    return Object.freeze({
      capability: Object.freeze({
        availability: 'available',
        contractVersion: 1,
        reasonCode: 'web_control_plane_configured',
        source: sourceValue.source,
      }),
      origin,
    });
  } catch {
    return Object.freeze({
      capability: Object.freeze({
        availability: 'unavailable',
        contractVersion: 1,
        reasonCode: 'web_control_plane_origin_invalid',
        source: 'none',
      }),
      origin: null,
    });
  }
}

function requestRecord(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('web control-plane request is invalid');
  }
  return value as Record<string, unknown>;
}

function requestIdentifier(value: unknown, label: string): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 256 ||
    value.trim() !== value ||
    /[\u0000-\u001f\u007f]/u.test(value)
  ) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

function parseWebControlPlaneRequest(value: unknown): WebControlPlaneRequest {
  const request = requestRecord(value);
  if (
    typeof request.destination !== 'string' ||
    !destinationSet.has(request.destination)
  ) {
    throw new Error('web control-plane destination is not supported');
  }
  return {
    destination: request.destination as WebControlPlaneDestination,
    tenantId: requestIdentifier(request.tenantId, 'tenant ID'),
    projectId: requestIdentifier(request.projectId, 'project ID'),
  };
}

export function buildWebControlPlaneUrl(originValue: unknown, requestValue: unknown): string {
  const origin = configuredOrigin(originValue);
  const request = parseWebControlPlaneRequest(requestValue);
  const tenantId = encodeURIComponent(request.tenantId);
  const projectId = encodeURIComponent(request.projectId);
  let path: string;

  switch (request.destination) {
    case 'tenant-overview':
      path = `/tenant/${tenantId}/overview`;
      break;
    case 'agent-workspace':
      path = `/tenant/${tenantId}/agent-workspace`;
      break;
    case 'project-overview':
      path = `/tenant/${tenantId}/project/${projectId}`;
      break;
    case 'project-memories':
      path = `/tenant/${tenantId}/project/${projectId}/memories`;
      break;
    case 'project-graph':
      path = `/tenant/${tenantId}/project/${projectId}/graph`;
      break;
    case 'project-settings':
      path = `/tenant/${tenantId}/project/${projectId}/settings`;
      break;
  }

  const url = new URL(path, `${origin}/`);
  if (request.destination === 'tenant-overview' || request.destination === 'agent-workspace') {
    url.searchParams.set('projectId', request.projectId);
  }
  return url.toString();
}
