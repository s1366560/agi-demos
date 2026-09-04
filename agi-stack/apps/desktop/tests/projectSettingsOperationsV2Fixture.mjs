export function projectSettingsOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectSettings({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 68,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: 'desktop_project_settings_actions_unwired',
        contractVersion: '4.0.0',
        allowedActions: Object.freeze(['view']),
        membershipRole: 'member',
        project: Object.freeze({
          id: scope.projectId,
          tenantId: scope.tenantId,
          name: 'Project Settings',
          description: 'Settings fixture',
          ownerId: 'user-1',
          isPublic: false,
          memoryRules: Object.freeze({
            maxEpisodes: 200,
            retentionDays: 30,
            autoRefresh: true,
            refreshInterval: 10,
          }),
          graphConfig: Object.freeze({
            maxNodes: 1000,
            maxEdges: 2000,
            similarityThreshold: 0.75,
            communityDetection: true,
          }),
          sandboxType: 'docker',
          conversationMode: 'threaded',
          createdAt: '2026-09-03T00:00:00Z',
          updatedAt: null,
        }),
        sandbox: null,
        sandboxStats: null,
        ...overrides,
      });
    },
  });
}
