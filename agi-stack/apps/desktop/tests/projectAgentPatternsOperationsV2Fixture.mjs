export function projectAgentPatternsOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectAgentPatterns({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 31,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: Object.freeze(['view', 'list-patterns', 'inspect-shared-scope']),
        scopeKind: 'tenant_shared',
        patterns: Object.freeze([]),
        total: 0,
        ...overrides,
      });
    },
  });
}
