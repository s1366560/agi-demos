const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search',
  'filter-status',
  'paginate',
  'restart',
  'delete',
]);
const LOCAL_ACTIONS = Object.freeze(['view', 'list', 'refresh', 'search', 'filter-status']);

export function runtimeInstancesOperationsV2Fixture(overrides = {}) {
  return {
    async listRuntimeInstances(input) {
      if (overrides.listRuntimeInstances) return overrides.listRuntimeInstances(input);
      return { instances: [], total: 0, page: input.query?.page ?? 1, pageSize: input.query?.pageSize ?? 20 };
    },
    async restartRuntimeInstance(input) {
      if (overrides.restartRuntimeInstance) return overrides.restartRuntimeInstance(input);
    },
    async deleteRuntimeInstance(input) {
      if (overrides.deleteRuntimeInstance) return overrides.deleteRuntimeInstance(input);
    },
    async probeRuntimeInstances(input) {
      if (overrides.probeRuntimeInstances) return overrides.probeRuntimeInstances(input);
      const local = input.scope.authority === 'local';
      return {
        availability: 'degraded',
        reason_code: local
          ? 'local_instance_sidecar_projection_partial'
          : 'runtime_instances_nested_routes_partial',
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: [...(local ? LOCAL_ACTIONS : CLOUD_ACTIONS)],
        scope: {
          tenant_id: input.scope.tenantId,
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
      };
    },
  };
}
