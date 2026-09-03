export function projectCommunitiesOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectCommunities({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 43,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: 'desktop_project_communities_actions_partial',
        allowedActions: Object.freeze(['view', 'list']),
        communities: Object.freeze([]),
        total: 0,
        ...overrides,
      });
    },
  });
}
