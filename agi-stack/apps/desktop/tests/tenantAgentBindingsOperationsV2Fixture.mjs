export function tenantAgentBindingsOperationsV2Fixture() {
  return Object.freeze({
    async listTenantAgentBindings({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        authority: scope.authority,
        availability: 'unavailable',
        reasonCode: 'tenant_agent_bindings_authority_unavailable',
        serviceVersion: '0.1.0',
        contractVersion: '3.0.0',
        allowedActions: Object.freeze([]),
        authorityRevision: null,
        bindings: Object.freeze([]),
        definitions: Object.freeze([]),
      });
    },
    async createTenantAgentBinding() {
      throw new Error('tenant_agent_bindings_authority_unavailable');
    },
    async deleteTenantAgentBinding() {
      throw new Error('tenant_agent_bindings_authority_unavailable');
    },
    async setTenantAgentBindingEnabled() {
      throw new Error('tenant_agent_bindings_authority_unavailable');
    },
    async testTenantAgentBinding() {
      throw new Error('tenant_agent_bindings_authority_unavailable');
    },
  });
}
