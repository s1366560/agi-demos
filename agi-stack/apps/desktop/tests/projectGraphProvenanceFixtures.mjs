export const scope = { authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' };
export const config = {
  apiBaseUrl: 'https://graph.test',
  deviceAuthorizationBaseUrl: 'https://graph.test',
  apiKey: 'test-session',
  localApiToken: '',
  tenantId: scope.tenantId,
  projectId: scope.projectId,
  workspaceId: '',
  workspaceRoot: '',
  mode: 'cloud',
};
export const episode = {
  id: 'element-episode',
  uuid: 'episode-uuid',
  name: 'Same name',
  label: 'Episode',
  type: 'Episodic',
  summary: null,
  content: 'Captured source text',
  memory_id: 'memory-1',
  source_description: 'document',
  created_at: '2026-09-08T01:00:00Z',
  tenant_id: scope.tenantId,
  project_id: scope.projectId,
};
export const entity = {
  id: 'element-entity',
  uuid: 'entity-uuid',
  name: 'Same name',
  label: 'Entity',
  type: 'Entity',
  summary: 'Entity summary',
};
export const other = { ...entity, id: 'element-other', uuid: 'other-uuid' };
export const community = {
  ...entity,
  id: 'element-community',
  uuid: 'community-uuid',
  type: 'Community',
};
export const mention = {
  id: 'element-mention',
  source: episode.id,
  target: entity.id,
  label: 'MENTIONS',
  weight: null,
};
export const relation = {
  id: 'element-relation',
  uuid: 'relation-uuid',
  source: entity.id,
  target: other.id,
  label: 'RELATES_TO',
  relationship_type: 'KNOWS',
  weight: 0.6,
  fact: 'A recorded relationship',
  episodes: [episode.uuid, 'missing-episode'],
  valid_at: '2026-09-07T00:00:00Z',
};
export const membership = {
  id: 'element-membership',
  source: entity.id,
  target: community.id,
  label: 'BELONGS_TO',
  weight: null,
};
export const snapshot = (operationScope = scope, overrides = {}) => ({
  scope: operationScope,
  scopeRevision: 23,
  authority: 'cloud',
  availability: 'degraded',
  reasonCode: 'desktop_project_graph_actions_partial',
  allowedActions: ['view'],
  nodes: [episode, entity, other, community],
  edges: [mention, relation, membership],
  ...overrides,
});
export const sourceSnapshot = (node = episode) =>
  snapshot(scope, { nodes: node ? [node] : [], edges: [] });
export const json = (value) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
export const deferred = () => {
  let resolve;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
};
