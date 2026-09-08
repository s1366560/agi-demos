/** Cross-field protocol facts layered over generated structural schemas. */
import type {
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingResultMap as Results,
  NativeKnowledgeProcessingCommandResultMap as Commands,
  NativeKnowledgeProcessingSource,
  NativeKnowledgeRetrievalCursor,
  NativeKnowledgeEmbeddingConfiguration,
  NativeKnowledgeProcessingCoverage,
  NativeKnowledgeIndexCoverage,
  NativeKnowledgeIndexSource,
} from './nativeKnowledgeContracts';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import * as s from './nativeKnowledgeSchema';
import { sameJson } from './nativeKnowledgeRelationships';
import { validCommunityResult } from './nativeKnowledgeCommunityRelationships';

type Query = Extract<
  NativeKnowledgeProcessingQuery,
  { operation: 'entities' | 'relationships' | 'text' }
>;
export function validProcessingSource(
  value: NativeKnowledgeProcessingSource,
  scope: ProjectKnowledgeScope,
): boolean {
  return (
    value.tenant_id === scope.tenantId &&
    value.project_id === scope.projectId &&
    s.identifier(value.memory_id) &&
    s.localRevision(value.revision) &&
    s.sequence(value.change_sequence)
  );
}
export function validProcessingCursor(
  cursor: NativeKnowledgeRetrievalCursor,
  query: Query,
  scope: ProjectKnowledgeScope,
): boolean {
  return (
    cursor.tenant_id === scope.tenantId &&
    cursor.project_id === scope.projectId &&
    cursor.kind === query.operation &&
    sameJson(cursor.source, query.request.source ?? null) &&
    cursor.literal === (query.operation === 'text' ? query.literal : null) &&
    s.integer(0, 4_294_967_295)(cursor.after.item_index) &&
    cursor.after.change_sequence > 0 &&
    cursor.after.change_sequence <= cursor.upper_change_sequence &&
    (query.operation !== 'text' || cursor.after.item_index === 0) &&
    (!cursor.source || validProcessingSource(cursor.source, scope))
  );
}
export const validProcessingIndexInput = (
  value: NativeKnowledgeIndexSource,
  scope: ProjectKnowledgeScope,
): boolean =>
  validProcessingSource(value.source, scope) &&
  s.localRevision(value.audit_attempt) &&
  /^[0-9a-f]{64}$/.test(value.input_digest);
const configuration = (value: NativeKnowledgeEmbeddingConfiguration): boolean =>
  [value.build_id, value.provider_id, value.model_id].every(s.identifier);
const coverage = (
  p: NativeKnowledgeProcessingCoverage,
  index: NativeKnowledgeIndexCoverage | null,
): boolean =>
  p.applied_sources + p.pending_sources + p.failed_sources === p.current_sources &&
  (index === null ||
    (index.current_sources === p.applied_sources &&
      index.completed_sources + index.failed_sources <= index.current_sources));

export function validProcessingResult(
  operation: NativeKnowledgeProcessingQuery | NativeKnowledgeProcessingCommand,
  value: unknown,
  scope: ProjectKnowledgeScope,
): boolean {
  switch (operation.operation) {
    case 'community_active':
    case 'community_builds':
    case 'community_build':
    case 'community_audit':
    case 'create_community_build':
    case 'select_community_build':
    case 'process_community_one':
    case 'retry_community':
    case 'activate_community_build':
      return validCommunityResult(operation, value, scope);
    case 'configuration': {
      const r = value as Results['configuration'];
      return (
        (r.configuration === null || configuration(r.configuration)) &&
        (r.active_build_id === null || s.identifier(r.active_build_id)) &&
        (r.configuration === null) === (r.index === null) &&
        coverage(r.processing, r.index)
      );
    }
    case 'semantic': {
      const r = value as Results['semantic'];
      return (
        configuration(r.configuration) &&
        r.configuration.build_id === operation.build_id &&
        r.configuration.revision === operation.config_revision &&
        coverage(r.processing, r.index) &&
        r.hits.length <= operation.limit &&
        r.hits.every(
          (hit, i, hits) =>
            validProcessingIndexInput(hit.input, scope) &&
            hit.score >= -1 &&
            hit.score <= 1 &&
            (i === 0 || hits[i - 1]!.score >= hit.score),
        ) &&
        new Set(r.hits.map((h) => h.input.source.memory_id)).size === r.hits.length
      );
    }
    case 'failed_processing':
    case 'failed_index':
    case 'processing_audits':
      return diagnosticPage(operation, value, scope);
    case 'entities':
    case 'relationships':
    case 'text':
      return page(operation, value, scope);
    case 'configure_embedding':
    case 'select_embedding': {
      const r = value as Commands['configure_embedding'];
      return (
        configuration(r.configuration) &&
        r.configuration.build_id === operation.build_id &&
        r.configuration.revision === (operation.expected_config_revision ?? 0) + 1 &&
        (operation.operation !== 'configure_embedding' ||
          (r.configuration.provider_id === operation.provider_id &&
            r.configuration.provider_revision === operation.provider_revision &&
            r.configuration.model_id === operation.model_id))
      );
    }
    case 'promote_index': {
      const r = value as Commands['promote_index'];
      return (
        configuration(r.configuration) &&
        r.configuration.build_id === operation.build_id &&
        r.configuration.revision === operation.config_revision &&
        r.active_build_id === operation.build_id
      );
    }
    case 'retry_processing': {
      const r = value as Commands['retry_processing'];
      return sameJson(r.source, operation.source) && r.attempt === operation.expected_attempt;
    }
    case 'processing_task': {
      const r = value as Results['processing_task'];
      return (
        sameJson(r.source, operation.source) &&
        r.current === (r.task !== null) &&
        (r.task === null ||
          ((r.task.state === 'failed') === (r.task.failure !== null) &&
            r.task.state !== 'superseded' &&
            (r.task.state === 'pending' || r.task.attempt > 0)))
      );
    }
    case 'retry_index': {
      const r = value as Commands['retry_index'];
      return sameJson(r.input, operation.input) && r.attempt === operation.expected_attempt;
    }
    case 'index_one': {
      const r = (value as Commands['index_one']).receipt;
      return (
        r === null ||
        (validProcessingIndexInput(r.input, scope) &&
          s.localRevision(r.attempt) &&
          (r.status === 'failed') === (r.failure !== null))
      );
    }
    case 'process_one': {
      const r = (value as Commands['process_one']).receipt;
      return (
        r === null ||
        (validProcessingSource(r.source, scope) &&
          s.localRevision(r.attempt) &&
          (r.status === 'failed') === (r.failure !== null))
      );
    }
  }
}

function page(query: Query, value: unknown, scope: ProjectKnowledgeScope): boolean {
  const result = value as Results['entities'] | Results['relationships'] | Results['text'];
  if (result.items.length > query.request.limit) return false;
  let previous = query.request.cursor?.after;
  const sources = new Map<string, NativeKnowledgeProcessingSource>();
  const sequences = new Map<number, NativeKnowledgeProcessingSource>();
  const positions: Array<{ change_sequence: number; item_index: number }> = [];
  for (const item of result.items) {
    const source = 'reference' in item ? item.reference.source : item.source;
    const index =
      'reference' in item
        ? item.reference.entity_index
        : 'relationship_index' in item
          ? item.relationship_index
          : 0;
    if (
      !s.integer(0, 4_294_967_295)(index) ||
      !validProcessingSource(source, scope) ||
      !s.localRevision(item.audit_attempt) ||
      (query.request.source && !sameJson(query.request.source, source))
    )
      return false;
    if (
      (sources.has(source.memory_id) && !sameJson(sources.get(source.memory_id), source)) ||
      (sequences.has(source.change_sequence) &&
        !sameJson(sequences.get(source.change_sequence), source))
    )
      return false;
    sources.set(source.memory_id, source);
    sequences.set(source.change_sequence, source);
    if (
      'relationship' in item &&
      (!sameJson(source, item.source_entity.source) ||
        !sameJson(source, item.target_entity.source) ||
        item.source_entity.entity_index !== item.relationship.source_index ||
        item.target_entity.entity_index !== item.relationship.target_index ||
        item.relationship.score < 0 ||
        item.relationship.score > 1)
    )
      return false;
    if (
      'title' in item &&
      query.operation === 'text' &&
      !item.title.includes(query.literal) &&
      !item.content.includes(query.literal)
    )
      return false;
    const position = {
      change_sequence: source.change_sequence,
      item_index: index,
    };
    if (
      previous &&
      (position.change_sequence < previous.change_sequence ||
        (position.change_sequence === previous.change_sequence &&
          position.item_index <= previous.item_index))
    )
      return false;
    if (query.request.cursor && source.change_sequence > query.request.cursor.upper_change_sequence)
      return false;
    positions.push(position);
    previous = position;
  }
  const cursor = result.next_cursor;
  return (
    cursor === null ||
    (result.items.length === query.request.limit &&
      validProcessingCursor(cursor, query, scope) &&
      sameJson(cursor.after, positions.at(-1)) &&
      (!query.request.cursor ||
        cursor.upper_change_sequence === query.request.cursor.upper_change_sequence))
  );
}

function diagnosticPage(
  query: Extract<
    NativeKnowledgeProcessingQuery,
    { operation: 'failed_processing' | 'failed_index' | 'processing_audits' }
  >,
  value: unknown,
  scope: ProjectKnowledgeScope,
): boolean {
  const result = value as
    | Results['failed_processing']
    | Results['failed_index']
    | Results['processing_audits'];
  if (
    result.items.length > query.request.limit ||
    (result.next_cursor !== null &&
      (result.items.length !== query.request.limit ||
        result.next_cursor.length === 0 ||
        result.next_cursor.length > 8192))
  )
    return false;
  let previous = 0;
  for (const item of result.items) {
    const source = 'input' in item ? item.input.source : item.source;
    const position =
      query.operation === 'processing_audits' ? item.attempt : source.change_sequence;
    if (
      !validProcessingSource(source, scope) ||
      !s.localRevision(item.attempt) ||
      position <= previous
    )
      return false;
    previous = position;
    if ('input' in item && !validProcessingIndexInput(item.input, scope)) return false;
    if (query.operation === 'processing_audits' && !sameJson(query.source, source)) return false;
    if (
      'status' in item &&
      (![item.agent_id, item.provider_id, item.model_id, item.tool_name].every(s.identifier) ||
        (item.status === 'running') !==
          (item.finished_at_ms === null && item.latency_ms === null) ||
        (item.status !== 'running' && (item.finished_at_ms === null || item.latency_ms === null)) ||
        (item.finished_at_ms !== null && item.finished_at_ms < item.started_at_ms) ||
        (item.status === 'failed') !== (item.failure !== null))
    )
      return false;
  }
  return true;
}
