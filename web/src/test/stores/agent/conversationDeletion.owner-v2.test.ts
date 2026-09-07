import { beforeEach, expect, it, vi } from 'vitest';
import { agentService } from '@/services/agentService';
import { useAgentV3Store } from '@/stores/agentV3';
import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { createDefaultConversationState } from '@/types/conversationState';
const scope = vi.hoisted(() => ({ owner: {} }));
vi.mock('@/plugins/webOperationAdmissionV2', () => ({
  getWebOperationAvailabilityV2: () => ({ owner: scope.owner, available: true }),
}));
vi.mock('@/services/agentService', () => ({
  agentService: { deleteConversation: vi.fn(), unsubscribe: vi.fn() },
}));
vi.mock('@/utils/conversationDB', () => ({
  deleteConversationState: vi.fn(),
  loadConversationState: vi.fn(),
  saveConversationState: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  scope.owner = {};
});
for (const outcome of ['success', 'failure'] as const) {
  it(`old-owner delete ${outcome} leaves same-id new owner subscription and state intact`, async () => {
    let resolve!: () => void;
    let reject!: (error: Error) => void;
    vi.mocked(agentService.deleteConversation).mockReturnValueOnce(
      new Promise<void>((yes, no) => {
        resolve = yes;
        reject = no;
      })
    );
    const old = { id: 'same', project_id: 'p', title: 'old' } as any;
    useConversationsStore.setState({ conversations: [old], currentConversation: old });
    useAgentV3Store.setState({
      activeConversationId: 'same',
      conversations: [old],
      conversationStates: new Map([['same', createDefaultConversationState()]]),
    });
    const deletion = useAgentV3Store.getState().deleteConversation('same', 'p');
    scope.owner = {};
    const replacement = { id: 'same', project_id: 'p', title: 'new owner' } as any;
    const replacementStates = new Map([['same', createDefaultConversationState()]]);
    useConversationsStore.setState({
      conversations: [replacement],
      currentConversation: replacement,
      conversationsLoading: false,
      conversationsError: null,
    });
    useAgentV3Store.setState({
      activeConversationId: 'same',
      conversations: [replacement],
      conversationStates: replacementStates,
    });
    if (outcome === 'success') resolve();
    else reject(new Error('old request failed'));
    await deletion;
    expect(agentService.deleteConversation).toHaveBeenCalledTimes(1);
    expect(agentService.unsubscribe).not.toHaveBeenCalled();
    expect(useConversationsStore.getState().conversations).toEqual([replacement]);
    expect(useConversationsStore.getState().currentConversation).toBe(replacement);
    expect(useConversationsStore.getState().conversationsError).toBeNull();
    expect(useAgentV3Store.getState().conversationStates).toBe(replacementStates);
    expect(useAgentV3Store.getState().activeConversationId).toBe('same');
  });
}
