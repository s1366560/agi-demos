import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useConversationApprovalMode } from '@/hooks/useConversationApprovalMode';
import { useAgentPermissionModeStore } from '@/stores/agent/permissionModeStore';

const { getConversation, updateConversationConfig, authority } = vi.hoisted(() => ({
  authority: { snapshot: { owner: {}, available: true } },
  getConversation: vi.fn(),
  updateConversationConfig: vi.fn(),
}));
vi.mock('@/services/agentService', () => ({
  agentService: { getConversation, updateConversationConfig },
}));

vi.mock('@/plugins/webOperationAdmissionV2', () => {
  return {
    getWebOperationAvailabilityV2: () => authority.snapshot,
    subscribeWebOperationAvailabilityV2: () => () => {},
  };
});

describe('canonical conversation approval mode', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useAgentPermissionModeStore.setState({ modesByConversation: {} });
    getConversation.mockResolvedValue({
      id: 'conversation',
      project_id: 'project',
      agent_config: {},
    });
  });

  it('defaults missing config to ask and refreshes cross-client changes on focus', async () => {
    const { result } = renderHook(() => useConversationApprovalMode('conversation', 'project'));
    await waitFor(() => expect(getConversation).toHaveBeenCalledTimes(1));
    expect(result.current.mode).toBe('ask');
    getConversation.mockResolvedValue({
      id: 'conversation',
      project_id: 'project',
      agent_config: { approval_mode: 'auto_edit' },
    });
    act(() => window.dispatchEvent(new Event('focus')));
    await waitFor(() => expect(result.current.mode).toBe('auto_edit'));
    expect(updateConversationConfig).not.toHaveBeenCalled();
  });

  it('does not grant requested authority until the server acknowledges and preserves mode on failure', async () => {
    const { result } = renderHook(() => useConversationApprovalMode('conversation', 'project'));
    await waitFor(() => expect(getConversation).toHaveBeenCalled());
    let complete!: (value: unknown) => void;
    updateConversationConfig.mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        })
    );
    let saving!: Promise<void>;
    act(() => {
      saving = result.current.save('full_access');
    });
    expect(result.current.mode).toBe('ask');
    await act(async () => {
      complete({
        id: 'conversation',
        project_id: 'project',
        agent_config: { approval_mode: 'full_access' },
      });
      await saving;
    });
    expect(result.current.mode).toBe('full_access');
    expect(updateConversationConfig).toHaveBeenCalledWith('conversation', 'project', {
      approval_mode: 'full_access',
    });
    updateConversationConfig.mockRejectedValue(new Error('offline'));
    await act(async () => {
      await result.current.save('auto_edit');
    });
    expect(result.current.mode).toBe('full_access');
    expect(result.current.failed).toBe(true);
  });

  it('ignores a stale read that finishes after a saved mode', async () => {
    let complete!: (value: unknown) => void;
    getConversation.mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        })
    );
    updateConversationConfig.mockResolvedValue({
      id: 'conversation',
      project_id: 'project',
      agent_config: { approval_mode: 'auto_edit' },
    });
    const { result } = renderHook(() => useConversationApprovalMode('conversation', 'project'));
    await act(async () => {
      await result.current.save('auto_edit');
    });
    await act(async () => {
      complete({
        id: 'conversation',
        project_id: 'project',
        agent_config: { approval_mode: 'full_access' },
      });
    });
    expect(result.current.mode).toBe('auto_edit');
  });

  it('ignores a late response owned by a replaced renderer generation', async () => {
    let complete!: (value: unknown) => void;
    getConversation.mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        })
    );
    const { result, rerender } = renderHook(() =>
      useConversationApprovalMode('conversation', 'project')
    );
    const oldComplete = complete;
    authority.snapshot = { owner: {}, available: true };
    rerender();
    await act(async () => {
      oldComplete({
        id: 'conversation',
        project_id: 'project',
        agent_config: { approval_mode: 'full_access' },
      });
    });
    // The previous generation response cannot establish approval authority.
    expect(result.current.mode).toBe('ask');
  });

  it('rejects mismatched receipts and failed reads without retaining cached authority', async () => {
    useAgentPermissionModeStore.getState().setPermissionMode('conversation', 'full_access');
    getConversation.mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useConversationApprovalMode('conversation', 'project'));
    expect(result.current.mode).toBe('ask');
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(useAgentPermissionModeStore.getState().getPermissionMode('conversation')).toBe('ask');
    updateConversationConfig.mockResolvedValue({
      id: 'other',
      project_id: 'project',
      agent_config: { approval_mode: 'full_access' },
    });
    await act(async () => {
      await result.current.save('full_access');
    });
    expect(result.current.mode).toBe('ask');
    expect(result.current.failed).toBe(true);
    updateConversationConfig.mockResolvedValue({
      id: 'conversation',
      project_id: 'project',
      agent_config: {},
    });
    await act(async () => {
      await result.current.save('full_access');
    });
    expect(result.current.mode).toBe('ask');
    expect(result.current.failed).toBe(true);
  });

  it('ignores legacy persisted browser modes while retaining approval provenance', async () => {
    localStorage.setItem(
      'agent-permission-mode',
      JSON.stringify({
        state: {
          modesByConversation: { legacy: 'full_access' },
          autoApprovedRequestIds: { legacy: ['request'] },
        },
        version: 0,
      })
    );
    await useAgentPermissionModeStore.persist.rehydrate();
    expect(useAgentPermissionModeStore.getState().getPermissionMode('legacy')).toBe('ask');
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds.legacy).toEqual([
      'request',
    ]);
  });
});
