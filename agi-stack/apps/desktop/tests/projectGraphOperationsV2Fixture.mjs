export function projectGraphOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectGraph({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 37,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: 'desktop_project_graph_actions_partial',
        allowedActions: Object.freeze(['view']),
        nodes: Object.freeze([]),
        edges: Object.freeze([]),
        ...overrides,
      });
    },
  });
}
