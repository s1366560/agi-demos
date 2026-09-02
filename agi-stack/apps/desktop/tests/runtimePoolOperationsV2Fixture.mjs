const CLOUD_ACTIONS = Object.freeze([
  'view',
  'refresh',
  'toggle-auto-refresh',
  'list-instances',
  'search-current-page',
  'filter-by-tier',
  'paginate-instances',
  'pause-instance',
  'resume-instance',
  'terminate-instance',
  'retry-list-instances',
  'inspect-pool-status',
]);

export function runtimePoolOperationsV2Fixture(overrides = {}) {
  return {
    async probeRuntimePool(input) {
      if (overrides.probeRuntimePool) return overrides.probeRuntimePool(input);
      const local = input.scope.authority === 'local';
      return {
        availability: local ? 'not_applicable' : 'degraded',
        reason_code: local
          ? 'cloud_runtime_pool_not_applicable'
          : 'global_pool_capacity_not_available_in_tenant_scope',
        service_version: local ? null : '0.1.0',
        contract_version: local ? null : '3.0.0',
        allowed_actions: local ? [] : [...CLOUD_ACTIONS],
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
