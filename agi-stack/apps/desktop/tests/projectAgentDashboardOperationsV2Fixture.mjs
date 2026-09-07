export function projectAgentDashboardOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectAgentDashboard({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 29,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: Object.freeze(['view', 'list-runs', 'inspect-active-count']),
        runs: Object.freeze([]),
        total: 0,
        activeCount: 0,
        ...overrides,
      });
    },
  });
}
