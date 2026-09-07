export function projectMemoriesOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectMemories({ scope, signal, page = 1, pageSize = 50 }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 47,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: 'desktop_project_memories_actions_partial',
        allowedActions: Object.freeze(['view', 'list']),
        memories: Object.freeze([]),
        total: 0,
        page,
        pageSize,
        ...overrides,
      });
    },
  });
}
