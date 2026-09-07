import type { NativeKnowledgeOperation } from './nativeKnowledgeContracts';
import * as s from './nativeKnowledgeSchema';
import * as r from './nativeKnowledgeRecordSchema';
const command = (
  operation: NativeKnowledgeOperation,
  fields: s.NativeShape = {},
  optional: s.NativeShape = {},
): s.NativeCheck => s.object({ operation: s.literal(operation), ...fields }, optional);
const limit = s.integer(1, 200);
export const commands: Readonly<Record<NativeKnowledgeOperation, s.NativeCheck>> = Object.freeze({
  sync_status: command('sync_status'),
  sync_link: command('sync_link', { link: r.link }),
  sync_push: command('sync_push'),
  sync_pull: command('sync_pull'),
  sync_outbox: command('sync_outbox', { after_sequence: s.integer(), limit }),
  remote_baseline: command('remote_baseline', { id: s.identifier }),
  push_conflicts: command('push_conflicts', { limit }),
  pull_conflicts: command('pull_conflicts', { limit }),
  pull_conflict_context: command('pull_conflict_context', { id: s.identifier }),
  resolution_history: command('resolution_history', { id: s.identifier, limit }),
  resolve_pull: command('resolve_pull', {
    resolution: r.pullResolution,
    idempotency_key: s.idempotencyKey,
  }),
  cloud_conflict_context: command('cloud_conflict_context', { local_sequence: s.sequence }),
  resolve_push: command('resolve_push', {
    resolution: r.cloudResolution,
    idempotency_key: s.idempotencyKey,
  }),
  resume_resolution: command('resume_resolution', { resolution_id: s.uuid }),
  reconcile_resolution: command('reconcile_resolution', {
    resolution_id: s.uuid,
    reconciliation: r.reconciliation,
  }),
  resolution: command('resolution', { resolution_id: s.uuid }),
  resolution_by_key: command('resolution_by_key', { idempotency_key: s.idempotencyKey }),
  resolutions: command('resolutions', { limit }),
  pending_resolutions: command(
    'pending_resolutions',
    { limit },
    { before_resolution_id: s.nullable(s.uuid) },
  ),
  reconciliation_context: command('reconciliation_context', { resolution_id: s.uuid }),
});
export const results: Readonly<Record<NativeKnowledgeOperation, s.NativeCheck>> = Object.freeze({
  sync_status: s.object({ status: r.status }),
  sync_link: s.object({
    status: r.status,
    association_state: s.literal('configured'),
    remote_authorization: s.literal('unverified'),
  }),
  sync_push: s.nullable(
    s.object({ local_sequence: s.sequence, replayed: s.bool, receipt: r.pushReceipt }),
  ),
  sync_pull: s.object({
    next_cursor: s.integer(),
    applied: s.integer(),
    conflicts: s.integer(),
    has_more: s.bool,
  }),
  sync_outbox: s.object({
    items: s.array(
      s.object({
        change_id: s.uuid,
        local_change: s.object({ sequence: s.sequence, memory: r.memory, deleted: s.bool }),
      }),
    ),
    next_sequence: s.integer(),
  }),
  remote_baseline: s.object({ version: s.nullable(r.remote) }),
  push_conflicts: s.object({ items: s.array(r.pushConflict) }),
  pull_conflicts: s.object({ items: s.array(r.pullConflict) }),
  pull_conflict_context: s.object({ context: s.nullable(r.pullContext) }),
  resolution_history: s.object({
    items: s.array(
      s.object({ request: r.pullResolution, receipt: r.localReceipt, archive: r.pullContext }),
    ),
  }),
  resolve_pull: s.object({ receipt: r.localReceipt, replayed: s.bool }),
  cloud_conflict_context: s.object({ context: r.cloudContext }),
  resolve_push: r.cloudOutcome,
  resume_resolution: r.cloudOutcome,
  reconcile_resolution: r.cloudOutcome,
  resolution: s.object({ record: r.resolutionRecord }),
  resolution_by_key: s.object({ record: s.nullable(r.resolutionRecord) }),
  resolutions: s.object({ items: s.array(r.resolutionRecord) }),
  pending_resolutions: s.object({
    items: s.array(r.resolutionRecord),
    next_before_resolution_id: s.nullable(s.uuid),
  }),
  reconciliation_context: s.object({ context: r.cloudContext }),
});
