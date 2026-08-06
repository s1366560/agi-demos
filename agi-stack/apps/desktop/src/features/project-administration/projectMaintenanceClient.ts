import type { DesktopRuntimeConfig } from '../../types';
import {
  isRecord,
  observeProjectAdministrationScope,
  optionalText,
  projectAdministrationError,
  requestProjectAdministrationJson,
  requestProjectAdministrationNoContent,
  requireBoolean,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectAdministrationScope,
  type ProjectAdministrationOptions,
  type ProjectAdministrationScope,
  type ProjectAdministrationSnapshotBase,
  type ProjectMembershipRole,
} from './projectAdministrationClient';

export const PROJECT_MAINTENANCE_ROUTE_ID = 'project-project-maintenance' as const;
export const PROJECT_MAINTENANCE_LOCAL_REASON =
  'local_project_maintenance_authority_unavailable' as const;
export const PROJECT_MAINTENANCE_DEGRADED_REASON =
  'project_maintenance_export_file_ipc_unavailable' as const;

export type ProjectMaintenanceStats = Readonly<{
  entityCount: number;
  episodeCount: number;
  communityCount: number;
  edgeCount: number;
}>;
export type ProjectMaintenanceStatus = Readonly<{
  entities: number;
  episodes: number;
  communities: number;
  oldEpisodes: number;
  recommendations: readonly string[];
  lastChecked: string;
}>;
export type ProjectEmbeddingStatus = Readonly<{
  currentProvider: string;
  currentDimension: number;
  existingDimension: number;
  compatible: boolean;
  missingEmbeddings: number;
}>;
export type ProjectMaintenanceSnapshot = ProjectAdministrationSnapshotBase &
  Readonly<{
    stats: ProjectMaintenanceStats;
    maintenanceStatus: ProjectMaintenanceStatus;
    embeddingStatus: ProjectEmbeddingStatus;
  }>;
export type ProjectMaintenanceClient = Readonly<{
  load(
    scope: ProjectAdministrationScope,
    options?: ProjectAdministrationOptions,
  ): Promise<ProjectMaintenanceSnapshot>;
  incrementalRefresh(scope: ProjectAdministrationScope): Promise<void>;
  deduplicate(scope: ProjectAdministrationScope): Promise<void>;
  invalidateEdges(scope: ProjectAdministrationScope): Promise<void>;
  rebuildCommunities(scope: ProjectAdministrationScope): Promise<void>;
  rebuildEmbeddings(scope: ProjectAdministrationScope): Promise<void>;
}>;

const READ_ACTIONS = ['view', 'inspect-stats', 'inspect-embeddings'] as const;
const WRITE_ACTIONS = [
  'incremental-refresh',
  'deduplicate',
  'invalidate-edges',
  'rebuild-communities',
  'rebuild-embeddings',
] as const;

export function createProjectMaintenanceClient(
  config: DesktopRuntimeConfig,
): ProjectMaintenanceClient {
  const runtimeConfig = Object.freeze({ ...config });
  const mutate = async (scope: ProjectAdministrationScope, path: string): Promise<void> => {
    const currentScope = requireProjectAdministrationScope(
      runtimeConfig,
      scope,
      PROJECT_MAINTENANCE_LOCAL_REASON,
    );
    await requestProjectAdministrationNoContent(runtimeConfig, path, {
      method: 'POST',
      query: { tenant_id: currentScope.tenantId, project_id: currentScope.projectId },
    });
  };
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        scope,
        PROJECT_MAINTENANCE_LOCAL_REASON,
      );
      const authority = await observeProjectAdministrationScope(runtimeConfig, currentScope, options);
      const query = { tenant_id: currentScope.tenantId, project_id: currentScope.projectId };
      const [maintenancePayload, statsPayload, embeddingPayload] = await Promise.all([
        requestProjectAdministrationJson(runtimeConfig, '/api/v1/maintenance/status', {
          ...options,
          query,
        }),
        requestProjectAdministrationJson(runtimeConfig, '/api/v1/data/stats', {
          ...options,
          query,
        }),
        requestProjectAdministrationJson(runtimeConfig, '/api/v1/maintenance/embeddings/status', {
          ...options,
          query,
        }),
      ]);
      return Object.freeze({
        scope: currentScope,
        scopeRevision: authority.revision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_MAINTENANCE_DEGRADED_REASON,
        contractVersion: '4.0.0',
        allowedActions: allowedActions(authority.membershipRole),
        membershipRole: authority.membershipRole,
        stats: parseStats(statsPayload),
        maintenanceStatus: parseMaintenanceStatus(maintenancePayload),
        embeddingStatus: parseEmbeddingStatus(embeddingPayload),
      });
    },
    incrementalRefresh: (scope) => mutate(scope, '/api/v1/maintenance/incremental-refresh'),
    deduplicate: (scope) => mutate(scope, '/api/v1/maintenance/deduplicate'),
    invalidateEdges: (scope) => mutate(scope, '/api/v1/maintenance/invalidate-edges'),
    rebuildCommunities: (scope) => mutate(scope, '/api/v1/maintenance/communities/rebuild'),
    rebuildEmbeddings: (scope) => mutate(scope, '/api/v1/maintenance/embeddings/rebuild'),
  });
}

function allowedActions(role: ProjectMembershipRole): readonly string[] {
  return Object.freeze([
    ...READ_ACTIONS,
    ...(role === 'owner' || role === 'admin' ? WRITE_ACTIONS : []),
  ]);
}

function parseStats(payload: unknown): ProjectMaintenanceStats {
  if (!isRecord(payload)) throw projectAdministrationError('project_maintenance_contract_invalid');
  return Object.freeze({
    entityCount: requireNonnegativeInteger(
      payload.entity_count,
      'project_maintenance_contract_invalid',
    ),
    episodeCount: requireNonnegativeInteger(
      payload.episodic_count,
      'project_maintenance_contract_invalid',
    ),
    communityCount: requireNonnegativeInteger(
      payload.community_count,
      'project_maintenance_contract_invalid',
    ),
    edgeCount: requireNonnegativeInteger(payload.edge_count, 'project_maintenance_contract_invalid'),
  });
}

function parseMaintenanceStatus(payload: unknown): ProjectMaintenanceStatus {
  if (!isRecord(payload) || !isRecord(payload.stats) || !Array.isArray(payload.recommendations)) {
    throw projectAdministrationError('project_maintenance_contract_invalid');
  }
  return Object.freeze({
    entities: requireNonnegativeInteger(
      payload.stats.entities,
      'project_maintenance_contract_invalid',
    ),
    episodes: requireNonnegativeInteger(
      payload.stats.episodes,
      'project_maintenance_contract_invalid',
    ),
    communities: requireNonnegativeInteger(
      payload.stats.communities,
      'project_maintenance_contract_invalid',
    ),
    oldEpisodes: requireNonnegativeInteger(
      payload.stats.old_episodes,
      'project_maintenance_contract_invalid',
    ),
    recommendations: Object.freeze(
      payload.recommendations.map((value) =>
        requireIdentifier(value, 'project_maintenance_contract_invalid'),
      ),
    ),
    lastChecked:
      optionalText(payload.last_checked, 'project_maintenance_contract_invalid') ?? '',
  });
}

function parseEmbeddingStatus(payload: unknown): ProjectEmbeddingStatus {
  if (!isRecord(payload)) throw projectAdministrationError('project_maintenance_contract_invalid');
  return Object.freeze({
    currentProvider: requireIdentifier(
      payload.current_provider,
      'project_maintenance_contract_invalid',
    ),
    currentDimension: requireNonnegativeInteger(
      payload.current_dimension,
      'project_maintenance_contract_invalid',
    ),
    existingDimension: requireNonnegativeInteger(
      payload.existing_dimension,
      'project_maintenance_contract_invalid',
    ),
    compatible: requireBoolean(payload.is_compatible, 'project_maintenance_contract_invalid'),
    missingEmbeddings: requireNonnegativeInteger(
      payload.missing_embeddings,
      'project_maintenance_contract_invalid',
    ),
  });
}
