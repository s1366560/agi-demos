/**
 * Unit tests for ConversationRosterSection — blackboard-embedded roster.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

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

const listConversations = vi.fn();
vi.mock('@/services/agentService', () => ({
  agentService: {
    listConversations: (...args: unknown[]) => listConversations(...args),
  },
}));

vi.mock('@/components/agent/ConversationModePanel', () => ({
  ConversationModePanel: ({ conversationId }: { conversationId: string }) => (
    <div data-testid={`mode-panel-${conversationId}`} />
  ),
}));

vi.mock('@/components/agent/ConversationParticipantsPanel', () => ({
  ConversationParticipantsPanel: ({ conversationId }: { conversationId: string }) => (
    <div data-testid={`inner-panel-${conversationId}`} />
  ),
}));

vi.mock('@/components/agent/HITLCenterPanel', () => ({
  HITLCenterPanel: ({ conversationId }: { conversationId: string | null }) => (
    <div data-testid={`hitl-panel-${conversationId ?? 'none'}`} />
  ),
}));

import { ConversationRosterSection } from '@/components/blackboard/tabs/ConversationRosterSection';

const renderAt = (search = '') =>
  render(
    <MemoryRouter initialEntries={[`/?${search}`]}>
      <ConversationRosterSection projectId="p1" workspaceId="ws1" />
    </MemoryRouter>
  );

describe('ConversationRosterSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('filters conversations by workspace_id', async () => {
    listConversations.mockResolvedValue({
      items: [
        { id: 'c1', title: 'In WS', workspace_id: 'ws1', updated_at: '2025-01-02' },
        { id: 'c2', title: 'Other WS', workspace_id: 'ws2', updated_at: '2025-01-01' },
      ],
    });

    renderAt();

    await waitFor(() => expect(listConversations).toHaveBeenCalled());
    expect(await screen.findByText('In WS')).toBeInTheDocument();
    expect(screen.queryByText('Other WS')).not.toBeInTheDocument();
  });

  it('auto-expands the conversation referenced by ?conversationId and renders all three panels', async () => {
    listConversations.mockResolvedValue({
      items: [{ id: 'c1', title: 'Auto', workspace_id: 'ws1' }],
    });

    renderAt('conversationId=c1');

    await waitFor(() =>
      expect(screen.getByTestId('inner-panel-c1')).toBeInTheDocument()
    );
    expect(screen.getByTestId('mode-panel-c1')).toBeInTheDocument();
    expect(screen.getByTestId('hitl-panel-c1')).toBeInTheDocument();
  });

  it('toggles open on click', async () => {
    listConversations.mockResolvedValue({
      items: [{ id: 'c1', title: 'Click me', workspace_id: 'ws1' }],
    });

    renderAt();

    await screen.findByText('Click me');
    expect(screen.queryByTestId('inner-panel-c1')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Click me'));
    expect(screen.getByTestId('inner-panel-c1')).toBeInTheDocument();
  });

  it('shows empty state when no conversations match', async () => {
    listConversations.mockResolvedValue({ items: [] });

    renderAt();

    expect(
      await screen.findByText(/No conversations linked to this workspace/i)
    ).toBeInTheDocument();
  });
});
