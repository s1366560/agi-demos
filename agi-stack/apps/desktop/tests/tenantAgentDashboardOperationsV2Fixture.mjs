export function tenantAgentDashboardOperationsV2Fixture() {
  return Object.freeze({
    async loadTenantAgentDashboard({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      throw new Error('tenant_agent_dashboard_authority_unavailable');
    },
    async updateTenantAgentDashboardConfig() {
      throw new Error('tenant_agent_dashboard_authority_unavailable');
    },
    async inspectTenantAgentDashboardTrace() {
      throw new Error('tenant_agent_dashboard_authority_unavailable');
    },
  });
}
