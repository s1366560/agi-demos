/**
 * Unit tests for ConversationWorkspacePanel — consolidated workspace rail.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

const getConversation = vi.fn();
const getWorkspace = vi.fn();

vi.mock('@/services/agent/restApi', () => ({
  restApi: {
    getConversation: (...args: unknown[]) => getConversation(...args),
  },
}));

vi.mock('@/services/workspaceService', () => ({
  workspaceService: {
    getById: (...args: unknown[]) => getWorkspace(...args),
  },
  workspaceTaskService: { list: vi.fn().mockResolvedValue([]) },
}));

// Stub child panels — we only assert the header/orchestration.
vi.mock('@/components/agent/ConversationModePanel', () => ({
  ConversationModePanel: () => <div data-testid="stub-mode-panel" />,
}));
vi.mock('@/components/agent/ConversationParticipantsPanel', () => ({
  ConversationParticipantsPanel: () => <div data-testid="stub-participants-panel" />,
}));
vi.mock('@/components/agent/HITLCenterPanel', () => ({
  HITLCenterPanel: () => <div data-testid="stub-hitl-panel" />,
}));

import { ConversationWorkspacePanel } from '@/components/agent/ConversationWorkspacePanel';

const renderPanel = () =>
  render(
    <MemoryRouter initialEntries={['/tenant/t1/agent-workspace/c1']}>
      <Routes>
        <Route
          path="/tenant/:tenantId/agent-workspace/:conversation"
          element={<ConversationWorkspacePanel conversationId="c1" projectId="p1" />}
        />
      </Routes>
    </MemoryRouter>
  );

describe('ConversationWorkspacePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the standalone header when the conversation has no workspace_id', async () => {
    getConversation.mockResolvedValue({ id: 'c1', workspace_id: null });

    renderPanel();

    await waitFor(() => expect(getConversation).toHaveBeenCalled());
    expect(screen.getByText('Untethered conversation')).toBeInTheDocument();
    expect(screen.getByText('standalone')).toBeInTheDocument();
    expect(screen.queryByTestId('conversation-workspace-open-link')).not.toBeInTheDocument();
    expect(getWorkspace).not.toHaveBeenCalled();
  });

  it('renders the workspace header + deep link when linked', async () => {
    getConversation.mockResolvedValue({ id: 'c1', workspace_id: 'ws1' });
    getWorkspace.mockResolvedValue({
      id: 'ws1',
      name: 'Rollout Workspace',
      description: 'Tier-1 launch',
    });

    renderPanel();

    await waitFor(() => expect(getConversation).toHaveBeenCalled());
    await waitFor(() =>
      expect(getWorkspace).toHaveBeenCalledWith('t1', 'p1', 'ws1')
    );
    await waitFor(() =>
      expect(screen.getByText('Rollout Workspace')).toBeInTheDocument()
    );

    const link = screen.getByTestId('conversation-workspace-open-link');
    expect(link).toHaveAttribute('href', '/tenant/t1/workspaces/ws1');
    expect(screen.getByText('Tier-1 launch')).toBeInTheDocument();
    expect(screen.getByText('linked')).toBeInTheDocument();
  });

  it('renders all three section stubs (mode, participants, hitl)', async () => {
    getConversation.mockResolvedValue({ id: 'c1', workspace_id: null });

    renderPanel();

    expect(await screen.findByTestId('stub-mode-panel')).toBeInTheDocument();
    expect(screen.getByTestId('stub-participants-panel')).toBeInTheDocument();
    expect(screen.getByTestId('stub-hitl-panel')).toBeInTheDocument();
  });
});
