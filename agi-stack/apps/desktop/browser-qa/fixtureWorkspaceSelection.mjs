export function fixtureWorkspaceSwitch(context, tenantId, projectId) {
  if (context?.project_id === projectId && context?.tenant_id === tenantId) {
    return null;
  }
  return {
    tenant_id: tenantId,
    project_id: projectId,
    expected_revision: context?.revision,
    idempotency_key: `neo4j-gate-${projectId}`,
  };
}
