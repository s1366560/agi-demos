const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search-current-page',
  'filter-status-current-page',
  'paginate',
  'inspect-health',
]);

export function runtimeClustersOperationsV2Fixture(overrides = {}) {
  return {
    async listRuntimeClusters(input) {
      if (overrides.listRuntimeClusters) return overrides.listRuntimeClusters(input);
      return {
        clusters: [],
        total: 0,
        page: input.query?.page ?? 1,
        pageSize: input.query?.pageSize ?? 20,
      };
    },
    async getRuntimeClusterHealth(input) {
      if (overrides.getRuntimeClusterHealth) return overrides.getRuntimeClusterHealth(input);
      return {
        status: 'healthy',
        nodeCount: 1,
        cpuUsage: null,
        memoryUsage: null,
        checkedAt: null,
      };
    },
    async probeRuntimeClusters(input) {
      if (overrides.probeRuntimeClusters) return overrides.probeRuntimeClusters(input);
      const local = input.scope.authority === 'local';
      return {
        availability: local ? 'not_applicable' : 'degraded',
        reason_code: local
          ? 'cloud_cluster_control_not_applicable'
          : 'runtime_clusters_detail_and_mutations_partial',
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
