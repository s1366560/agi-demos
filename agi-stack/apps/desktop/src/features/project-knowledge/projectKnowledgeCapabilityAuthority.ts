import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';
import {
  createProjectCommunitiesClient,
  PROJECT_COMMUNITIES_LOCAL_REASON,
  PROJECT_COMMUNITIES_ROUTE_ID,
} from './projectCommunitiesClient';
import {
  createProjectEntitiesClient,
  PROJECT_ENTITIES_LOCAL_REASON,
  PROJECT_ENTITIES_ROUTE_ID,
} from './projectEntitiesClient';
import {
  createProjectGraphClient,
  PROJECT_GRAPH_LOCAL_REASON,
  PROJECT_GRAPH_ROUTE_ID,
} from './projectGraphClient';
import type {
  ProjectKnowledgeClient,
  ProjectKnowledgeScope,
  ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';
import {
  createProjectMemoriesClient,
  PROJECT_MEMORIES_LOCAL_REASON,
  PROJECT_MEMORIES_ROUTE_ID,
} from './projectMemoriesClient';
import {
  createProjectTeamClient,
  PROJECT_TEAM_LOCAL_REASON,
  PROJECT_TEAM_ROUTE_ID,
} from './projectTeamClient';

export const PROJECT_KNOWLEDGE_CAPABILITY_IDS = Object.freeze([
  PROJECT_TEAM_ROUTE_ID,
  PROJECT_MEMORIES_ROUTE_ID,
  PROJECT_ENTITIES_ROUTE_ID,
  PROJECT_COMMUNITIES_ROUTE_ID,
  PROJECT_GRAPH_ROUTE_ID,
] as const);

export type ProjectKnowledgeCapabilityId =
  (typeof PROJECT_KNOWLEDGE_CAPABILITY_IDS)[number];

type CapabilityClient = Pick<
  ProjectKnowledgeClient<ProjectKnowledgeSnapshotBase>,
  'load'
>;

export type ProjectKnowledgeCapabilityClients = Readonly<
  Record<ProjectKnowledgeCapabilityId, CapabilityClient>
>;

export type ProjectKnowledgeCapabilityProjection = Readonly<
  Record<ProjectKnowledgeCapabilityId, DesktopCapabilityAvailability>
>;

const SERVICE_VERSION = '0.1.0';
const CONTRACT_VERSION = '4.0.0';

const LOCAL_REASONS: Readonly<Record<ProjectKnowledgeCapabilityId, string>> =
  Object.freeze({
    [PROJECT_TEAM_ROUTE_ID]: PROJECT_TEAM_LOCAL_REASON,
    [PROJECT_MEMORIES_ROUTE_ID]: PROJECT_MEMORIES_LOCAL_REASON,
    [PROJECT_ENTITIES_ROUTE_ID]: PROJECT_ENTITIES_LOCAL_REASON,
    [PROJECT_COMMUNITIES_ROUTE_ID]: PROJECT_COMMUNITIES_LOCAL_REASON,
    [PROJECT_GRAPH_ROUTE_ID]: PROJECT_GRAPH_LOCAL_REASON,
  });

const REASON_PREFIXES: Readonly<Record<ProjectKnowledgeCapabilityId, string>> =
  Object.freeze({
    [PROJECT_TEAM_ROUTE_ID]: 'project_team',
    [PROJECT_MEMORIES_ROUTE_ID]: 'project_memories',
    [PROJECT_ENTITIES_ROUTE_ID]: 'project_entities',
    [PROJECT_COMMUNITIES_ROUTE_ID]: 'project_communities',
    [PROJECT_GRAPH_ROUTE_ID]: 'project_graph',
  });

export function createProjectKnowledgeCapabilityClients(
  config: DesktopRuntimeConfig,
): ProjectKnowledgeCapabilityClients {
  return Object.freeze({
    [PROJECT_TEAM_ROUTE_ID]: createProjectTeamClient(config),
    [PROJECT_MEMORIES_ROUTE_ID]: createProjectMemoriesClient(config),
    [PROJECT_ENTITIES_ROUTE_ID]: createProjectEntitiesClient(config),
    [PROJECT_COMMUNITIES_ROUTE_ID]: createProjectCommunitiesClient(config),
    [PROJECT_GRAPH_ROUTE_ID]: createProjectGraphClient(config),
  });
}

export async function loadProjectKnowledgeCapabilities(
  clients: ProjectKnowledgeCapabilityClients,
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<ProjectKnowledgeCapabilityProjection> {
  const scope = capabilityScope(config);
  if (!scope) {
    return unavailableProjection(config, 'project_knowledge_scope_unavailable');
  }
  if (config.mode === 'local') {
    return Object.freeze(
      Object.fromEntries(
        PROJECT_KNOWLEDGE_CAPABILITY_IDS.map((capabilityId) => [
          capabilityId,
          unavailable(LOCAL_REASONS[capabilityId], scope),
        ]),
      ) as Record<ProjectKnowledgeCapabilityId, DesktopCapabilityAvailability>,
    );
  }

  const entries = await Promise.all(
    PROJECT_KNOWLEDGE_CAPABILITY_IDS.map(async (capabilityId) => {
      const capability = await loadCapability(
        capabilityId,
        clients[capabilityId],
        scope,
        signal,
      );
      return [capabilityId, capability] as const;
    }),
  );
  return Object.freeze(
    Object.fromEntries(entries) as Record<
      ProjectKnowledgeCapabilityId,
      DesktopCapabilityAvailability
    >,
  );
}

async function loadCapability(
  capabilityId: ProjectKnowledgeCapabilityId,
  client: CapabilityClient,
  scope: ProjectKnowledgeScope,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  try {
    const snapshot = await client.load(scope, { signal });
    if (!validObservation(snapshot, scope)) {
      return unavailable(
        `${REASON_PREFIXES[capabilityId]}_authority_contract_invalid`,
        scope,
      );
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
  scope: ProjectKnowledgeScope,
): input is ProjectKnowledgeSnapshotBase {
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

function validAvailabilityReason(
  availability: unknown,
  reasonCode: unknown,
): boolean {
  if (availability !== 'available' && availability !== 'degraded') return false;
  return availability === 'available'
    ? reasonCode === null
    : typeof reasonCode === 'string' &&
        reasonCode.length > 0 &&
        reasonCode.trim() === reasonCode;
}

function capabilityScope(
  config: DesktopRuntimeConfig,
): ProjectKnowledgeScope | null {
  const tenantId = identifier(config.tenantId);
  const projectId = identifier(config.projectId);
  return tenantId && projectId
    ? Object.freeze({ authority: config.mode, tenantId, projectId })
    : null;
}

function unavailableProjection(
  config: DesktopRuntimeConfig,
  reasonCode: string,
): ProjectKnowledgeCapabilityProjection {
  const fallbackScope = Object.freeze({
    authority: config.mode,
    tenantId: identifier(config.tenantId) ?? '',
    projectId: identifier(config.projectId) ?? '',
  });
  return Object.freeze(
    Object.fromEntries(
      PROJECT_KNOWLEDGE_CAPABILITY_IDS.map((capabilityId) => [
        capabilityId,
        unavailable(reasonCode, fallbackScope),
      ]),
    ) as Record<ProjectKnowledgeCapabilityId, DesktopCapabilityAvailability>,
  );
}

function unavailable(
  reasonCode: string,
  scope: ProjectKnowledgeScope,
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: Object.freeze([]),
    scope: snapshotScope(scope),
    authority_revision: null,
  });
}

function snapshotScope(scope: ProjectKnowledgeScope) {
  return Object.freeze({
    tenant_id: identifier(scope.tenantId),
    project_id: identifier(scope.projectId),
    workspace_id: null,
    instance_id: null,
  });
}

function identifier(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value.trim() === value
    ? value
    : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
