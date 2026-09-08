export const projectScope = { authority: 'local', tenantId: 'tenant-1', projectId: 'project-1' };
export const nativeScope = {
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  context_revision: 7,
  profile_id: 'native-profile',
  generation: 4,
  digest: 'native-digest',
};
export const uuid = '00000000-0000-4000-8000-000000000001';
export const changeId = '00000000-0000-4000-8000-000000000002';
export const content = {
  title: 'Memory',
  content: 'text',
  content_type: 'text',
  tags: [],
  metadata: { preserved: true },
  status: 'ENABLED',
};
export const memory = {
  id: 'memory-1',
  project_id: 'project-1',
  title: 'Memory',
  content: 'local',
  author_id: 'local-actor',
  content_type: 'text',
  tags: [],
  entities: [],
  version: 1,
  status: 'ENABLED',
  created_at_ms: 100,
  embedding: null,
  metadata: {},
};
export const remote = {
  memory_id: 'memory-1',
  revision: 2,
  deleted: false,
  author_id: 'remote-actor',
  created_at_ms: 100,
  content,
  extension: { retained: true },
};
export const link = {
  remote_tenant_id: 'remote-tenant',
  remote_project_id: 'remote-project',
  remote_actor_id: 'remote-actor',
};
export const status = { replica_id: uuid, link, pending_changes: 1 };
export const guard = {
  expected_local_revision: 1,
  expected_remote_revision: 2,
  expected_baseline_revision: 0,
  conflict_sequences: [2],
};
export const proposal = {
  memory_id: 'memory-1',
  operation: 'create',
  expected_revision: 0,
  content,
};
export const conflict = {
  id: uuid,
  memory_id: 'memory-1',
  proposed: proposal,
  current: remote,
  observed_current: remote,
  resolved_change_id: null,
};
export const pullContext = {
  memory_id: 'memory-1',
  conflict_sequences: [2],
  local: memory,
  local_deleted: false,
  local_metadata: {},
  baseline: null,
  remote,
};
export const cloudContext = {
  local_sequence: 1,
  memory_id: 'memory-1',
  conflict_id: uuid,
  original_request: { ...proposal, change_id: changeId },
  cloud_conflict: conflict,
  local: memory,
  local_deleted: false,
  local_metadata: {},
  baseline: null,
  remote,
  conflict_sequences: [2],
  pending_sequences: [1],
  observed_cursor: 2,
};
export const pullResolution = {
  ...guard,
  memory_id: 'memory-1',
  choice: { decision: 'use_remote' },
};
export const cloudResolution = {
  local_sequence: 1,
  memory_id: 'memory-1',
  conflict_id: uuid,
  guard,
  choice: { decision: 'keep_current' },
};
export const reconciliation = { guard, choice: { decision: 'keep_both' } };
export const localReceipt = {
  resolution_id: changeId,
  memory_id: 'memory-1',
  local_revision: 2,
  remote_baseline_revision: 2,
  copy_memory_id: null,
  processing_sequences: [3],
  pending_push_sequences: [],
  superseded_sequences: [1],
  conflict_sequences: [2],
};
export const cloudReceipt = {
  status: 'resolved',
  change_id: changeId,
  conflict_id: uuid,
  version: remote,
};
export const outcome = {
  resolution_id: changeId,
  receipt: cloudReceipt,
  pending_reconciliation: true,
  replayed: false,
};
export const record = {
  resolution_id: changeId,
  local_sequence: 1,
  request_json: JSON.stringify({
    change_id: changeId,
    expected_current_revision: 2,
    decision: 'keep_current',
    content: null,
  }),
  command: cloudResolution,
  archive: cloudContext,
  receipt: cloudReceipt,
  rejection: null,
  reconciliation: null,
  reconciliation_command: null,
  reconciliation_archive: null,
};
export const cases = [
  [{ operation: 'sync_status' }, { status }],
  [
    { operation: 'sync_link', link },
    { status, association_state: 'configured', remote_authorization: 'unverified' },
  ],
  [
    { operation: 'sync_push' },
    {
      local_sequence: 1,
      replayed: false,
      receipt: { status: 'conflict', change_id: changeId, conflict_id: uuid },
    },
  ],
  [{ operation: 'sync_pull' }, { next_cursor: 3, applied: 1, conflicts: 0, has_more: false }],
  [
    { operation: 'sync_outbox', after_sequence: 0, limit: 10 },
    {
      items: [{ change_id: changeId, local_change: { sequence: 1, memory, deleted: false } }],
      next_sequence: 1,
    },
  ],
  [{ operation: 'remote_baseline', id: 'memory-1' }, { version: remote }],
  [{ operation: 'push_conflicts', limit: 10 }, { items: [conflict] }],
  [
    { operation: 'pull_conflicts', limit: 10 },
    {
      items: [
        {
          sequence: 2,
          memory_id: 'memory-1',
          remote,
          local: memory,
          local_deleted: false,
          baseline: null,
        },
      ],
    },
  ],
  [{ operation: 'pull_conflict_context', id: 'memory-1' }, { context: pullContext }],
  [
    { operation: 'resolution_history', id: 'memory-1', limit: 10 },
    { items: [{ request: pullResolution, receipt: localReceipt, archive: pullContext }] },
  ],
  [
    { operation: 'resolve_pull', resolution: pullResolution, idempotency_key: 'local-decision' },
    { receipt: localReceipt, replayed: false },
  ],
  [{ operation: 'cloud_conflict_context', local_sequence: 1 }, { context: cloudContext }],
  [
    { operation: 'resolve_push', resolution: cloudResolution, idempotency_key: 'cloud-decision' },
    outcome,
  ],
  [{ operation: 'resume_resolution', resolution_id: changeId }, outcome],
  [
    { operation: 'reconcile_resolution', resolution_id: changeId, reconciliation },
    { ...outcome, pending_reconciliation: false },
  ],
  [{ operation: 'resolution', resolution_id: changeId }, { record }],
  [{ operation: 'resolution_by_key', idempotency_key: 'cloud-decision' }, { record }],
  [{ operation: 'resolutions', limit: 10 }, { items: [record] }],
  [
    { operation: 'pending_resolutions', limit: 10 },
    { items: [record], next_before_resolution_id: null },
  ],
  [{ operation: 'reconciliation_context', resolution_id: changeId }, { context: cloudContext }],
];
export const envelope = (command, result, scope = nativeScope) => ({
  contract_version: '1.0.0',
  operation: command.operation,
  scope,
  result,
});
