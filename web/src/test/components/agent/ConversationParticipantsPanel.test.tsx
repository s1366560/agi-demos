import { describe, expect, it, vi } from 'vitest';

import { render, screen } from '@/test/utils';
import { fireEvent } from '@testing-library/react';

const setFocusedAgent = vi.fn();
const rosterState = {
  conversation_id: 'c1',
  conversation_mode: 'multi_agent_shared',
  effective_mode: 'multi_agent_shared',
  participant_agents: ['agent-1'],
  participant_bindings: [
    {
      agent_id: 'agent-1',
      workspace_agent_id: 'binding-1',
      display_name: 'Worker A',
      label: null,
      is_active: true,
      source: 'workspace' as const,
    },
  ],
  coordinator_agent_id: 'agent-1',
  focused_agent_id: null as string | null,
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: unknown) => {
      if (opts && typeof opts === 'object' && 'defaultValue' in opts) {
        return (opts as { defaultValue: string }).defaultValue;
      }
      return typeof opts === 'string' ? opts : _key;
    },
  }),
}));

vi.mock('@/hooks/useConversationParticipants', () => ({
  useConversationParticipants: () => ({
    roster: rosterState,
    loading: false,
    error: null,
    refresh: vi.fn(),
    addParticipant: vi.fn(),
    removeParticipant: vi.fn(),
    setCoordinator: vi.fn(),
    setFocusedAgent,
  }),
}));

vi.mock('@/hooks/useMentionCandidates', () => ({
  useMentionCandidates: () => ({
    candidates: [],
  }),
}));

import { ConversationParticipantsPanel } from '@/components/agent/ConversationParticipantsPanel';

describe('ConversationParticipantsPanel', () => {
  it('renders participant display_name when binding projection is available', () => {
    rosterState.conversation_mode = 'multi_agent_shared';
    rosterState.effective_mode = 'multi_agent_shared';
    rosterState.coordinator_agent_id = 'agent-1';
    rosterState.focused_agent_id = null;
    render(<ConversationParticipantsPanel conversationId="c1" />);

    expect(screen.getByText('Worker A')).toBeInTheDocument();
    expect(screen.queryByText('agent-1')).not.toBeInTheDocument();
    expect(screen.getByText('workspace')).toBeInTheDocument();
  });

  it('allows setting the focused agent in isolated mode', async () => {
    vi.mocked(setFocusedAgent).mockResolvedValue(null);
    rosterState.conversation_mode = 'multi_agent_isolated';
    rosterState.effective_mode = 'multi_agent_isolated';
    rosterState.coordinator_agent_id = null;
    rosterState.focused_agent_id = null;

    render(<ConversationParticipantsPanel conversationId="c1" />);

    fireEvent.click(screen.getByRole('button', { name: /focused agent/i }));
    expect(setFocusedAgent).toHaveBeenCalledWith('agent-1');
  });
});
