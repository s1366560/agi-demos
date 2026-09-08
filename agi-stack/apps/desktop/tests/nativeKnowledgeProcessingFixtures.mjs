import { readFileSync } from 'node:fs';
export const wireCases = JSON.parse(
  readFileSync(
    new URL('../../../../shared/fixtures/native-knowledge.v1.json', import.meta.url),
    'utf8',
  ),
).requests.filter((c) => c.path.includes('/processing-'));
export const nativeScope = wireCases[0].request.scope;
export const projectScope = {
  authority: 'local',
  tenantId: nativeScope.tenant_id,
  projectId: nativeScope.project_id,
};
export const config = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'identity',
  localApiToken: 'launch',
  tenantId: projectScope.tenantId,
  projectId: projectScope.projectId,
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
};
export const source = {
  tenant_id: 'tenant',
  project_id: 'project',
  memory_id: 'memory',
  revision: 1,
  change_sequence: 1,
};
export const input = wireCases.find((c) => c.name === 'retry_index').request.command.input;
export const embedding = {
  revision: 1,
  build_id: 'build',
  provider_id: 'provider',
  provider_revision: 0,
  model_id: 'explicit-model',
  dimensions: 3,
  input_contract_version: 1,
  normalization_version: 1,
};
export const processing = {
  current_sources: 1,
  applied_sources: 1,
  pending_sources: 0,
  failed_sources: 0,
};
export const index = {
  current_sources: 1,
  completed_sources: 1,
  failed_sources: 0,
};
export const results = {
  configuration: {
    configuration: embedding,
    active_build_id: 'build',
    processing,
    index,
  },
  entities: {
    items: [
      {
        reference: { source, entity_index: 0 },
        audit_attempt: 1,
        entity: { name: 'Entity', kind: 'concept' },
      },
    ],
    next_cursor: null,
  },
  relationships: {
    items: [
      {
        source,
        relationship_index: 0,
        audit_attempt: 1,
        source_entity: { source, entity_index: 0 },
        target_entity: { source, entity_index: 1 },
        relationship: {
          source_index: 0,
          target_index: 1,
          relation_type: 'linked',
          fact: 'A links B',
          score: 0.8,
        },
      },
    ],
    next_cursor: null,
  },
  text: {
    items: [{ source, audit_attempt: 1, title: 'Title', content: 'Content' }],
    next_cursor: null,
  },
  semantic: {
    configuration: embedding,
    processing,
    index,
    hits: [{ input, score: 0.8 }],
  },
  configure_embedding: { configuration: embedding },
  select_embedding: { configuration: { ...embedding, revision: 2 } },
  index_one: {
    receipt: { input, attempt: 1, status: 'indexed', failure: null },
  },
  promote_index: { configuration: embedding, active_build_id: 'build' },
  retry_index: { accepted: true, input, attempt: 1 },
  retry_processing: { accepted: true, source, attempt: 1 },
  processing_task: { source, current: true, task: { state: 'failed', attempt: 1, failure: 'provider_unavailable' } },
  process_one: {
    receipt: { source, attempt: 1, status: 'applied', failure: null },
  },
};
export const capability = {
  availability: 'degraded',
  reason_code: 'partial',
  service_version: '1.0.0',
  contract_version: '1.0.0',
  allowed_actions: wireCases.map((c) => c.name),
  scope: {
    tenant_id: 'tenant',
    project_id: 'project',
    workspace_id: null,
    instance_id: null,
  },
  authority_revision: 1,
  retryable: false,
  authority_source: 'sidecar',
  supporting_authority_sources: [],
  provenance: 'observed',
};
export const json = (value, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
export const response = (name) => ({
  contract_version: '1.0.0',
  scope: nativeScope,
  result: structuredClone(results[name]),
});
export const operation = (name) =>
  structuredClone(
    wireCases.find((c) => c.name === name).request.query ??
      wireCases.find((c) => c.name === name).request.command,
  );
