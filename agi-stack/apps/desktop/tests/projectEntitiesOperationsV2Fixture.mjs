export function projectEntitiesOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectEntities({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 41,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: 'desktop_project_entities_actions_partial',
        allowedActions: Object.freeze(['view', 'list']),
        entities: Object.freeze([]),
        total: 0,
        entityTypes: Object.freeze([]),
        ...overrides,
      });
    },
    async loadProjectEntityRelationships({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze([]);
    },
  });
}
