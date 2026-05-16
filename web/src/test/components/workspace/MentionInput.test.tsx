import { describe, expect, it, vi } from 'vitest';

import { MentionInput } from '@/components/workspace/chat/MentionInput';
import type { WorkspaceAgent, WorkspaceMember } from '@/types/workspace';

import { fireEvent, render, screen } from '../../utils';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
    i18n: { language: 'en-US', changeLanguage: vi.fn() },
  }),
}));

describe('MentionInput', () => {
  const members: WorkspaceMember[] = [
    {
      id: 'member-1',
      workspace_id: 'workspace-1',
      user_id: 'user-1',
      user_email: 'operator@example.com',
      role: 'member',
      created_at: '2024-01-01T00:00:00Z',
    },
  ];

  const agents: WorkspaceAgent[] = [
    {
      id: 'agent-binding-1',
      workspace_id: 'workspace-1',
      agent_id: 'agent-1',
      display_name: 'Planner',
      is_active: true,
      created_at: '2024-01-01T00:00:00Z',
    },
  ];

  it('renders localized input copy and sends non-empty messages', () => {
    const onSend = vi.fn();
    render(<MentionInput members={members} agents={agents} onSend={onSend} />);

    const input = screen.getByLabelText('Chat message input');
    expect(input).toHaveAttribute('placeholder', 'Type a message... (Use @ to mention)');

    fireEvent.change(input, { target: { value: 'Hello team' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onSend).toHaveBeenCalledWith('Hello team');
  });

  it('shows localized mention type labels in the mention dropdown', () => {
    render(<MentionInput members={members} agents={agents} onSend={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Chat message input'), {
      target: { value: '@' },
    });

    expect(screen.getByText('all')).toBeInTheDocument();
    expect(screen.getByText('broadcast')).toBeInTheDocument();
    expect(screen.getByText('human')).toBeInTheDocument();
    expect(screen.getByText('agent')).toBeInTheDocument();
  });
});
