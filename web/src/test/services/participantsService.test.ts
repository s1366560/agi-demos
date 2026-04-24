/**
 * participantsService tests — Track B P2-3 phase-2 (b-fe-roster).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  },
}));

import { httpClient } from '@/services/client/httpClient';
import { participantsService } from '@/services/participantsService';

describe('participantsService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('listRoster hits the relative /agent/conversations/.../participants path', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'c1',
      conversation_mode: 'multi_agent_shared',
      effective_mode: 'multi_agent_shared',
      participant_agents: ['agent-1'],
      participant_bindings: [
        {
          agent_id: 'agent-1',
          workspace_agent_id: 'binding-1',
          display_name: 'Agent One',
          label: null,
          is_active: true,
          source: 'workspace',
        },
      ],
      coordinator_agent_id: 'agent-1',
      focused_agent_id: null,
    });

    const roster = await participantsService.listRoster('c1');

    expect(httpClient.get).toHaveBeenCalledWith('/agent/conversations/c1/participants');
    expect(roster.participant_agents).toEqual(['agent-1']);
    expect(roster.participant_bindings[0]?.workspace_agent_id).toBe('binding-1');
  });

  it('addParticipant POSTs the add-participant payload', async () => {
    (httpClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'c1',
      conversation_mode: 'multi_agent_shared',
      effective_mode: 'multi_agent_shared',
      participant_agents: ['agent-1', 'agent-2'],
      participant_bindings: [],
      coordinator_agent_id: 'agent-1',
      focused_agent_id: null,
    });

    await participantsService.addParticipant('c1', {
      agent_id: 'agent-2',
      role: 'reviewer',
    });

    expect(httpClient.post).toHaveBeenCalledWith('/agent/conversations/c1/participants', {
      agent_id: 'agent-2',
      role: 'reviewer',
    });
  });

  it('removeParticipant encodes the agent_id and uses DELETE', async () => {
    (httpClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'c1',
      conversation_mode: 'multi_agent_shared',
      effective_mode: 'multi_agent_shared',
      participant_agents: [],
      participant_bindings: [],
      coordinator_agent_id: null,
      focused_agent_id: null,
    });

    await participantsService.removeParticipant('c1', 'agent/with/slash');

    expect(httpClient.delete).toHaveBeenCalledWith(
      '/agent/conversations/c1/participants/agent%2Fwith%2Fslash',
      undefined
    );
  });

  it('removeParticipant forwards a reason as the request body when provided', async () => {
    (httpClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'c1',
      conversation_mode: 'multi_agent_shared',
      effective_mode: 'multi_agent_shared',
      participant_agents: [],
      participant_bindings: [],
      coordinator_agent_id: null,
      focused_agent_id: null,
    });

    await participantsService.removeParticipant('c1', 'agent-2', {
      reason: 'Task reassigned',
    });

    expect(httpClient.delete).toHaveBeenCalledWith('/agent/conversations/c1/participants/agent-2', {
      data: { reason: 'Task reassigned' },
    });
  });

  it('listMentionCandidates returns binding-aware workspace candidates', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'c1',
      workspace_id: 'ws-1',
      source: 'workspace',
      candidates: [
        {
          agent_id: 'agent-1',
          workspace_agent_id: 'binding-1',
          display_name: 'Worker A',
          label: 'alpha',
          status: 'idle',
          is_active: true,
          source: 'workspace',
        },
      ],
    });

    const result = await participantsService.listMentionCandidates('c1');

    expect(httpClient.get).toHaveBeenCalledWith('/agent/conversations/c1/mention-candidates', {
      params: { include_inactive: false },
    });
    expect(result.candidates[0]?.workspace_agent_id).toBe('binding-1');
  });

  it('setFocusedAgent PATCHes the focused endpoint', async () => {
    (httpClient.patch as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'c1',
      conversation_mode: 'multi_agent_isolated',
      effective_mode: 'multi_agent_isolated',
      participant_agents: ['agent-1'],
      participant_bindings: [],
      coordinator_agent_id: null,
      focused_agent_id: 'agent-1',
    });

    await participantsService.setFocusedAgent('c1', 'agent-1');

    expect(httpClient.patch).toHaveBeenCalledWith(
      '/agent/conversations/c1/participants/focused',
      { agent_id: 'agent-1' }
    );
  });
});
