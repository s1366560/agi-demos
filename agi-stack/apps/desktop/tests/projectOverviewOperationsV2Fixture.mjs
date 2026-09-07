export function projectOverviewOperationsV2Fixture() {
  return Object.freeze({
    async loadProjectOverview() {
      throw new Error('project_overview_not_exercised');
    },
    async probeProjectOverview({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const local = scope.authority === 'local';
      return Object.freeze({
        availability: local ? 'degraded' : 'unavailable',
        reason_code: local
          ? 'local_project_overview_timeline_projection_only'
          : 'capability_authority_revision_unavailable',
        service_version: '0.1.0',
        contract_version: local ? '4.0.0' : '3.0.0',
        allowed_actions: Object.freeze(local ? ['view'] : []),
        scope: Object.freeze({
          tenant_id: scope.tenantId,
          project_id: scope.projectId,
          workspace_id: null,
          instance_id: null,
        }),
        authority_revision: local ? 1 : null,
      });
    },
  });
}
