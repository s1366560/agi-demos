import { createRequire } from 'node:module';
export const require = createRequire(import.meta.url);
export const dist =
  process.env.NATIVE_PROJECT_SCHEMA_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
export const scope = {
  tenant_id: 'tenant-a',
  project_id: 'project-a',
  context_revision: 0,
  profile_id: 'schema-test',
  generation: 1,
  digest: 'ab'.repeat(32),
};
export const actor = 'local-actor';
export const options = { expectedScope: scope, expectedActorId: actor };
export const projectScope = {
  authority: 'local',
  tenantId: scope.tenant_id,
  projectId: scope.project_id,
};
export const config = {
  apiBaseUrl: 'http://127.0.0.1:4318',
  deviceAuthorizationBaseUrl: '',
  apiKey: 'identity',
  localApiToken: 'launch',
  tenantId: scope.tenant_id,
  projectId: scope.project_id,
  workspaceId: '',
  mode: 'local',
  workspaceRoot: '/tmp/schema-test',
};
export const document = {
  format_version: 1,
  tenant_id: scope.tenant_id,
  project_id: scope.project_id,
  schema_id: '00000000-0000-4000-8000-000000000001',
  revision: 1,
  deleted: false,
  entity_types: [],
  edge_types: [],
  mappings: [],
  tombstones: [],
};
export const change = '00000000-0000-4000-8000-000000000002';
export const envelope = (operation, result) => ({
  contract_version: '1.0.0',
  authority: 'native-project-schema',
  operation,
  actor_id: actor,
  scope,
  result,
});
export const receipt = {
  format_version: 1,
  actor_id: actor,
  change_id: change,
  sequence: 1,
  document,
};
export const capability = envelope('schema_capabilities', {
  route_id: 'project-project-schema',
  availability: 'degraded',
  reason_code: 'project_schema_internal_validation',
  allowed_actions: [
    'schema_read',
    'schema_bootstrap',
    'schema_replace',
    'schema_receipt',
    'schema_history',
  ],
  provenance: 'observed',
  authority_source: 'sidecar',
});
export const json = (value, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  });
export function install(fn) {
  const old = globalThis.fetch;
  globalThis.fetch = fn;
  return () => {
    globalThis.fetch = old;
  };
}
export function observation(url) {
  if (String(url).endsWith('/auth/me')) return json({ user_id: actor, is_active: true });
  if (String(url).endsWith('/knowledge/context')) return json({ contract_version: '1.0.0', scope });
  return null;
}
