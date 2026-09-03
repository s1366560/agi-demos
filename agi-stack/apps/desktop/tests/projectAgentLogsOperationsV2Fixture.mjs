export function projectAgentLogsOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectAgentLogs({ scope, status, limit, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 23,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: Object.freeze(['view', 'list-runs', 'filter-status']),
        runs: Object.freeze([]),
        total: 0,
        observedStatus: status,
        observedLimit: limit,
        ...overrides,
      });
    },
  });
}
