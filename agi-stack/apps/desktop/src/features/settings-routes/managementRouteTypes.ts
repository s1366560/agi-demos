import type { ComponentType } from 'react';

import type { DesktopRuntimeConfig } from '../../types';

export type ManagementRouteCapability =
  | 'tenant-tenant-providers'
  | 'tenant-tenant-agent-definitions'
  | 'tenant-tenant-skills'
  | 'tenant-tenant-plugins'
  | 'tenant-tenant-mcp-servers';

export type ManagementRouteAuthority = DesktopRuntimeConfig['mode'];

export type ManagementRouteScope = Readonly<{
  authority: ManagementRouteAuthority;
  tenantId: string;
  projectId: string | null;
}>;

export type ManagementRouteObservation = Readonly<{
  scope: ManagementRouteScope;
  itemCount: number;
}>;

export type ManagementRouteReadOptions = Readonly<{
  signal?: AbortSignal;
}>;

export interface ManagementRouteClient {
  observe(
    scope: ManagementRouteScope,
    options?: ManagementRouteReadOptions,
  ): Promise<ManagementRouteObservation>;
}

export type ManagementRouteContent = ComponentType;

export class ManagementRouteClientError extends Error {
  readonly status: number;
  readonly reasonCode: string;

  constructor(reasonCode: string, status = 0) {
    super(reasonCode);
    this.name = 'ManagementRouteClientError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

export function managementRouteScopeForRuntime(
  config: DesktopRuntimeConfig,
  tenantId: string,
): ManagementRouteScope {
  const normalizedTenantId = exactIdentifier(tenantId);
  if (!normalizedTenantId || config.tenantId !== normalizedTenantId) {
    throw new ManagementRouteClientError(
      'management_route_runtime_scope_mismatch',
    );
  }
  const projectId = exactIdentifier(config.projectId);
  return Object.freeze({
    authority: config.mode,
    tenantId: normalizedTenantId,
    projectId,
  });
}

export function requireManagementRouteRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: ManagementRouteScope,
): ManagementRouteScope {
  if (
    !isManagementRouteScope(scope) ||
    scope.authority !== config.mode ||
    scope.tenantId !== config.tenantId ||
    (scope.projectId !== null && scope.projectId !== config.projectId)
  ) {
    throw new ManagementRouteClientError(
      'management_route_runtime_scope_mismatch',
    );
  }
  return scope;
}

export function managementRouteObservation(
  scope: ManagementRouteScope,
  itemCount: number,
): ManagementRouteObservation {
  if (!Number.isSafeInteger(itemCount) || itemCount < 0) {
    throw new ManagementRouteClientError(
      'management_route_collection_contract_invalid',
    );
  }
  return Object.freeze({ scope, itemCount });
}

export function managementRouteReasonPrefix(
  capability: ManagementRouteCapability,
): string {
  return capability.replaceAll('-', '_');
}

function isManagementRouteScope(
  value: unknown,
): value is ManagementRouteScope {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const scope = value as Record<string, unknown>;
  return (
    (scope.authority === 'cloud' || scope.authority === 'local') &&
    exactIdentifier(scope.tenantId) !== null &&
    (scope.projectId === null || exactIdentifier(scope.projectId) !== null)
  );
}

function exactIdentifier(value: unknown): string | null {
  if (typeof value !== 'string' || value.length === 0 || value !== value.trim()) {
    return null;
  }
  return value;
}
