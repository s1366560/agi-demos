/**
 * Unit tests for ConversationModePanel (mode-picker only after G1).
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
const getConversation = vi.fn().mockResolvedValue({
  id: 'c1',
  workspace_id: null,
  linked_workspace_task_id: null,
});
const listTasks = vi.fn().mockResolvedValue([]);

vi.mock('@/services/agentService', () => ({
  agentService: {
    updateConversationMode: (...args: unknown[]) => updateConversationMode(...args),
  },
}));

vi.mock('@/services/agent/restApi', () => ({
  restApi: {
    getConversation: (...args: unknown[]) => getConversation(...args),
  },
}));

vi.mock('@/services/workspaceService', () => ({
  workspaceTaskService: {
    list: (...args: unknown[]) => listTasks(...args),
  },
}));

import { ConversationModePanel } from '@/components/agent/ConversationModePanel';

describe('ConversationModePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRoster = { effective_mode: 'single_agent' };
    getConversation.mockResolvedValue({
      id: 'c1',
      workspace_id: null,
      linked_workspace_task_id: null,
    });
    listTasks.mockResolvedValue([]);
  });

  it('renders the mode segmented control reflecting effective_mode from roster', () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    expect(screen.getByTestId('conversation-mode-panel')).toBeInTheDocument();
    expect(screen.getByText('Single')).toBeInTheDocument();
    expect(screen.getByText('Autonomous')).toBeInTheDocument();
  });

  it('PATCHes the new mode when operator picks a non-autonomous option', async () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    fireEvent.click(screen.getByText('Shared'));
    await waitFor(() => {
      expect(updateConversationMode).toHaveBeenCalledWith('c1', 'p1', {
        conversation_mode: 'multi_agent_shared',
      });
    });
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it('PATCHes autonomous mode directly (no goal-contract drawer after G1)', async () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    fireEvent.click(screen.getByText('Autonomous'));
    await waitFor(() => {
      expect(updateConversationMode).toHaveBeenCalledWith('c1', 'p1', {
        conversation_mode: 'autonomous',
      });
    });
  });

  it('ignores clicks on the already-active mode', async () => {
    render(<ConversationModePanel conversationId="c1" projectId="p1" />);
    fireEvent.click(screen.getByText('Single'));
    await new Promise((r) => setTimeout(r, 20));
    expect(updateConversationMode).not.toHaveBeenCalled();
  });

  it('renders the workspace-task picker in autonomous mode when conversation.workspace_id is set', async () => {
    mockRoster = { effective_mode: 'autonomous' };
    getConversation.mockResolvedValue({
      id: 'c1',
      workspace_id: 'ws1',
      linked_workspace_task_id: null,
    });
    listTasks.mockResolvedValue([
      { id: 't1', title: 'Ship rollout', status: 'in_progress' },
      { id: 't2', title: 'Audit logs', status: 'open' },
    ]);

    render(<ConversationModePanel conversationId="c1" projectId="p1" />);

    await waitFor(() => {
      expect(listTasks).toHaveBeenCalledWith('ws1');
    });
    await waitFor(() => {
      expect(screen.getByTestId('conversation-task-picker')).toBeInTheDocument();
    });
  });

  it('does not render the task picker when workspace_id is absent', async () => {
    mockRoster = { effective_mode: 'autonomous' };
    getConversation.mockResolvedValue({
      id: 'c1',
      workspace_id: null,
      linked_workspace_task_id: null,
    });

    render(<ConversationModePanel conversationId="c1" projectId="p1" />);

    await waitFor(() => expect(getConversation).toHaveBeenCalled());
    expect(screen.queryByTestId('conversation-task-picker')).not.toBeInTheDocument();
    expect(listTasks).not.toHaveBeenCalled();
  });
});
