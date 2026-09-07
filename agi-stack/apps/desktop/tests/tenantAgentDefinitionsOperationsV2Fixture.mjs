export function tenantAgentDefinitionsOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadTenantAgentDefinitions({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze([]);
    },
    async listTenantAgentDefinitionExternalAcpAgents({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze([]);
    },
    async createTenantAgentDefinition() {
      throw new Error('tenant_agent_definitions_authority_unavailable');
    },
    async updateTenantAgentDefinition() {
      throw new Error('tenant_agent_definitions_authority_unavailable');
    },
    async setTenantAgentDefinitionEnabled() {
      throw new Error('tenant_agent_definitions_authority_unavailable');
    },
    async deleteTenantAgentDefinition() {
      throw new Error('tenant_agent_definitions_authority_unavailable');
    },
    ...overrides,
  });
}
