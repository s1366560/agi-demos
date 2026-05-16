import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ThreadView } from '../../../../components/agent/chat/ThreadView';

vi.mock('@/services/client/urlUtils', () => ({
  apiFetch: {
    get: vi.fn(),
  },
}));

import { apiFetch } from '@/services/client/urlUtils';

describe('ThreadView', () => {
  beforeEach(() => {
    vi.mocked(apiFetch.get).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('encodes route params when loading replies', async () => {
    vi.mocked(apiFetch.get).mockResolvedValueOnce(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    );

    render(
      <ThreadView
        messageId="message/1"
        conversationId="conversation #1"
        replyCount={1}
        onSendReply={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /1 replies/i }));

    await waitFor(() => {
      expect(apiFetch.get).toHaveBeenCalledWith(
        '/agent/conversations/conversation%20%231/messages/message%2F1/replies',
        expect.objectContaining({ signal: expect.any(AbortSignal) })
      );
    });
  });

  it('shows an error when loading replies returns a non-success response', async () => {
    vi.mocked(apiFetch.get).mockRejectedValueOnce(
      new Error('Failed to load thread replies (404)')
    );

    render(
      <ThreadView
        messageId="message-1"
        conversationId="conversation-1"
        replyCount={1}
        onSendReply={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /1 replies/i }));

    expect(await screen.findByText('Failed to load thread replies (404)')).toBeInTheDocument();
  });
});
