const ALLOWED_ACTIONS = Object.freeze(['view', 'list', 'create', 'open-blackboard']);

export function projectWorkspacesClientV2Fixture(overrides = {}) {
  return Object.freeze({
    async list(scope, options) {
      if (overrides.list) return overrides.list(scope, options);
      if (options?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        authority: scope.authority,
        availability: scope.authority === 'cloud' ? 'available' : 'degraded',
        reasonCode:
          scope.authority === 'cloud' ? null : 'local_workspace_lifecycle_partial',
        serviceVersion: '1.0.0',
        contractVersion: '1.0.0',
        authorityRevision: null,
        allowedActions: ALLOWED_ACTIONS,
        workspaces: Object.freeze([]),
      });
    },
  });
}
