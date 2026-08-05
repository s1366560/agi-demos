import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '@/services/agentService';

import { SubAgentActions } from '@/components/agent/timeline/SubAgentActions';

vi.mock('@/services/agentService', () => ({
  agentService: {
    killSubAgent: vi.fn(),
    steerSubAgent: vi.fn(),
  },
}));

describe('SubAgentActions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps the steering instruction when authority rejects the command', async () => {
    vi.mocked(agentService.steerSubAgent).mockResolvedValue({
      type: 'control_command_ack',
      action: 'steer',
      accepted: false,
      duplicate: false,
      reason_code: 'run_revision_conflict',
      conversation_id: 'conversation-1',
      project_id: 'project-1',
      run_id: 'execution-1',
      run_revision: 8,
      idempotency_key: 'steer-1',
    });

    render(
      <SubAgentActions
        subagentId="execution-1"
        conversationId="conversation-1"
        expectedRunRevision={7}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'agent.subagent.action_redirect' }));
    const input = screen.getByRole('textbox', {
      name: 'agent.subagent.redirect_placeholder',
    });
    fireEvent.change(input, { target: { value: 'Use the current revision' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send redirect' }));

    await waitFor(() => {
      expect(agentService.steerSubAgent).toHaveBeenCalledWith(
        'conversation-1',
        'execution-1',
        'Use the current revision',
        { expectedRunRevision: 7 }
      );
    });
    expect(input).toHaveValue('Use the current revision');
  });
});
