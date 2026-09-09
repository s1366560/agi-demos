import type * as K from './nativeKnowledgeContracts';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import * as s from './nativeKnowledgeSchema';

const sameRemote = (remote: K.NativeKnowledgeRemote | null, id: string): boolean =>
  remote === null || remote.memory_id === id;
const sameMemory = (
  memory: K.NativeKnowledgeMemory | null,
  id: string,
  scope: ProjectKnowledgeScope,
): boolean => memory === null || (memory.id === id && memory.project_id === scope.projectId);
const sameConflict = (c: K.NativeKnowledgePushConflict): boolean =>
  c.proposed.memory_id === c.memory_id &&
  sameRemote(c.current, c.memory_id) &&
  (!Object.hasOwn(c, 'observed_current') ||
    sameRemote(c.observed_current as K.NativeKnowledgeRemote | null, c.memory_id));
export function sameJson(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== 'object' || typeof right !== 'object')
    return false;
  if (Array.isArray(left) !== Array.isArray(right)) return false;
  const a = left as Record<string, unknown>,
    b = right as Record<string, unknown>;
  return (
    Object.keys(a).length === Object.keys(b).length &&
    Object.keys(a).every((key) => Object.hasOwn(b, key) && sameJson(a[key], b[key]))
  );
}
function context(
  c: K.NativeKnowledgeCloudContext | K.NativeKnowledgePullContext,
  scope: ProjectKnowledgeScope,
): boolean {
  if (
    !sameMemory(c.local, c.memory_id, scope) ||
    !sameRemote(c.remote, c.memory_id) ||
    !sameRemote(c.baseline, c.memory_id)
  )
    return false;
  if ('cloud_conflict' in c) {
    const { change_id: _change, ...proposed } = c.original_request;
    return (
      c.conflict_id === c.cloud_conflict.id &&
      c.memory_id === c.cloud_conflict.memory_id &&
      c.original_request.memory_id === c.memory_id &&
      sameConflict(c.cloud_conflict) &&
      sameJson(proposed, c.cloud_conflict.proposed)
    );
  }
  return true;
}
function receipt(
  r: K.NativeKnowledgeCloudReceipt,
  id: string,
  memoryId?: string,
  conflictId?: string,
): boolean {
  return (
    r.change_id === id &&
    (memoryId === undefined || sameRemote(r.version, memoryId)) &&
    (r.status !== 'resolved' || conflictId === undefined || r.conflict_id === conflictId)
  );
}
function record(r: K.NativeKnowledgeResolutionRecord, scope: ProjectKnowledgeScope): boolean {
  if (
    !context(r.archive, scope) ||
    r.local_sequence !== r.command.local_sequence ||
    r.local_sequence !== r.archive.local_sequence ||
    r.command.memory_id !== r.archive.memory_id ||
    r.command.conflict_id !== r.archive.conflict_id ||
    (r.receipt !== null &&
      !receipt(r.receipt, r.resolution_id, r.command.memory_id, r.command.conflict_id)) ||
    (r.receipt !== null && r.rejection !== null) ||
    (r.reconciliation !== null && r.receipt === null) ||
    (r.reconciliation === null) !== (r.reconciliation_command === null) ||
    (r.reconciliation === null) !== (r.reconciliation_archive === null) ||
    (r.reconciliation_archive !== null &&
      (!context(r.reconciliation_archive, scope) ||
        r.reconciliation_archive.local_sequence !== r.local_sequence ||
        r.reconciliation_archive.memory_id !== r.command.memory_id ||
        r.reconciliation_archive.conflict_id !== r.command.conflict_id))
  )
    return false;
  let request: unknown;
  try {
    request = JSON.parse(r.request_json) as unknown;
  } catch {
    return false;
  }
  return sameJson(request, {
    change_id: r.resolution_id,
    expected_current_revision: r.command.guard.expected_remote_revision,
    decision: r.command.choice.decision,
    content: r.command.choice.decision === 'merged' ? r.command.choice.content : null,
  });
}

function mutationMemoryMatches(
  actual: K.NativeKnowledgeStoredMemory,
  requested: K.NativeKnowledgeMutationMemory,
  version: number,
): boolean {
  // Rust stores embeddings as f32 and defaults omitted embeddings to null.
  return sameJson(
    { ...actual, embedding: actual.embedding?.map(Math.fround) ?? null },
    { ...requested, version, embedding: requested.embedding?.map(Math.fround) ?? null },
  );
}

/** Called only after the result's structural schema has succeeded. */
export function validNativeRelationships(
  c: K.NativeKnowledgeCommand,
  value: unknown,
  scope: ProjectKnowledgeScope,
): boolean {
  const result = value as K.NativeKnowledgeResultMap[keyof K.NativeKnowledgeResultMap];
  if ('limit' in c) {
    const items = (result as { items: readonly unknown[] }).items;
    if (items.length > c.limit) return false;
  }
  switch (c.operation) {
    case 'get':
      return sameMemory((result as K.NativeKnowledgeResultMap['get']).memory, c.id, scope);
    case 'create':
    case 'update': {
      const receipt = (result as K.NativeKnowledgeMutationResult).receipt;
      return (
        !receipt.deleted &&
        sameMemory(receipt.memory, c.memory.id, scope) &&
        mutationMemoryMatches(
          receipt.memory,
          c.memory,
          c.operation === 'create' ? 1 : c.expected_revision + 1,
        )
      );
    }
    case 'delete': {
      const receipt = (result as K.NativeKnowledgeMutationResult).receipt;
      return (
        receipt.deleted &&
        sameMemory(receipt.memory, c.id, scope) &&
        receipt.memory.version === c.expected_revision + 1
      );
    }
    case 'sync_status':
      return true;
    case 'sync_link':
      return sameJson((result as K.NativeKnowledgeResultMap['sync_link']).status.link, c.link);
    case 'sync_unbind': {
      const r = result as K.NativeKnowledgeResultMap['sync_unbind'];
      return r.policy === c.policy && r.status.link === null && r.status.pending_changes === 0;
    }
    case 'sync_push':
    case 'sync_pull':
      return true;
    case 'sync_outbox': {
      const r = result as K.NativeKnowledgeResultMap['sync_outbox'];
      const sequences = r.items.map((item) => item.local_change.sequence);
      return (
        s.sortedSequences(sequences) &&
        sequences.every((n) => n > c.after_sequence) &&
        r.next_sequence === (sequences.at(-1) ?? c.after_sequence) &&
        r.items.every((item) => item.local_change.memory.project_id === scope.projectId)
      );
    }
    case 'remote_baseline':
      return sameRemote((result as K.NativeKnowledgeResultMap['remote_baseline']).version, c.id);
    case 'push_conflicts': {
      const items = (result as K.NativeKnowledgeResultMap['push_conflicts']).items;
      return (
        new Set(items.map((item) => item.id)).size === items.length && items.every(sameConflict)
      );
    }
    case 'pull_conflicts': {
      const items = (result as K.NativeKnowledgeResultMap['pull_conflicts']).items;
      return (
        s.sortedSequences(items.map((item) => item.sequence)) &&
        items.every(
          (item) =>
            sameMemory(item.local, item.memory_id, scope) &&
            sameRemote(item.remote, item.memory_id) &&
            sameRemote(item.baseline, item.memory_id),
        )
      );
    }
    case 'graph_pull_conflicts':
    case 'graph_push_conflicts':
    case 'graph_resolution_history':
    case 'synced_graph_projections':
      return true;
    case 'graph_pull_conflict_context': {
      const r = (result as K.NativeKnowledgeResultMap['graph_pull_conflict_context'])
        .context as unknown as { object_id?: string } | null;
      return r === null || r.object_id === c.id;
    }
    case 'remote_graph_baseline':
      return true;
    case 'synced_graph_projection': {
      const r = (result as K.NativeKnowledgeResultMap['synced_graph_projection']).projection;
      return r === null || r.object_id === c.id;
    }
    case 'resolve_graph_pull': {
      const r = (result as K.NativeKnowledgeResultMap['resolve_graph_pull'])
        .receipt as unknown as {
          object_id?: string;
          conflict_sequences?: readonly number[];
          remote_baseline_revision?: number;
        };
      return (
        r.object_id === c.resolution.object_id &&
        sameJson(r.conflict_sequences, c.resolution.conflict_sequences) &&
        r.remote_baseline_revision === c.resolution.expected_remote_revision
      );
    }
    case 'resolve_graph_push': {
      const r = (result as K.NativeKnowledgeResultMap['resolve_graph_push'])
        .receipt as unknown as {
          status?: string;
          change_id?: string;
          conflict_id?: string;
        };
      return (
        r.status === 'resolved' &&
        r.change_id === c.change_id &&
        r.conflict_id === c.conflict_id
      );
    }
    case 'pull_conflict_context': {
      const r = (result as K.NativeKnowledgeResultMap['pull_conflict_context']).context;
      return r === null || (r.memory_id === c.id && context(r, scope));
    }
    case 'resolution_history':
      return (result as K.NativeKnowledgeResultMap['resolution_history']).items.every(
        (item) =>
          item.request.memory_id === c.id &&
          item.receipt.memory_id === c.id &&
          item.archive.memory_id === c.id &&
          context(item.archive, scope),
      );
    case 'resolve_pull': {
      const r = (result as K.NativeKnowledgeResultMap['resolve_pull']).receipt;
      return (
        r.memory_id === c.resolution.memory_id &&
        sameJson(r.conflict_sequences, c.resolution.conflict_sequences) &&
        r.local_revision === c.resolution.expected_local_revision + 1 &&
        r.remote_baseline_revision === c.resolution.expected_remote_revision &&
        (r.copy_memory_id !== null) === (c.resolution.choice.decision === 'keep_both')
      );
    }
    case 'cloud_conflict_context': {
      const r = (result as K.NativeKnowledgeResultMap['cloud_conflict_context']).context;
      return r.local_sequence === c.local_sequence && context(r, scope);
    }
    case 'reconciliation_context':
      return context(
        (result as K.NativeKnowledgeResultMap['reconciliation_context']).context,
        scope,
      );
    case 'resolve_push':
    case 'resume_resolution':
    case 'reconcile_resolution': {
      const r = result as K.NativeKnowledgeCloudOutcome;
      if (c.operation === 'resolve_push') {
        const decision = c.resolution.choice;
        if (decision.decision === 'keep_current' || decision.decision === 'keep_both') {
          if (
            r.receipt.status !== 'resolved' ||
            (r.receipt.version?.revision ?? 0) !==
              c.resolution.guard.expected_remote_revision ||
            (decision.decision === 'keep_both') !== Object.hasOwn(r.receipt, 'copy_memory_id')
          )
            return false;
        } else if (
          r.receipt.status !== 'applied' ||
          r.receipt.version.revision !== c.resolution.guard.expected_remote_revision + 1 ||
          (decision.decision === 'merged' &&
            (r.receipt.version.deleted || !sameJson(r.receipt.version.content, decision.content)))
        )
          return false;
      }
      if (c.operation === 'reconcile_resolution' && r.pending_reconciliation) return false;
      return (
        receipt(
          r.receipt,
          r.resolution_id,
          c.operation === 'resolve_push' ? c.resolution.memory_id : undefined,
          c.operation === 'resolve_push' ? c.resolution.conflict_id : undefined,
        ) &&
        (c.operation === 'resolve_push' || r.resolution_id === c.resolution_id)
      );
    }
    case 'resolution':
    case 'resolution_by_key': {
      const r = (result as K.NativeKnowledgeResultMap['resolution_by_key']).record;
      return r === null
        ? c.operation === 'resolution_by_key'
        : record(r, scope) &&
            (c.operation === 'resolution_by_key' || r.resolution_id === c.resolution_id);
    }
    case 'resolutions':
    case 'pending_resolutions': {
      const r = result as K.NativeKnowledgeResultMap['pending_resolutions'];
      if (
        new Set(r.items.map((item) => item.resolution_id)).size !== r.items.length ||
        !r.items.every((item) => record(item, scope))
      )
        return false;
      if (c.operation === 'resolutions') return true;
      return (
        r.items.every((item) => item.rejection === null && item.reconciliation === null) &&
        (r.next_before_resolution_id === null ||
          (r.items.length === c.limit &&
            r.next_before_resolution_id === r.items.at(-1)?.resolution_id))
      );
    }
  }
}
