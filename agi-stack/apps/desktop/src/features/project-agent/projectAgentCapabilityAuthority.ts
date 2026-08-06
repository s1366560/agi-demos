import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';
import type { ProjectAgentScope, ProjectAgentSnapshotBase } from './projectAgentClient';
import {
  createProjectAgentDashboardClient,
  PROJECT_AGENT_DASHBOARD_LOCAL_REASON,
  PROJECT_AGENT_DASHBOARD_ROUTE_ID,
} from './projectAgentDashboardClient';
import {
  createProjectAgentLogsClient,
  PROJECT_AGENT_LOGS_LOCAL_REASON,
  PROJECT_AGENT_LOGS_ROUTE_ID,
} from './projectAgentLogsClient';
import {
  createProjectAgentPatternsClient,
  PROJECT_AGENT_PATTERNS_LOCAL_REASON,
  PROJECT_AGENT_PATTERNS_ROUTE_ID,
} from './projectAgentPatternsClient';

export const PROJECT_AGENT_CAPABILITY_IDS = Object.freeze([
  PROJECT_AGENT_DASHBOARD_ROUTE_ID,
  PROJECT_AGENT_LOGS_ROUTE_ID,
  PROJECT_AGENT_PATTERNS_ROUTE_ID,
] as const);

export type ProjectAgentCapabilityId = (typeof PROJECT_AGENT_CAPABILITY_IDS)[number];
type CapabilityClient = Readonly<{
  load(
    scope: ProjectAgentScope,
    options?: Readonly<{ signal?: AbortSignal }>,
  ): Promise<ProjectAgentSnapshotBase>;
}>;
export type ProjectAgentCapabilityClients = Record<ProjectAgentCapabilityId, CapabilityClient>;
export type ProjectAgentCapabilityProjection = Readonly<
  Record<ProjectAgentCapabilityId, DesktopCapabilityAvailability>
>;

const SERVICE_VERSION = '0.1.0';
const CONTRACT_VERSION = '4.0.0';
const LOCAL_REASONS: Readonly<Record<ProjectAgentCapabilityId, string>> = Object.freeze({
  [PROJECT_AGENT_DASHBOARD_ROUTE_ID]: PROJECT_AGENT_DASHBOARD_LOCAL_REASON,
  [PROJECT_AGENT_LOGS_ROUTE_ID]: PROJECT_AGENT_LOGS_LOCAL_REASON,
  [PROJECT_AGENT_PATTERNS_ROUTE_ID]: PROJECT_AGENT_PATTERNS_LOCAL_REASON,
});
const REASON_PREFIXES: Readonly<Record<ProjectAgentCapabilityId, string>> = Object.freeze({
  [PROJECT_AGENT_DASHBOARD_ROUTE_ID]: 'project_agent_dashboard',
  [PROJECT_AGENT_LOGS_ROUTE_ID]: 'project_agent_logs',
  [PROJECT_AGENT_PATTERNS_ROUTE_ID]: 'project_agent_patterns',
});

export function createProjectAgentCapabilityClients(
  config: DesktopRuntimeConfig,
): ProjectAgentCapabilityClients {
  return {
    [PROJECT_AGENT_DASHBOARD_ROUTE_ID]: createProjectAgentDashboardClient(config),
    [PROJECT_AGENT_LOGS_ROUTE_ID]: createProjectAgentLogsClient(config),
    [PROJECT_AGENT_PATTERNS_ROUTE_ID]: createProjectAgentPatternsClient(config),
  };
}

export async function loadProjectAgentCapabilities(
  clients: ProjectAgentCapabilityClients,
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<ProjectAgentCapabilityProjection> {
  const scope = capabilityScope(config);
  if (!scope) return unavailableProjection(config, 'project_agent_scope_unavailable');
  if (config.mode === 'local') {
    return Object.freeze(
      Object.fromEntries(
        PROJECT_AGENT_CAPABILITY_IDS.map((capabilityId) => [
          capabilityId,
          unavailable(LOCAL_REASONS[capabilityId], scope),
        ]),
      ) as Record<ProjectAgentCapabilityId, DesktopCapabilityAvailability>,
    );
  }
  const entries = await Promise.all(
    PROJECT_AGENT_CAPABILITY_IDS.map(async (capabilityId) => {
      const capability = await loadCapability(capabilityId, clients[capabilityId], scope, signal);
      return [capabilityId, capability] as const;
    }),
  );
  return Object.freeze(
    Object.fromEntries(entries) as Record<ProjectAgentCapabilityId, DesktopCapabilityAvailability>,
  );
}

async function loadCapability(
  capabilityId: ProjectAgentCapabilityId,
  client: CapabilityClient,
  scope: ProjectAgentScope,
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
  scope: ProjectAgentScope,
): input is ProjectAgentSnapshotBase {
  if (!isRecord(input) || !isRecord(input.scope)) return false;
  if (
    input.authority !== 'cloud' ||
    input.scope.authority !== 'cloud' ||
    input.scope.tenantId !== scope.tenantId ||
    input.scope.projectId !== scope.projectId ||
    typeof input.scopeRevision !== 'number' ||
    !Number.isSafeInteger(input.scopeRevision) ||
    input.scopeRevision < 0 ||
    !validAvailabilityReason(input.availability, input.reasonCode)
  ) {
    return false;
  }
  return (
    Array.isArray(input.allowedActions) &&
    new Set(input.allowedActions).size === input.allowedActions.length &&
    input.allowedActions.every(
      (action) => typeof action === 'string' && action.length > 0 && action.trim() === action,
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
): ProjectAgentCapabilityProjection {
  const scope = fallbackScope(config);
  return Object.freeze(
    Object.fromEntries(
      PROJECT_AGENT_CAPABILITY_IDS.map((capabilityId) => [
        capabilityId,
        unavailable(reasonCode, scope),
      ]),
    ) as Record<ProjectAgentCapabilityId, DesktopCapabilityAvailability>,
  );
}

function unavailable(reasonCode: string, scope: ProjectAgentScope): DesktopCapabilityAvailability {
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

function capabilityScope(config: DesktopRuntimeConfig): ProjectAgentScope | null {
  const tenantId = identifier(config.tenantId);
  const projectId = identifier(config.projectId);
  return tenantId && projectId
    ? Object.freeze({ authority: config.mode, tenantId, projectId })
    : null;
}

function fallbackScope(config: DesktopRuntimeConfig): ProjectAgentScope {
  return Object.freeze({
    authority: config.mode,
    tenantId: identifier(config.tenantId) ?? 'unavailable',
    projectId: identifier(config.projectId) ?? 'unavailable',
  });
}

function snapshotScope(scope: ProjectAgentScope) {
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
