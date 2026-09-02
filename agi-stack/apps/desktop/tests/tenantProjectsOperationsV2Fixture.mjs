export function tenantProjectsOperationsV2Fixture() {
  return Object.freeze({
    async listTenantProjects({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        authority: scope.authority,
        availability: 'unavailable',
        reasonCode: 'tenant_projects_authority_unavailable',
        serviceVersion: '0.1.0',
        contractVersion: '3.0.0',
        allowedActions: Object.freeze([]),
        authorityRevision: null,
        projects: Object.freeze([]),
        total: 0,
        page: 1,
        pageSize: 1,
        ownerIds: Object.freeze([]),
      });
    },
    async getTenantProject() {
      throw new Error('tenant_projects_authority_unavailable');
    },
    async createTenantProject() {
      throw new Error('tenant_projects_authority_unavailable');
    },
    async updateTenantProject() {
      throw new Error('tenant_projects_authority_unavailable');
    },
    async deleteTenantProject() {
      throw new Error('tenant_projects_authority_unavailable');
    },
  });
}
