export function projectMaintenanceOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectMaintenance({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 68,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: 'desktop_project_maintenance_surface_and_endpoints_incomplete',
        contractVersion: '4.0.0',
        allowedActions: Object.freeze(['view']),
        membershipRole: 'member',
        stats: Object.freeze({
          entityCount: 4,
          episodeCount: 5,
          communityCount: 2,
          edgeCount: 8,
        }),
        maintenanceStatus: Object.freeze({
          entities: 4,
          episodes: 5,
          communities: 2,
          oldEpisodes: 1,
          recommendations: Object.freeze(['refresh']),
          lastChecked: '2026-09-03T00:00:00Z',
        }),
        embeddingStatus: Object.freeze({
          currentProvider: 'openai',
          currentDimension: 1536,
          existingDimension: 1536,
          compatible: true,
          missingEmbeddings: 0,
        }),
        ...overrides,
      });
    },
  });
}
