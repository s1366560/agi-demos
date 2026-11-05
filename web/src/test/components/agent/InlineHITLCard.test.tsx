import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { message } from 'antd';
import '@testing-library/jest-dom/vitest';

import type { ClarificationAskedEventData, PermissionAskedEventData } from '@/types/agent';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

const respondToClarification = vi.fn().mockResolvedValue(undefined);
const respondToDecision = vi.fn().mockResolvedValue(undefined);
const respondToEnvVar = vi.fn().mockResolvedValue(undefined);
const respondToPermission = vi.fn().mockResolvedValue(undefined);

vi.mock('@/stores/agentV3', () => ({
  useAgentV3Store: (selector: (state: unknown) => unknown) =>
    selector({
      respondToClarification,
      respondToDecision,
      respondToEnvVar,
      respondToPermission,
    }),
}));

const requestStatuses = new Map<string, string>();
const updateRequestStatus = vi.fn();

vi.mock('@/stores/hitlStore.unified', () => {
  const useUnifiedHITLStore = Object.assign(
    (selector: (state: unknown) => unknown) =>
      selector({
        isSubmitting: false,
        submittingRequestId: null,
        requestStatuses,
      }),
    {
      getState: () => ({
        updateRequestStatus,
      }),
    }
  );

  return { useUnifiedHITLStore };
});

import { InlineHITLCard } from '@/components/agent/InlineHITLCard';

describe('InlineHITLCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requestStatuses.clear();
  });

  it('shows a failed permission submission without marking the request answered', async () => {
    respondToPermission.mockRejectedValueOnce(new Error('Permission response failed'));
    const errorToast = vi.spyOn(message, 'error').mockReturnValue(Promise.resolve() as never);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      render(
        <InlineHITLCard
          hitlType="permission"
          requestId="permission-failed"
          permissionData={{
            request_id: 'permission-failed',
            tool_name: 'memory_update',
            permission_type: 'ask',
            description: 'Update memory',
            risk_level: 'low',
            context: {},
          }}
        />
      );
      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));
      await waitFor(() => expect(errorToast).toHaveBeenCalledWith('Permission response failed'));
      expect(updateRequestStatus).not.toHaveBeenCalled();
      expect(screen.queryByText('Decision recorded')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Allow$/ })).not.toBeDisabled();
    } finally {
      errorToast.mockRestore();
      consoleError.mockRestore();
    }
  });

  it('renders clarification requests with missing options without crashing', async () => {
    const clarificationData = {
      request_id: 'hitl-1',
      question: 'Continue &amp; verify?',
      clarification_type: 'choice',
      options: undefined,
      allow_custom: true,
      context: {},
    } as unknown as ClarificationAskedEventData;

    render(
      <InlineHITLCard
        hitlType="clarification"
        requestId="hitl-1"
        clarificationData={clarificationData}
      />
    );

    expect(await screen.findByText('Needs clarification')).toBeInTheDocument();
    expect(screen.getByText('Continue & verify?')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('renders answered permission requests with invalid timestamps without crashing', async () => {
    const permissionData: PermissionAskedEventData = {
      request_id: 'hitl-2',
      tool_name: 'deploy_tool',
      permission_type: 'ask',
      description: 'Deploy &lt;prod&gt;',
      risk_level: 'high',
      context: {},
    };

    render(
      <InlineHITLCard
        hitlType="permission"
        requestId="hitl-2"
        permissionData={permissionData}
        isAnswered={true}
        answeredValue="Granted"
        createdAt="not-a-date"
      />
    );

    expect(await screen.findByText('Needs permission')).toBeInTheDocument();
    expect(screen.getByText('Deploy <prod>')).toBeInTheDocument();
    expect(screen.getByText('Permission granted')).toBeInTheDocument();
    expect(screen.queryByText('Granted - executed')).not.toBeInTheDocument();
  });

  it('derives the granted verdict from the structured prop, not localized text', async () => {
    const permissionData: PermissionAskedEventData = {
      request_id: 'hitl-i18n',
      tool_name: 'deploy_tool',
      permission_type: 'ask',
      description: 'Deploy prod',
      risk_level: 'high',
      context: {},
    };

    const { unmount } = render(
      <InlineHITLCard
        hitlType="permission"
        requestId="hitl-i18n"
        permissionData={permissionData}
        isAnswered={true}
        answeredValue="已允许"
        answeredGranted={true}
        createdAt="2026-09-17T00:00:00Z"
      />
    );

    expect(await screen.findByText('Permission granted')).toBeInTheDocument();
    expect(screen.queryByText('Permission denied')).not.toBeInTheDocument();
    unmount();

    render(
      <InlineHITLCard
        hitlType="permission"
        requestId="hitl-i18n"
        permissionData={permissionData}
        isAnswered={true}
        answeredValue="已拒绝"
        answeredGranted={false}
        createdAt="2026-09-17T00:00:00Z"
      />
    );

    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
  });
});
