import type { AgentConversation, DesktopRun, RuntimeMode } from '../../types';
import type { SubAgentTimelineGroup } from './subagentTimelineGroupModel';

export type SubAgentControlAuthority = {
  availability: 'available' | 'unavailable';
  reasonCode: string | null;
  allowedActions: readonly ('steer' | 'kill_run')[];
  authorityRevision: number | null;
  conversationId: string | null;
  participantAgentIds: readonly string[];
};

export type SubAgentGroupControlAvailability = {
  available: boolean;
  reasonCode: string | null;
  allowedActions: readonly ('steer' | 'kill_run')[];
};

export function resolveSubAgentControlAuthority(
  mode: RuntimeMode,
  conversation: AgentConversation | null,
  run: DesktopRun | null,
): SubAgentControlAuthority {
  const participantAgentIds = conversation?.participant_agents ?? [];
  if (mode !== 'cloud') {
    return unavailableAuthority(
      'subagent_control_local_unavailable',
      participantAgentIds,
    );
  }
  if (!conversation) {
    return unavailableAuthority(
      'subagent_control_conversation_unavailable',
      participantAgentIds,
    );
  }
  if (!run || run.conversation_id !== conversation.id) {
    return unavailableAuthority(
      'subagent_control_run_unavailable',
      participantAgentIds,
    );
  }
  if (run.status !== 'running' && run.status !== 'queued') {
    return unavailableAuthority(
      'subagent_control_run_terminal',
      participantAgentIds,
      run.revision,
    );
  }
  return {
    availability: 'available',
    reasonCode: null,
    allowedActions:
      run.status === 'running' ? ['steer', 'kill_run'] : ['kill_run'],
    authorityRevision: run.revision,
    conversationId: conversation.id,
    participantAgentIds,
  };
}

export function subAgentGroupControlAvailability(
  authority: SubAgentControlAuthority,
  group: SubAgentTimelineGroup,
): SubAgentGroupControlAvailability {
  if (authority.availability !== 'available') {
    return {
      available: false,
      reasonCode: authority.reasonCode,
      allowedActions: [],
    };
  }
  if (!group.runId) {
    return {
      available: false,
      reasonCode: 'subagent_control_execution_id_unavailable',
      allowedActions: [],
    };
  }
  if (
    !group.subagentId ||
    !authority.participantAgentIds.includes(group.subagentId)
  ) {
    return {
      available: false,
      reasonCode: 'subagent_control_roster_denied',
      allowedActions: [],
    };
  }
  if (!['running', 'steered', 'queued', 'background'].includes(group.status)) {
    return {
      available: false,
      reasonCode: 'subagent_control_execution_terminal',
      allowedActions: [],
    };
  }
  const allowedActions = authority.allowedActions.filter(
    (action) =>
      action !== 'steer' ||
      group.status === 'running' ||
      group.status === 'steered',
  );
  return {
    available: allowedActions.length > 0,
    reasonCode:
      allowedActions.length > 0 ? null : 'subagent_control_action_not_allowed',
    allowedActions,
  };
}

function unavailableAuthority(
  reasonCode: string,
  participantAgentIds: readonly string[],
  authorityRevision: number | null = null,
): SubAgentControlAuthority {
  return {
    availability: 'unavailable',
    reasonCode,
    allowedActions: [],
    authorityRevision,
    conversationId: null,
    participantAgentIds,
  };
}
