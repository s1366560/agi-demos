export function projectSchemaOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectSchema({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 67,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: 'desktop_project_schema_actions_and_export_unwired',
        contractVersion: '4.0.0',
        allowedActions: Object.freeze(['view', 'list-entity-types']),
        membershipRole: 'member',
        entityTypes: Object.freeze([]),
        edgeTypes: Object.freeze([]),
        mappings: Object.freeze([]),
        ...overrides,
      });
    },
  });
}
