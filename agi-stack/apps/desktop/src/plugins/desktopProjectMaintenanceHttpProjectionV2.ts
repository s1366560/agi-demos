import {
  isRecord,
  observeProjectAdministrationScope,
  optionalText,
  projectAdministrationError,
  requestProjectAdministrationJson,
  requireBoolean,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectAdministrationScope,
  type ProjectAdministrationScope,
} from '../features/project-administration/projectAdministrationClient';
import {
  PROJECT_MAINTENANCE_DEGRADED_REASON,
  PROJECT_MAINTENANCE_LOCAL_REASON,
  type ProjectEmbeddingStatus,
  type ProjectMaintenanceSnapshot,
  type ProjectMaintenanceStats,
  type ProjectMaintenanceStatus,
} from '../features/project-administration/projectMaintenanceClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectMaintenanceRuntimeConfigV2,
  cloneDesktopProjectMaintenanceScopeV2,
} from './desktopProjectMaintenanceOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view']);

export type DesktopProjectMaintenanceHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectMaintenanceSnapshot>;
}>;

export function createDesktopProjectMaintenanceHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectAdministrationScope,
): DesktopProjectMaintenanceHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectMaintenanceRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectMaintenanceScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        operationScope,
        PROJECT_MAINTENANCE_LOCAL_REASON,
      );
      const authority = await observeProjectAdministrationScope(runtimeConfig, currentScope, {
        signal,
      });
      const query = { tenant_id: currentScope.tenantId, project_id: currentScope.projectId };
      const [maintenancePayload, statsPayload, embeddingPayload] = await Promise.all([
        requestProjectAdministrationJson(runtimeConfig, '/api/v1/maintenance/status', {
          signal,
          query,
        }),
        requestProjectAdministrationJson(runtimeConfig, '/api/v1/data/stats', { signal, query }),
        requestProjectAdministrationJson(runtimeConfig, '/api/v1/maintenance/embeddings/status', {
          signal,
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
        allowedActions: ACTIONS_V2,
        membershipRole: authority.membershipRole,
        stats: parseStatsV2(statsPayload),
        maintenanceStatus: parseMaintenanceStatusV2(maintenancePayload),
        embeddingStatus: parseEmbeddingStatusV2(embeddingPayload),
      });
    },
  });
}

function parseStatsV2(payload: unknown): ProjectMaintenanceStats {
  if (!isRecord(payload)) throw invalidContractV2();
  return Object.freeze({
    entityCount: requireNonnegativeInteger(payload.entity_count, invalidContractCodeV2()),
    episodeCount: requireNonnegativeInteger(payload.episodic_count, invalidContractCodeV2()),
    communityCount: requireNonnegativeInteger(payload.community_count, invalidContractCodeV2()),
    edgeCount: requireNonnegativeInteger(payload.edge_count, invalidContractCodeV2()),
  });
}

function parseMaintenanceStatusV2(payload: unknown): ProjectMaintenanceStatus {
  if (!isRecord(payload) || !isRecord(payload.stats) || !Array.isArray(payload.recommendations)) {
    throw invalidContractV2();
  }
  return Object.freeze({
    entities: requireNonnegativeInteger(payload.stats.entities, invalidContractCodeV2()),
    episodes: requireNonnegativeInteger(payload.stats.episodes, invalidContractCodeV2()),
    communities: requireNonnegativeInteger(payload.stats.communities, invalidContractCodeV2()),
    oldEpisodes: requireNonnegativeInteger(payload.stats.old_episodes, invalidContractCodeV2()),
    recommendations: Object.freeze(
      payload.recommendations.map((value) => requireIdentifier(value, invalidContractCodeV2())),
    ),
    lastChecked: optionalText(payload.last_checked, invalidContractCodeV2()) ?? '',
  });
}

function parseEmbeddingStatusV2(payload: unknown): ProjectEmbeddingStatus {
  if (!isRecord(payload)) throw invalidContractV2();
  return Object.freeze({
    currentProvider: requireIdentifier(payload.current_provider, invalidContractCodeV2()),
    currentDimension: requireNonnegativeInteger(
      payload.current_dimension,
      invalidContractCodeV2(),
    ),
    existingDimension: requireNonnegativeInteger(
      payload.existing_dimension,
      invalidContractCodeV2(),
    ),
    compatible: requireBoolean(payload.is_compatible, invalidContractCodeV2()),
    missingEmbeddings: requireNonnegativeInteger(
      payload.missing_embeddings,
      invalidContractCodeV2(),
    ),
  });
}

function invalidContractCodeV2(): string {
  return 'project_maintenance_contract_invalid';
}

function invalidContractV2(): Error {
  return projectAdministrationError(invalidContractCodeV2());
}
