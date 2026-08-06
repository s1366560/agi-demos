import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';
import type {
  ProjectAdministrationScope,
  ProjectAdministrationSnapshotBase,
} from './projectAdministrationClient';
import {
  createProjectMaintenanceClient,
  PROJECT_MAINTENANCE_LOCAL_REASON,
  PROJECT_MAINTENANCE_ROUTE_ID,
} from './projectMaintenanceClient';
import {
  createProjectSchemaClient,
  PROJECT_SCHEMA_LOCAL_REASON,
  PROJECT_SCHEMA_ROUTE_ID,
} from './projectSchemaClient';
import {
  createProjectSettingsClient,
  PROJECT_SETTINGS_LOCAL_REASON,
  PROJECT_SETTINGS_ROUTE_ID,
} from './projectSettingsClient';

export const PROJECT_ADMINISTRATION_CAPABILITY_IDS = Object.freeze([
  PROJECT_SCHEMA_ROUTE_ID,
  PROJECT_MAINTENANCE_ROUTE_ID,
  PROJECT_SETTINGS_ROUTE_ID,
] as const);

export type ProjectAdministrationCapabilityId =
  (typeof PROJECT_ADMINISTRATION_CAPABILITY_IDS)[number];

type CapabilityClient = Readonly<{
  load(
    scope: ProjectAdministrationScope,
    options?: Readonly<{ signal?: AbortSignal }>,
  ): Promise<ProjectAdministrationSnapshotBase>;
}>;

export type ProjectAdministrationCapabilityClients = Readonly<
  Record<ProjectAdministrationCapabilityId, CapabilityClient>
>;

export type ProjectAdministrationCapabilityProjection = Readonly<
  Record<ProjectAdministrationCapabilityId, DesktopCapabilityAvailability>
>;

const SERVICE_VERSION = '0.1.0';
const CONTRACT_VERSION = '4.0.0';

const LOCAL_REASONS: Readonly<Record<ProjectAdministrationCapabilityId, string>> = Object.freeze({
  [PROJECT_SCHEMA_ROUTE_ID]: PROJECT_SCHEMA_LOCAL_REASON,
  [PROJECT_MAINTENANCE_ROUTE_ID]: PROJECT_MAINTENANCE_LOCAL_REASON,
  [PROJECT_SETTINGS_ROUTE_ID]: PROJECT_SETTINGS_LOCAL_REASON,
});

const REASON_PREFIXES: Readonly<Record<ProjectAdministrationCapabilityId, string>> = Object.freeze({
  [PROJECT_SCHEMA_ROUTE_ID]: 'project_schema',
  [PROJECT_MAINTENANCE_ROUTE_ID]: 'project_maintenance',
  [PROJECT_SETTINGS_ROUTE_ID]: 'project_settings',
});

export function createProjectAdministrationCapabilityClients(
  config: DesktopRuntimeConfig,
): ProjectAdministrationCapabilityClients {
  return Object.freeze({
    [PROJECT_SCHEMA_ROUTE_ID]: createProjectSchemaClient(config),
    [PROJECT_MAINTENANCE_ROUTE_ID]: createProjectMaintenanceClient(config),
    [PROJECT_SETTINGS_ROUTE_ID]: createProjectSettingsClient(config),
  });
}

export async function loadProjectAdministrationCapabilities(
  clients: ProjectAdministrationCapabilityClients,
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<ProjectAdministrationCapabilityProjection> {
  const scope = capabilityScope(config);
  if (!scope) {
    return unavailableProjection(config, 'project_administration_scope_unavailable');
  }
  if (config.mode === 'local') {
    return Object.freeze(
      Object.fromEntries(
        PROJECT_ADMINISTRATION_CAPABILITY_IDS.map((capabilityId) => [
          capabilityId,
          unavailable(LOCAL_REASONS[capabilityId], scope),
        ]),
      ) as Record<ProjectAdministrationCapabilityId, DesktopCapabilityAvailability>,
    );
  }

  const entries = await Promise.all(
    PROJECT_ADMINISTRATION_CAPABILITY_IDS.map(async (capabilityId) => {
      const capability = await loadCapability(capabilityId, clients[capabilityId], scope, signal);
      return [capabilityId, capability] as const;
    }),
  );
  return Object.freeze(
    Object.fromEntries(entries) as Record<
      ProjectAdministrationCapabilityId,
      DesktopCapabilityAvailability
    >,
  );
}

async function loadCapability(
  capabilityId: ProjectAdministrationCapabilityId,
  client: CapabilityClient,
  scope: ProjectAdministrationScope,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  try {
    const snapshot = await client.load(scope, { signal });
    if (!validObservation(snapshot, scope)) {
      return unavailable(`${REASON_PREFIXES[capabilityId]}_authority_contract_invalid`, scope);
    }
    return Object.freeze({
      availability: snapshot.availability,
      reason_code: snapshot.reasonCode,
      service_version: SERVICE_VERSION,
      contract_version: CONTRACT_VERSION,
      allowed_actions: Object.freeze([...snapshot.allowedActions]),
      scope: snapshotScope(scope),
      authority_revision: snapshot.scopeRevision,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    const suffix =
      error instanceof DesktopApiError && error.status === 403
        ? 'forbidden'
        : 'authority_unavailable';
    return unavailable(`${REASON_PREFIXES[capabilityId]}_${suffix}`, scope);
  }
}

function validObservation(
  input: unknown,
  scope: ProjectAdministrationScope,
): input is ProjectAdministrationSnapshotBase {
  if (!isRecord(input) || !isRecord(input.scope)) return false;
  if (
    input.authority !== 'cloud' ||
    input.scope.authority !== 'cloud' ||
    input.scope.tenantId !== scope.tenantId ||
    input.scope.projectId !== scope.projectId ||
    input.contractVersion !== CONTRACT_VERSION ||
    typeof input.scopeRevision !== 'number' ||
    !Number.isSafeInteger(input.scopeRevision) ||
    input.scopeRevision < 0 ||
    !validAvailabilityReason(input.availability, input.reasonCode)
  ) {
    return false;
  }
  const actions = input.allowedActions;
  return (
    Array.isArray(actions) &&
    new Set(actions).size === actions.length &&
    actions.every(
      (action) =>
        typeof action === 'string' &&
        action.length > 0 &&
        action.trim() === action,
    )
  );
}

function validAvailabilityReason(availability: unknown, reasonCode: unknown): boolean {
  if (availability === 'available') return reasonCode === null;
  return (
    availability === 'degraded' &&
    typeof reasonCode === 'string' &&
    reasonCode.length > 0 &&
    reasonCode.trim() === reasonCode
  );
}

function unavailableProjection(
  config: DesktopRuntimeConfig,
  reasonCode: string,
): ProjectAdministrationCapabilityProjection {
  const scope = fallbackScope(config);
  return Object.freeze(
    Object.fromEntries(
      PROJECT_ADMINISTRATION_CAPABILITY_IDS.map((capabilityId) => [
        capabilityId,
        unavailable(reasonCode, scope),
      ]),
    ) as Record<ProjectAdministrationCapabilityId, DesktopCapabilityAvailability>,
  );
}

function unavailable(
  reasonCode: string,
  scope: ProjectAdministrationScope,
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: SERVICE_VERSION,
    contract_version: CONTRACT_VERSION,
    allowed_actions: Object.freeze([]),
    scope: snapshotScope(scope),
    authority_revision: 0,
  });
}

function capabilityScope(config: DesktopRuntimeConfig): ProjectAdministrationScope | null {
  const tenantId = identifier(config.tenantId);
  const projectId = identifier(config.projectId);
  return tenantId && projectId
    ? Object.freeze({ authority: config.mode, tenantId, projectId })
    : null;
}

function fallbackScope(config: DesktopRuntimeConfig): ProjectAdministrationScope {
  return Object.freeze({
    authority: config.mode,
    tenantId: identifier(config.tenantId) ?? 'unavailable',
    projectId: identifier(config.projectId) ?? 'unavailable',
  });
}

function snapshotScope(scope: ProjectAdministrationScope) {
  return Object.freeze({
    tenant_id: scope.tenantId,
    project_id: scope.projectId,
    workspace_id: null,
    instance_id: null,
  });
}

function identifier(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value.trim() === value ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
