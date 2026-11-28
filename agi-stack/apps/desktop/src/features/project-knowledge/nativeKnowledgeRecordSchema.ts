import { isNativeKnowledgeMetadata } from './nativeKnowledgeMetadata';
import * as s from './nativeKnowledgeSchema';

const embedding = s.nullable(
  s.array((value) => typeof value === 'number' && Number.isFinite(Math.fround(value))),
);
const storedMemoryFields = {
  id: s.identifier,
  project_id: s.identifier,
  title: s.text,
  content: s.text,
  author_id: s.identifier,
  content_type: s.text,
  tags: s.array(s.text),
  metadata: isNativeKnowledgeMetadata,
  entities: s.array(s.object({ name: s.text, kind: s.text })),
  version: s.localRevision,
  status: s.text,
  created_at_ms: s.integer(-Number.MAX_SAFE_INTEGER),
};
export const mutationMemory = s.object(storedMemoryFields, { embedding });
export const storedMemory = s.object({ ...storedMemoryFields, embedding });
export const mutationResult = s.object({
  receipt: s.object({ sequence: s.sequence, memory: storedMemory, deleted: s.bool }),
  replayed: s.bool,
  processing_status: s.literal('accepted'),
});

export const link = s.object({
  remote_tenant_id: s.identifier,
  remote_project_id: s.identifier,
  remote_actor_id: s.identifier,
});
export const status = s.object({
  replica_id: s.uuid,
  link: s.nullable(link),
  pending_changes: s.integer(),
  pending_graph_changes: s.integer(),
});
export const content = s.object({
  title: (v) => s.identifier(v) && [...String(v)].length <= 500,
  content: (v) => typeof v === 'string' && new TextEncoder().encode(v).length <= 1_048_576,
  content_type: s.literal('text', 'document', 'image', 'video'),
  tags: s.array(s.identifier, 100),
  metadata: isNativeKnowledgeMetadata,
  status: s.literal('ENABLED', 'DISABLED'),
});
export const memory = s.object({
  id: s.identifier,
  project_id: s.identifier,
  title: s.identifier,
  content: s.text,
  author_id: s.identifier,
  content_type: s.identifier,
  tags: s.array(s.text),
  metadata: isNativeKnowledgeMetadata,
  entities: s.array(s.jsonValue),
  version: s.localRevision,
  status: s.identifier,
  created_at_ms: s.integer(-Number.MAX_SAFE_INTEGER),
  embedding: s.nullable(s.array((v) => typeof v === 'number' && Number.isFinite(v))),
});
export const remote = s.object(
  {
    memory_id: s.identifier,
    revision: s.integer(1, 2_147_483_647),
    deleted: s.bool,
    author_id: s.identifier,
    created_at_ms: s.integer(-Number.MAX_SAFE_INTEGER),
    content,
  },
  {},
  true,
);
export const proposal = s.object(
  {
    memory_id: s.identifier,
    operation: s.literal('create', 'update', 'delete'),
    expected_revision: s.remoteRevision,
    content: s.nullable(content),
  },
  { change_id: s.uuid },
  true,
);
export const pushConflict = s.object(
  {
    id: s.uuid,
    memory_id: s.identifier,
    proposed: proposal,
    current: s.nullable(remote),
    resolved_change_id: s.nullable(s.uuid),
  },
  { observed_current: s.nullable(remote) },
  true,
);
export const pullConflict = s.object({
  sequence: s.sequence,
  memory_id: s.identifier,
  remote,
  local: s.nullable(memory),
  local_deleted: s.bool,
  baseline: s.nullable(remote),
});
export const guardShape = {
  expected_local_revision: s.localRevision,
  expected_remote_revision: s.remoteRevision,
  expected_baseline_revision: s.remoteRevision,
  conflict_sequences: s.sortedSequences,
};
export const guard = s.object(guardShape);
export const localChoice: s.NativeCheck = (v) =>
  s.object({ decision: s.literal('use_local', 'use_remote', 'keep_both') })(v) ||
  s.object({ decision: s.literal('merged'), content })(v);
export const cloudChoice: s.NativeCheck = (v) =>
  s.object({ decision: s.literal('keep_current', 'use_proposed', 'keep_both') })(v) ||
  s.object({ decision: s.literal('merged'), content })(v);
const graphEntity = s.object({ name: s.identifier, kind: s.identifier });
const graphRelationship = s.object({
  source_index: s.integer(),
  target_index: s.integer(),
  relation_type: s.identifier,
  fact: (v) => typeof v === 'string' && v.trim().length > 0,
  score: (v) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1,
});
export const graphContent = s.object({
  source_revision: s.integer(1, 2_147_483_646),
  change_sequence: s.sequence,
  audit_attempt: s.integer(1, 2_147_483_646),
  entities: s.array(graphEntity, 200),
  relationships: s.array(graphRelationship, 500),
});
export const graphLocalChoice: s.NativeCheck = (v) =>
  s.object({ decision: s.literal('use_local', 'use_remote', 'keep_both') })(v) ||
  s.object({ decision: s.literal('merged'), content: graphContent })(v);
export const graphPullResolution: s.NativeCheck = (v) =>
  s.object({ ...guardShape, object_id: s.identifier, choice: graphLocalChoice })(v) &&
  Number((v as Record<string, unknown>).expected_remote_revision) > 0 &&
  ((v as Record<string, unknown>).conflict_sequences as number[]).length > 0;
export const syncedGraphProjection = s.object({
  object_id: s.identifier,
  revision: s.integer(1, 2_147_483_647),
  deleted: s.bool,
  author_id: s.identifier,
  created_at_ms: s.integer(),
  content: graphContent,
  source_available: s.bool,
  source_current: s.bool,
});
export const pullResolution: s.NativeCheck = (v) =>
  s.object({ ...guardShape, memory_id: s.identifier, choice: localChoice })(v) &&
  Number((v as Record<string, unknown>).expected_remote_revision) > 0 &&
  ((v as Record<string, unknown>).conflict_sequences as number[]).length > 0;
export const cloudResolution = s.object({
  local_sequence: s.sequence,
  memory_id: s.identifier,
  conflict_id: s.uuid,
  guard,
  choice: cloudChoice,
});
export const reconciliation = s.object({ guard, choice: localChoice });
export const pullContext = s.object({
  memory_id: s.identifier,
  conflict_sequences: s.sortedSequences,
  local: memory,
  local_deleted: s.bool,
  local_metadata: s.jsonObject,
  baseline: s.nullable(remote),
  remote,
});
export const cloudContext = s.object({
  local_sequence: s.sequence,
  memory_id: s.identifier,
  conflict_id: s.uuid,
  original_request: (v) => proposal(v) && s.uuid((v as Record<string, unknown>).change_id),
  cloud_conflict: pushConflict,
  local: memory,
  local_deleted: s.bool,
  local_metadata: s.jsonObject,
  baseline: s.nullable(remote),
  remote: s.nullable(remote),
  conflict_sequences: s.sortedSequences,
  pending_sequences: s.sortedSequences,
  observed_cursor: s.integer(),
});
const receiptShape = {
  local_revision: s.localRevision,
  copy_memory_id: s.nullable(s.identifier),
  processing_sequences: s.sequenceList,
  pending_push_sequences: s.sequenceList,
  superseded_sequences: s.sequenceList,
  conflict_sequences: s.sequenceList,
};
export const localReceipt = s.object({
  ...receiptShape,
  resolution_id: s.uuid,
  memory_id: s.identifier,
  remote_baseline_revision: s.remoteRevision,
});
export const reconciliationReceipt = s.object(receiptShape);
export const appliedReceipt = s.object(
  { status: s.literal('applied'), change_id: s.uuid, sequence: s.sequence, version: remote },
  {},
  true,
);
const resolvedReceipt = s.object(
  {
    status: s.literal('resolved'),
    change_id: s.uuid,
    conflict_id: s.uuid,
    version: s.nullable(remote),
  },
  {},
  true,
);
const copyVersion: s.NativeCheck = (v) =>
  remote(v) &&
  (v as Record<string, unknown>).revision === 1 &&
  (v as Record<string, unknown>).deleted === false;
/** Keep-both resolution: the cloud object is untouched and the pushed version
 * survives as a fresh copy whose creation advances the journal. */
const keepBothReceipt: s.NativeCheck = (v) =>
  s.object(
    {
      status: s.literal('resolved'),
      change_id: s.uuid,
      conflict_id: s.uuid,
      version: s.nullable(remote),
      sequence: s.sequence,
      copy_memory_id: s.identifier,
      copy_version: copyVersion,
    },
    {},
    true,
  )(v) &&
  (v as Record<string, unknown>).copy_memory_id ===
    ((v as Record<string, unknown>).copy_version as Record<string, unknown>).memory_id;
export const cloudReceipt: s.NativeCheck = (v) =>
  appliedReceipt(v) ||
  keepBothReceipt(v) ||
  (resolvedReceipt(v) &&
    !Object.hasOwn(v as object, 'sequence') &&
    !Object.hasOwn(v as object, 'copy_memory_id'));
export const pushReceipt: s.NativeCheck = (v) =>
  appliedReceipt(v) ||
  s.object({ status: s.literal('conflict'), change_id: s.uuid, conflict_id: s.uuid }, {}, true)(v);
export const cloudOutcome = s.object({
  resolution_id: s.uuid,
  receipt: cloudReceipt,
  pending_reconciliation: s.bool,
  replayed: s.bool,
});
export const resolutionRecord = s.object({
  resolution_id: s.uuid,
  local_sequence: s.sequence,
  request_json: s.text,
  command: cloudResolution,
  archive: cloudContext,
  receipt: s.nullable(cloudReceipt),
  rejection: s.nullable(
    s.object(
      { detail: s.object({ code: s.literal('knowledge_sync_resolution_stale') }, {}, true) },
      {},
      true,
    ),
  ),
  reconciliation: s.nullable(reconciliationReceipt),
  reconciliation_command: s.nullable(
    (value) => reconciliation(value) || s.object({ source: s.literal('cloud_receipt') })(value),
  ),
  reconciliation_archive: s.nullable(cloudContext),
});
