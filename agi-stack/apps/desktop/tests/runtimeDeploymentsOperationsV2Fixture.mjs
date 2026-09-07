const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'paginate',
  'inspect-progress',
  'reconnect-progress',
]);

export function runtimeDeploymentsOperationsV2Fixture(overrides = {}) {
  return {
    async listRuntimeDeployments(input) {
      if (overrides.listRuntimeDeployments) return overrides.listRuntimeDeployments(input);
      return {
        deployments: [],
        total: 0,
        page: input.query?.page ?? 1,
        pageSize: input.query?.pageSize ?? 10,
      };
    },
    async getRuntimeDeployment(input) {
      if (overrides.getRuntimeDeployment) return overrides.getRuntimeDeployment(input);
      throw new Error('runtime_deployment_fixture_missing');
    },
    async streamRuntimeDeploymentProgress(input) {
      if (overrides.streamRuntimeDeploymentProgress) {
        return overrides.streamRuntimeDeploymentProgress(input);
      }
    },
    async probeRuntimeDeployments(input) {
      if (overrides.probeRuntimeDeployments) return overrides.probeRuntimeDeployments(input);
      const local = input.scope.authority === 'local';
      return {
        availability: local ? 'not_applicable' : 'degraded',
        reason_code: local
          ? 'cloud_deployment_authority_not_applicable'
          : 'runtime_deployments_mutations_and_instance_discovery_partial',
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
