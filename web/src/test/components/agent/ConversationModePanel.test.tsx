/**
 * Unit tests for ConversationModePanel (Track F — f-mode-toggle + f-goal-editor).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

const refresh = vi.fn().mockResolvedValue(undefined);
let mockRoster: { effective_mode: string } | null = { effective_mode: 'single_agent' };

vi.mock('@/hooks/useConversationParticipants', () => ({
  useConversationParticipants: () => ({
    roster: mockRoster,
    loading: false,
    error: null,
    refresh,
    addParticipant: vi.fn(),
    removeParticipant: vi.fn(),
  }),
}));

const updateConversationMode = vi.fn().mockResolvedValue({});
const getConversation = vi.fn().mockResolvedValue({ goal_contract: null });

vi.mock('@/services/agentService', () => ({
  agentService: {
    updateConversationMode: (...args: unknown[]) => updateConversationMode(...args),
    getConversation: (...args: unknown[]) => getConversation(...args),
  },
}));

import { ConversationModePanel } from '@/components/agent/ConversationModePanel';

describe('ConversationModePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRoster = { effective_mode: 'single_agent' };
  });

  it('renders the mode segmented control reflecting effective_mode from roster', () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    expect(screen.getByTestId('conversation-mode-panel')).toBeInTheDocument();
    expect(screen.getByText('Single')).toBeInTheDocument();
    expect(screen.getByText('Autonomous')).toBeInTheDocument();
  });

  it('PATCHes the new mode when operator clicks a non-autonomous option', async () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    fireEvent.click(screen.getByText('Shared'));
    await waitFor(() => {
      expect(updateConversationMode).toHaveBeenCalledWith('c1', 'p1', {
        conversation_mode: 'multi_agent_shared',
      });
    });
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it('opens the goal drawer instead of PATCHing when autonomous is picked', async () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    fireEvent.click(screen.getByText('Autonomous'));
    await waitFor(() => {
      expect(screen.getByTestId('goal-contract-drawer')).toBeInTheDocument();
    });
    expect(updateConversationMode).not.toHaveBeenCalled();
  });

  it('submits the goal_contract with conversation_mode=autonomous after user fills primary_goal', async () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    fireEvent.click(screen.getByText('Autonomous'));

    await screen.findByTestId('goal-contract-drawer');
    const textarea = document.querySelector(
      '[data-testid="goal-contract-drawer"] textarea'
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Ship the feature' } });
    fireEvent.click(screen.getByTestId('goal-contract-submit'));

    await waitFor(() => {
      expect(updateConversationMode).toHaveBeenCalledWith(
        'c1',
        'p1',
        expect.objectContaining({
          conversation_mode: 'autonomous',
          goal_contract: expect.objectContaining({
            primary_goal: 'Ship the feature',
            supervisor_tick_seconds: 120,
          }),
        })
      );
    });
  });

  it('blocks submission when primary_goal is empty (validation error)', async () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    fireEvent.click(screen.getByText('Autonomous'));
    await screen.findByTestId('goal-contract-drawer');
    fireEvent.click(screen.getByTestId('goal-contract-submit'));

    // Let microtasks / validation run
    await new Promise((r) => setTimeout(r, 50));
    expect(updateConversationMode).not.toHaveBeenCalled();
  });
});
