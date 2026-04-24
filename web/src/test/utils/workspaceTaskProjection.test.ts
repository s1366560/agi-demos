import { describe, expect, it } from 'vitest';

import {
  getPendingLeaderAdjudicationSummary,
  getPendingLeaderAdjudicationProjection,
  getTaskAttemptConversationId,
  getTaskAttemptNumber,
  getTaskAttemptWorkerAgentId,
  getTaskAttemptWorkerBindingId,
  hasPendingLeaderAdjudication,
} from '@/utils/workspaceTaskProjection';

describe('workspaceTaskProjection', () => {
  it('prefers explicit attempt projection fields over metadata fallbacks', () => {
    const task = {
      metadata: {
        current_attempt_conversation_id: 'conv-fallback',
        current_attempt_number: 2,
        current_attempt_worker_binding_id: 'binding-fallback',
        current_attempt_worker_agent_id: 'agent-fallback',
      },
      current_attempt_conversation_id: 'conv-explicit',
      current_attempt_number: 3,
      current_attempt_worker_binding_id: 'binding-explicit',
      current_attempt_worker_agent_id: 'agent-explicit',
    } as any;

    expect(getTaskAttemptConversationId(task)).toBe('conv-explicit');
    expect(getTaskAttemptNumber(task)).toBe(3);
    expect(getTaskAttemptWorkerBindingId(task)).toBe('binding-explicit');
    expect(getTaskAttemptWorkerAgentId(task)).toBe('agent-explicit');
  });

  it('falls back to metadata projections and derives pending adjudication details', () => {
    const task = {
      metadata: {
        pending_leader_adjudication: true,
        current_attempt_conversation_id: 'conv-fallback',
        current_attempt_number: 7,
        current_attempt_worker_binding_id: 'binding-fallback',
        current_attempt_worker_agent_id: 'agent-fallback',
        last_worker_report_type: 'completed',
        last_worker_report_summary: 'Worker finished the run',
        last_worker_report_artifacts: ['artifact:summary', '', 42],
        last_worker_report_verifications: ['check:1', null],
      },
    } as any;

    expect(hasPendingLeaderAdjudication(task)).toBe(true);
    expect(getTaskAttemptConversationId(task)).toBe('conv-fallback');
    expect(getTaskAttemptNumber(task)).toBe(7);
    expect(getTaskAttemptWorkerBindingId(task)).toBe('binding-fallback');
    expect(getTaskAttemptWorkerAgentId(task)).toBe('agent-fallback');
    expect(getPendingLeaderAdjudicationProjection(task)).toEqual({
      pending: true,
      reportType: 'completed',
      reportSummary: 'Worker finished the run',
      reportArtifacts: ['artifact:summary'],
      reportVerifications: ['check:1'],
    });
  });

  it('prefers explicit worker report projections over metadata copies', () => {
    const task = {
      pending_leader_adjudication: true,
      last_worker_report_type: 'blocked',
      last_worker_report_summary: 'Explicit summary',
      last_worker_report_artifacts: ['artifact:explicit'],
      last_worker_report_verifications: ['verification:explicit'],
      metadata: {
        last_worker_report_type: 'completed',
        last_worker_report_summary: 'Fallback summary',
        last_worker_report_artifacts: ['artifact:fallback'],
        last_worker_report_verifications: ['verification:fallback'],
      },
    } as any;

    expect(getPendingLeaderAdjudicationProjection(task)).toEqual({
      pending: true,
      reportType: 'blocked',
      reportSummary: 'Explicit summary',
      reportArtifacts: ['artifact:explicit'],
      reportVerifications: ['verification:explicit'],
    });
  });

  it('builds a normalized adjudication summary with worker label and attempt fields', () => {
    const task = {
      pending_leader_adjudication: true,
      current_attempt_conversation_id: 'conv-9',
      current_attempt_number: 9,
      current_attempt_worker_binding_id: 'binding-1',
      last_worker_report_type: 'needs_review',
      metadata: {},
    } as any;
    const agents = [
      {
        id: 'binding-1',
        agent_id: 'agent-1',
        display_name: 'Worker A',
      },
    ] as any;

    expect(getPendingLeaderAdjudicationSummary(task, agents)).toEqual({
      pending: true,
      reportType: 'needs_review',
      reportTypeLabel: 'needs review',
      reportSummary: '',
      reportArtifacts: [],
      reportVerifications: [],
      attemptConversationId: 'conv-9',
      attemptNumber: 9,
      workerLabel: 'Worker A',
    });
  });
});
