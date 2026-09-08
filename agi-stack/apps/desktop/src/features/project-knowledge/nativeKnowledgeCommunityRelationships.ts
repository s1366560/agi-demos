/** Protocol relationships over the bounded community presentation responses. */
import type {
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingResultMap as Results,
  NativeKnowledgeProcessingCommandResultMap as Commands,
  NativeKnowledgeCommunityBuildReceipt,
  NativeKnowledgeCommunityBuildStatus,
  NativeKnowledgeCommunitySelection,
  NativeKnowledgeCommunityAuditSummary,
  NativeKnowledgeCommunityBuildPage,
  NativeKnowledgeCommunityCandidateProgress,
  NativeKnowledgeProcessingSource,
} from './nativeKnowledgeContracts';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import * as s from './nativeKnowledgeSchema';
import { sameJson } from './nativeKnowledgeRelationships';
import { validProcessingSource } from './nativeKnowledgeProcessingRelationships';

type CommunityOperation = Extract<
  NativeKnowledgeProcessingQuery | NativeKnowledgeProcessingCommand,
  {
    operation:
      | 'community_active'
      | 'community_build'
      | 'community_audit'
      | 'create_community_build'
      | 'select_community_build'
      | 'process_community_one'
      | 'retry_community'
      | 'activate_community_build';
  }
>;

const selection = (r: NativeKnowledgeCommunitySelection): boolean =>
  (r.requested_build_id === null || s.identifier(r.requested_build_id)) &&
  (r.active_build_id === null || s.identifier(r.active_build_id)) &&
  (r.revision === 0) === (r.requested_build_id === null) &&
  (r.requested_build_id !== null || r.active_build_id === null);

const build = (r: NativeKnowledgeCommunityBuildReceipt, scope: ProjectKnowledgeScope): boolean =>
  r.tenant_id === scope.tenantId &&
  r.project_id === scope.projectId &&
  s.identifier(r.build_id) &&
  (r.candidate_count === 0) === (r.state === 'completed_empty');

function status(r: NativeKnowledgeCommunityBuildStatus): boolean {
  const completed = r.ready_count + r.insufficient_evidence_count;
  if (!s.identifier(r.build_id) || completed + r.failed_count > r.candidate_count) return false;
  const expected =
    r.candidate_count === 0
      ? 'completed_empty'
      : r.failed_count > 0
        ? 'failed'
        : completed === r.candidate_count
          ? 'completed'
          : 'pending';
  return r.state === expected;
}

function audit(r: NativeKnowledgeCommunityAuditSummary): boolean {
  return (
    [r.build_id, r.agent_id, r.provider_id, r.model_id].every(s.identifier) &&
    (r.status === 'failed') === (r.failure !== null) &&
    (r.status === 'failed' || r.response_digest === null) &&
    (r.status === 'running'
      ? r.finished_at_ms === null && r.latency_ms === null
      : r.finished_at_ms !== null && r.latency_ms !== null && r.finished_at_ms >= r.started_at_ms)
  );
}

function candidate(
  item: NativeKnowledgeCommunityCandidateProgress,
  page: NativeKnowledgeCommunityBuildPage,
  scope: ProjectKnowledgeScope,
  sources: Map<string, NativeKnowledgeProcessingSource>,
  sequences: Map<number, NativeKnowledgeProcessingSource>,
  members: Set<string>,
): boolean {
  const { job, result, audit: record } = item;
  if (
    job.build_id !== page.build.build_id ||
    job.candidate_id !== item.candidate_id ||
    (job.state === 'failed') !== (job.failure !== null) ||
    (job.state !== 'pending' && job.attempt === 0) ||
    (job.state === 'completed') !== (result !== null)
  )
    return false;
  if (
    record !== null &&
    (!audit(record) ||
      record.build_id !== job.build_id ||
      record.candidate_id !== item.candidate_id ||
      record.attempt !== job.attempt ||
      (record.status === 'applied') !== (job.state === 'completed'))
  )
    return false;
  if (result === null) return true;
  const submission = result.submission;
  if (
    result.build_id !== job.build_id ||
    result.candidate_id !== item.candidate_id ||
    result.attempt !== job.attempt ||
    record === null ||
    result.finished_at_ms !== record.finished_at_ms ||
    submission.build_id !== job.build_id ||
    submission.candidate_id !== item.candidate_id ||
    submission.graph_digest !== page.build.graph_digest ||
    submission.members.length !== item.member_count
  )
    return false;
  for (const member of submission.members) {
    const source = member.source;
    const key = JSON.stringify([source.memory_id, member.entity_index]);
    if (
      !validProcessingSource(source, scope) ||
      members.has(key) ||
      (sources.has(source.memory_id) && !sameJson(sources.get(source.memory_id), source)) ||
      (sequences.has(source.change_sequence) &&
        !sameJson(sequences.get(source.change_sequence), source))
    )
      return false;
    members.add(key);
    sources.set(source.memory_id, source);
    sequences.set(source.change_sequence, source);
  }
  const decision = submission.decision;
  if (
    !decision.rationale.trim() ||
    (decision.status === 'ready' && (!decision.name.trim() || !decision.summary.trim()))
  )
    return false;
  // The snapshot is private. Relationship incidence and membership digests are
  // verified by the Rust authority; this response proves exact entity references.
  return decision.evidence.every(
    (e) =>
      validProcessingSource(e.source, scope) &&
      submission.members.some(
        (m) => m.entity_index === e.entity_index && sameJson(m.source, e.source),
      ),
  );
}

function pageValid(
  page: NativeKnowledgeCommunityBuildPage,
  query: Extract<CommunityOperation, { operation: 'community_build' }>,
  scope: ProjectKnowledgeScope,
): boolean {
  if (
    !build(page.build, scope) ||
    !status(page.status) ||
    page.build.build_id !== query.build_id ||
    page.status.build_id !== query.build_id ||
    page.status.candidate_count !== page.build.candidate_count ||
    page.total !== page.build.candidate_count ||
    page.offset !== query.offset ||
    page.limit !== query.limit ||
    page.items.length !== Math.min(page.limit, Math.max(0, page.total - page.offset))
  )
    return false;
  const sources = new Map<string, NativeKnowledgeProcessingSource>();
  const sequences = new Map<number, NativeKnowledgeProcessingSource>();
  const members = new Set<string>();
  const ids = new Set<string>();
  let ready = 0,
    insufficient = 0,
    failed = 0,
    pending = 0;
  for (const item of page.items) {
    if (ids.has(item.candidate_id) || !candidate(item, page, scope, sources, sequences, members))
      return false;
    ids.add(item.candidate_id);
    if (item.result?.submission.decision.status === 'ready') ready++;
    else if (item.result) insufficient++;
    else if (item.job.state === 'failed') failed++;
    else pending++;
  }
  const r = page.status;
  return (
    ready <= r.ready_count &&
    insufficient <= r.insufficient_evidence_count &&
    failed <= r.failed_count &&
    pending <= r.candidate_count - r.ready_count - r.insufficient_evidence_count - r.failed_count
  );
}

export function validCommunityResult(
  operation: CommunityOperation,
  value: unknown,
  scope: ProjectKnowledgeScope,
): boolean {
  switch (operation.operation) {
    case 'community_active': {
      const r = value as Results['community_active'];
      if (!selection(r.selection)) return false;
      const active = r.selection.active_build_id;
      if (active === null) return r.current_status === null && r.stale_build_id === null;
      if (r.stale_build_id !== null)
        return r.stale_build_id === active && r.current_status === null;
      return (
        r.current_status !== null &&
        status(r.current_status) &&
        r.current_status.build_id === active &&
        ['completed', 'completed_empty'].includes(r.current_status.state)
      );
    }
    case 'community_build': {
      const r = value as Results['community_build'];
      return r.page === null || pageValid(r.page, operation, scope);
    }
    case 'community_audit': {
      const r = (value as Results['community_audit']).audit;
      return (
        r === null ||
        (audit(r) &&
          r.build_id === operation.build_id &&
          r.candidate_id === operation.candidate_id &&
          r.attempt === operation.attempt)
      );
    }
    case 'create_community_build':
      return build((value as Commands['create_community_build']).build, scope);
    case 'select_community_build': {
      const r = (value as Commands['select_community_build']).selection;
      return (
        selection(r) &&
        r.requested_build_id === operation.build_id &&
        r.revision === operation.expected_selection_revision + 1
      );
    }
    case 'process_community_one': {
      const r = (value as Commands['process_community_one']).receipt;
      return (
        r === null || (audit(r) && r.build_id === operation.build_id && r.status !== 'running')
      );
    }
    case 'retry_community': {
      const r = value as Commands['retry_community'];
      return (
        r.build_id === operation.build_id &&
        r.candidate_id === operation.candidate_id &&
        r.attempt === operation.expected_attempt
      );
    }
    case 'activate_community_build': {
      const r = value as Commands['activate_community_build'];
      return (
        r.build_id === operation.build_id &&
        r.selection_revision === operation.expected_selection_revision
      );
    }
  }
}
