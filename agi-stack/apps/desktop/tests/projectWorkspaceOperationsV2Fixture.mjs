export function projectWorkspaceOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    desktopWorkspaceCatalogOperationsV2: Object.freeze({
      async listWorkspacesForProject(input) {
        if (overrides.listWorkspacesForProject) {
          return overrides.listWorkspacesForProject(input);
        }
        return [];
      },
    }),
    desktopWorkspaceLifecycleOperationsV2: Object.freeze({
      async createWorkspace(input) {
        if (overrides.createWorkspace) return overrides.createWorkspace(input);
        return Object.freeze({
          id: 'workspace-created',
          tenant_id: input.config.tenantId,
          project_id: input.config.projectId,
          name: input.input.name,
          description: input.input.description,
          is_archived: false,
          created_at: '2026-09-03T00:00:00Z',
          updated_at: null,
        });
      },
    }),
  });
}
