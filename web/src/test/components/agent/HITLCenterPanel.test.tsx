/**
 * Unit tests for HITLCenterPanel accept/reject inline resolution (Track F).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

// react-i18next pass-through mock so fallback text renders verbatim.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}));

const respondToDecision = vi.fn().mockResolvedValue(undefined);
const respondToClarification = vi.fn().mockResolvedValue(undefined);
const respondToPermission = vi.fn().mockResolvedValue(undefined);

vi.mock('../../../stores/agentV3', () => ({
  useAgentV3Store: (selector: (state: unknown) => unknown) =>
    selector({ respondToDecision, respondToClarification, respondToPermission }),
}));

const getPendingHITLRequests = vi.fn();

vi.mock('../../../services/agent/restApi', () => ({
  restApi: {
    getPendingHITLRequests: (...args: unknown[]) => getPendingHITLRequests(...args),
  },
}));

import { HITLCenterPanel } from '@/components/agent/HITLCenterPanel';

describe('HITLCenterPanel — inline resolve (Track F)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders Accept/Reject for decision requests and calls respondToDecision with first option on accept', async () => {
    getPendingHITLRequests.mockResolvedValueOnce({
      requests: [
        {
          id: 'req-1',
          request_type: 'decision',
          question: 'Ship it?',
          created_at: new Date().toISOString(),
          metadata: { category: 'action', visibility: 'room' },
          options: [
            { id: 'approve', label: 'Approve' },
            { id: 'reject', label: 'Reject' },
          ],
        },
      ],
    });

    render(
      <HITLCenterPanel conversationId="conv-1" autoRefreshMs={0} />
    );

    await waitFor(() => {
      expect(screen.getByText('Ship it?')).toBeInTheDocument();
    });

    const accept = screen.getByTestId('hitl-accept-btn');
    fireEvent.click(accept);

    await waitFor(() => {
      expect(respondToDecision).toHaveBeenCalledWith('req-1', 'approve');
    });
  });

  it('calls respondToPermission(false) on reject for permission requests', async () => {
    getPendingHITLRequests.mockResolvedValueOnce({
      requests: [
        {
          id: 'req-2',
          request_type: 'permission',
          question: 'Grant network access?',
          created_at: new Date().toISOString(),
          metadata: {},
        },
      ],
    });

    render(
      <HITLCenterPanel conversationId="conv-2" autoRefreshMs={0} />
    );

    await waitFor(() => {
      expect(screen.getByText('Grant network access?')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('hitl-reject-btn'));

    await waitFor(() => {
      expect(respondToPermission).toHaveBeenCalledWith('req-2', false);
    });
  });

  it('shows only the Open button for clarification requests (inline resolve not allowed)', async () => {
    getPendingHITLRequests.mockResolvedValueOnce({
      requests: [
        {
          id: 'req-3',
          request_type: 'clarification',
          question: 'Which repo?',
          created_at: new Date().toISOString(),
          metadata: {},
        },
      ],
    });

    render(
      <HITLCenterPanel conversationId="conv-3" autoRefreshMs={0} />
    );

    await waitFor(() => {
      expect(screen.getByText('Which repo?')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('hitl-accept-btn')).not.toBeInTheDocument();
    expect(screen.getByTestId('hitl-open-btn')).toBeInTheDocument();
  });
});
