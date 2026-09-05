export function tenantPromptTemplatesOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async listTenantPromptTemplates() { return []; },
    async createTenantPromptTemplate(input) {
      return {
        id: 'template-1',
        revision: 1,
        tenant_id: input.scope.tenantId,
        project_id: null,
        created_by: 'user-1',
        title: input.input.title,
        content: input.input.content,
        category: input.input.category,
        variables: [],
        is_system: false,
        usage_count: 0,
        created_at: '2026-09-05T00:00:00Z',
        updated_at: '2026-09-05T00:00:00Z',
      };
    },
    async deleteTenantPromptTemplate() {},
    ...overrides,
  });
}
