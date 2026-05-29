import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
    expect(screen.getByText('Granted - executed')).toBeInTheDocument();
  });
});
