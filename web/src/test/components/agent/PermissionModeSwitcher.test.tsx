import { act, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useAgentPermissionModeStore } from '@/stores/agent/permissionModeStore';
import { PermissionModeSwitcher } from '@/components/agent/PermissionModeSwitcher';

const mocks = vi.hoisted(() => ({
  mode: 'ask' as 'ask' | 'full_access',
  pending: {
    request_id: 'request',
    permission: 'write',
    tool_name: 'write',
    permission_type: 'ask',
  },
  respond: vi.fn(),
}));
vi.mock('@/hooks/useConversationApprovalMode', () => ({
  useConversationApprovalMode: () => ({
    mode: mocks.mode,
    saving: false,
    failed: false,
    save: vi.fn(),
  }),
}));
vi.mock('@/stores/agent/hitlStore', () => ({
  useAgentHITLStore: (selector: (state: unknown) => unknown) =>
    selector({ pendingPermission: mocks.pending }),
}));
vi.mock('@/stores/agentV3', () => ({
  useAgentV3Store: {
    getState: () => ({ activeConversationId: 'conversation', respondToPermission: mocks.respond }),
  },
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_key: string, fallback?: string) => fallback ?? _key }),
}));

describe('pending approval reconciliation', () => {
  beforeEach(() => {
    mocks.mode = 'ask';
    mocks.respond.mockReset().mockResolvedValue(undefined);
    useAgentPermissionModeStore.setState({
      pendingAutoApprovalIds: {},
      autoApprovedRequestIds: {},
    });
  });
  it('approves a pending request when canonical mode changes after arrival', async () => {
    const { rerender } = render(
      <PermissionModeSwitcher conversationId="conversation" projectId="project" />
    );
    expect(mocks.respond).not.toHaveBeenCalled();
    mocks.mode = 'full_access';
    rerender(<PermissionModeSwitcher conversationId="conversation" projectId="project" />);
    await waitFor(() => expect(mocks.respond).toHaveBeenCalledWith('request', true));
  });
  it('leaves a failed request answerable without retrying on rerender', async () => {
    mocks.mode = 'full_access';
    mocks.respond.mockRejectedValue(new Error('offline'));
    const { rerender } = render(
      <PermissionModeSwitcher conversationId="conversation" projectId="project" />
    );
    await act(async () => {});
    expect(useAgentPermissionModeStore.getState().pendingAutoApprovalIds.conversation).toEqual([]);
    rerender(<PermissionModeSwitcher conversationId="conversation" projectId="project" />);
    expect(mocks.respond).toHaveBeenCalledTimes(1);
    expect(mocks.pending.request_id).toBe('request');
  });
});
