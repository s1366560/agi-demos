/**
 * Unit tests for conversationsStore.
 *
 * TDD RED Phase: Tests written first for Conversations store split.
 *
 * Feature: Split Conversations state from monolithic agent store.
 *
 * Conversations state includes:
 * - conversations: List of conversations
 * - currentConversation: Active conversation
 * - conversationsLoading: Loading state
 * - conversationsError: Error state
 * - isNewConversationPending: Flag for new conversation pending state
 *
 * Actions:
 * - listConversations: Fetch list of conversations for a project
 * - createConversation: Create a new conversation
 * - getConversation: Get a specific conversation
 * - deleteConversation: Delete a conversation
 * - setCurrentConversation: Set the active conversation (basic version)
 * - generateConversationTitle: Auto-generate title for conversation
 * - updateCurrentConversation: Update current conversation object
 * - reset: Reset to initial state
 *
 * Note: The full setCurrentConversation with state saving/restoration
 * is complex and tightly coupled with timeline/execution state.
 * This store provides a simpler setCurrentConversation for basic switching.
 *
 * These tests verify that the conversationsStore maintains the same behavior
 * as the original monolithic agent store's conversation functionality.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

import { agentService } from '../../../services/agentService';
import { useConversationsStore, initialState } from '../../../stores/agent/conversationsStore';

import type { Conversation } from '../../../types/agent';
// Helper to create a mock conversation with all required fields
const createMockConversation = (
  id: string,
  projectId: string,
  title: string,
  status: 'active' | 'archived' | 'deleted' = 'active'
): Conversation => ({
  id,
  project_id: projectId,
  tenant_id: 'tenant-1',
  user_id: 'user-1',
  title,
  status,
  message_count: 0,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

// Mock agent service
vi.mock('../../../services/agentService', () => ({
  agentService: {
    listConversations: vi.fn(),
    createConversation: vi.fn(),
    getConversation: vi.fn(),
    deleteConversation: vi.fn(),
    generateConversationTitle: vi.fn(),
  },
}));

// Helper to access mocked methods
const listConversationsMock = vi.mocked(agentService.listConversations);
const createConversationMock = vi.mocked(agentService.createConversation);
const getConversationMock = vi.mocked(agentService.getConversation);
const deleteConversationMock = vi.mocked(agentService.deleteConversation);
const generateConversationTitleMock = vi.mocked(agentService.generateConversationTitle);

describe('ConversationsStore', () => {
  beforeEach(() => {
    // Reset store before each test
    useConversationsStore.getState().reset();
    vi.clearAllMocks();
  });

  describe('Initial State', () => {
    it('should have correct initial state', () => {
      const state = useConversationsStore.getState();
      expect(state.conversations).toEqual(initialState.conversations);
      expect(state.currentConversation).toBe(initialState.currentConversation);
      expect(state.conversationsLoading).toBe(initialState.conversationsLoading);
      expect(state.conversationsError).toBe(initialState.conversationsError);
      expect(state.isNewConversationPending).toBe(initialState.isNewConversationPending);
    });

    it('should have empty conversations list initially', () => {
      const { conversations } = useConversationsStore.getState();
      expect(conversations).toEqual([]);
    });

    it('should have null current conversation initially', () => {
      const { currentConversation } = useConversationsStore.getState();
      expect(currentConversation).toBe(null);
    });

    it('should have conversationsLoading as false initially', () => {
      const { conversationsLoading } = useConversationsStore.getState();
      expect(conversationsLoading).toBe(false);
    });

    it('should have conversationsError as null initially', () => {
      const { conversationsError } = useConversationsStore.getState();
      expect(conversationsError).toBe(null);
    });

    it('should have isNewConversationPending as false initially', () => {
      const { isNewConversationPending } = useConversationsStore.getState();
      expect(isNewConversationPending).toBe(false);
    });
  });

  describe('reset', () => {
    it('should reset state to initial values', async () => {
      // Set some state
      const mockConversation = createMockConversation('conv-1', 'proj-1', 'Test Conversation');

      useConversationsStore.setState({
        conversations: [mockConversation],
        currentConversation: mockConversation,
        conversationsLoading: false,
        conversationsError: null,
        isNewConversationPending: true,
      });

      // Verify state is set
      expect(useConversationsStore.getState().conversations).toHaveLength(1);
      expect(useConversationsStore.getState().isNewConversationPending).toBe(true);

      // Reset
      useConversationsStore.getState().reset();

      // Verify initial state restored
      const state = useConversationsStore.getState();
      expect(state.conversations).toEqual([]);
      expect(state.currentConversation).toBe(null);
      expect(state.conversationsLoading).toBe(false);
      expect(state.conversationsError).toBe(null);
      expect(state.isNewConversationPending).toBe(false);
    });
  });

  describe('listConversations', () => {
    it('should fetch conversations successfully', async () => {
      const mockConversations: Conversation[] = [
        createMockConversation('conv-1', 'proj-1', 'Conversation 1'),
        createMockConversation('conv-2', 'proj-1', 'Conversation 2', 'archived'),
      ];

      listConversationsMock.mockResolvedValue({
        items: mockConversations,
        has_more: false,
        total: 2,
      });

      await useConversationsStore.getState().listConversations('proj-1');

      const { conversations, conversationsLoading, conversationsError } =
        useConversationsStore.getState();

      expect(conversations).toEqual(mockConversations);
      expect(conversationsLoading).toBe(false);
      expect(conversationsError).toBe(null);
      expect(listConversationsMock).toHaveBeenCalledWith('proj-1', undefined, 10, 0, undefined, {
        groupByWorkspace: true,
      });
    });

    it('should fetch conversations with status filter', async () => {
      const mockConversations: Conversation[] = [
        createMockConversation('conv-1', 'proj-1', 'Active Conversation'),
      ];

      listConversationsMock.mockResolvedValue({
        items: mockConversations,
        has_more: false,
        total: 1,
      });

      await useConversationsStore.getState().listConversations('proj-1', 'active');

      expect(listConversationsMock).toHaveBeenCalledWith('proj-1', 'active', 10, 0, undefined, {
        groupByWorkspace: true,
      });
    });

    it('should fetch conversations with custom limit', async () => {
      const mockConversations: Conversation[] = [];
      listConversationsMock.mockResolvedValue({
        items: mockConversations,
        has_more: false,
        total: 0,
      });

      await useConversationsStore.getState().listConversations('proj-1', undefined, 100);

      expect(listConversationsMock).toHaveBeenCalledWith('proj-1', undefined, 100, 0, undefined, {
        groupByWorkspace: true,
      });
    });

    it('should set loading state during fetch', async () => {
      let resolveConversations: (value: any) => void;
      const pendingPromise = new Promise((resolve) => {
        resolveConversations = resolve;
      });

      listConversationsMock.mockReturnValue(pendingPromise as any);

      // Start fetch (don't await)
      const fetchPromise = useConversationsStore.getState().listConversations('proj-1');

      // Check loading state
      expect(useConversationsStore.getState().conversationsLoading).toBe(true);

      // Resolve and complete
      resolveConversations!({ items: [], has_more: false, total: 0 });
      await fetchPromise;
    });

    it('allows a newer project request while an older project is still loading', async () => {
      const projectARequest = deferred<{
        items: Conversation[];
        has_more: boolean;
        total: number;
      }>();
      const projectBRequest = deferred<{
        items: Conversation[];
        has_more: boolean;
        total: number;
      }>();
      const projectAConversation = createMockConversation('conv-a', 'proj-a', 'Project A');
      const projectBConversation = createMockConversation('conv-b', 'proj-b', 'Project B');

      listConversationsMock
        .mockReturnValueOnce(projectARequest.promise as any)
        .mockReturnValueOnce(projectBRequest.promise as any);

      const projectAPromise = useConversationsStore.getState().listConversations('proj-a');
      expect(useConversationsStore.getState().conversationsLoading).toBe(true);

      const projectBPromise = useConversationsStore.getState().listConversations('proj-b');
      expect(listConversationsMock).toHaveBeenCalledTimes(2);

      projectBRequest.resolve({
        items: [projectBConversation],
        has_more: false,
        total: 1,
      });
      await projectBPromise;

      expect(useConversationsStore.getState().conversations).toEqual([projectBConversation]);
      expect(useConversationsStore.getState().conversationsLoading).toBe(false);

      projectARequest.resolve({
        items: [projectAConversation],
        has_more: false,
        total: 1,
      });
      await projectAPromise;

      expect(useConversationsStore.getState().conversations).toEqual([projectBConversation]);
    });

    it('keeps post-reset list request authoritative when a stale request resolves first', async () => {
      const staleRequest = deferred<{
        items: Conversation[];
        has_more: boolean;
        total: number;
      }>();
      const freshRequest = deferred<{
        items: Conversation[];
        has_more: boolean;
        total: number;
      }>();
      const staleConversation = createMockConversation('conv-stale', 'proj-stale', 'Stale');
      const freshConversation = createMockConversation('conv-fresh', 'proj-fresh', 'Fresh');

      listConversationsMock
        .mockReturnValueOnce(staleRequest.promise as any)
        .mockReturnValueOnce(freshRequest.promise as any);

      const staleLoad = useConversationsStore.getState().listConversations('proj-stale');
      useConversationsStore.getState().reset();
      const freshLoad = useConversationsStore.getState().listConversations('proj-fresh');

      staleRequest.resolve({
        items: [staleConversation],
        has_more: false,
        total: 1,
      });
      await staleLoad;
      expect(useConversationsStore.getState().conversations).toEqual([]);
      expect(useConversationsStore.getState().conversationsLoading).toBe(true);

      freshRequest.resolve({
        items: [freshConversation],
        has_more: false,
        total: 1,
      });
      await freshLoad;

      expect(useConversationsStore.getState().conversations).toEqual([freshConversation]);
      expect(useConversationsStore.getState().conversationsLoading).toBe(false);
    });

    it('should handle fetch error', async () => {
      const error = { response: { data: { detail: 'Network error' } } };
      listConversationsMock.mockRejectedValue(error);

      await expect(useConversationsStore.getState().listConversations('proj-1')).rejects.toEqual(
        error
      );

      const { conversationsLoading, conversationsError } = useConversationsStore.getState();

      expect(conversationsLoading).toBe(false);
      expect(conversationsError).toBe('Network error');
    });

    it('should handle fetch error without detail', async () => {
      const error = { message: 'Unknown error' };
      listConversationsMock.mockRejectedValue(error);

      await expect(useConversationsStore.getState().listConversations('proj-1')).rejects.toEqual(
        error
      );

      expect(useConversationsStore.getState().conversationsError).toBe(
        'Failed to list conversations'
      );
    });

    it('should replace existing conversations on new fetch', async () => {
      // Set existing conversations
      const existingConv = createMockConversation('old', 'proj-1', 'Old');

      useConversationsStore.setState({
        conversations: [existingConv],
      });

      const newConversations: Conversation[] = [createMockConversation('new', 'proj-1', 'New')];

      listConversationsMock.mockResolvedValue({
        items: newConversations,
        has_more: false,
        total: 1,
      });

      await useConversationsStore.getState().listConversations('proj-1');

      expect(useConversationsStore.getState().conversations).toEqual(newConversations);
    });
  });

  describe('loadMoreConversations', () => {
    it('appends older pages without moving existing conversations behind them', async () => {
      const olderConversation = {
        ...createMockConversation('conv-old', 'proj-1', 'Old'),
        updated_at: '2024-01-01T00:00:00Z',
      };
      const refreshedConversation = {
        ...createMockConversation('conv-refresh', 'proj-1', 'Refreshed'),
        updated_at: '2024-01-03T00:00:00Z',
      };
      const nextPageConversation = {
        ...createMockConversation('conv-next-page', 'proj-1', 'Next Page'),
        updated_at: '2023-12-31T00:00:00Z',
      };

      useConversationsStore.setState({
        conversations: [refreshedConversation, olderConversation],
        hasMoreConversations: true,
        conversationsNextOffset: 2,
      });

      listConversationsMock.mockResolvedValue({
        items: [nextPageConversation, refreshedConversation],
        has_more: false,
        total: 3,
        offset: 2,
      });

      await useConversationsStore.getState().loadMoreConversations('proj-1');

      expect(
        useConversationsStore.getState().conversations.map((conversation) => conversation.id)
      ).toEqual(['conv-refresh', 'conv-old', 'conv-next-page']);
    });

    it('ignores stale older pages after conversation scope reset', async () => {
      const existingConversation = createMockConversation('conv-existing', 'proj-stale', 'Current');
      const staleConversation = createMockConversation('conv-stale-page', 'proj-stale', 'Stale');
      const stalePage = deferred<{
        items: Conversation[];
        has_more: boolean;
        total: number;
        offset: number;
      }>();

      useConversationsStore.setState({
        conversations: [existingConversation],
        hasMoreConversations: true,
        conversationsNextOffset: 1,
        conversationListProjectId: 'proj-stale',
      });
      listConversationsMock.mockReturnValueOnce(stalePage.promise as any);

      const loadPromise = useConversationsStore.getState().loadMoreConversations('proj-stale');
      expect(useConversationsStore.getState().conversationsLoadingMore).toBe(true);

      useConversationsStore.getState().reset();
      stalePage.resolve({
        items: [staleConversation],
        has_more: false,
        total: 2,
        offset: 1,
      });

      await loadPromise;

      expect(useConversationsStore.getState().conversations).toEqual([]);
      expect(useConversationsStore.getState().conversationListProjectId).toBe(null);
      expect(useConversationsStore.getState().conversationsLoadingMore).toBe(false);
    });
  });

  describe('createConversation', () => {
    it('should create conversation successfully', async () => {
      const newConversation = createMockConversation('conv-1', 'proj-1', 'New Chat');

      createConversationMock.mockResolvedValue(newConversation);

      const result = await useConversationsStore.getState().createConversation('proj-1');

      const { conversations, currentConversation, conversationsLoading, isNewConversationPending } =
        useConversationsStore.getState();

      expect(result).toEqual(newConversation);
      expect(conversations).toEqual([newConversation]);
      expect(currentConversation).toEqual(newConversation);
      expect(conversationsLoading).toBe(false);
      expect(isNewConversationPending).toBe(true);
      expect(createConversationMock).toHaveBeenCalledWith({
        project_id: 'proj-1',
        title: 'New Chat',
        agent_config: { selected_agent_id: 'builtin:all-access' },
      });
    });

    it('should create conversation with custom title', async () => {
      const newConversation = createMockConversation('conv-1', 'proj-1', 'Custom Title');

      createConversationMock.mockResolvedValue(newConversation);

      await useConversationsStore.getState().createConversation('proj-1', 'Custom Title');

      expect(createConversationMock).toHaveBeenCalledWith({
        project_id: 'proj-1',
        title: 'Custom Title',
        agent_config: { selected_agent_id: 'builtin:all-access' },
      });
    });

    it('should prepend new conversation to existing list', async () => {
      const existingConv = createMockConversation('existing', 'proj-1', 'Existing');

      useConversationsStore.setState({
        conversations: [existingConv],
      });

      const newConversation = createMockConversation('new', 'proj-1', 'New');

      createConversationMock.mockResolvedValue(newConversation);

      await useConversationsStore.getState().createConversation('proj-1');

      const { conversations } = useConversationsStore.getState();

      expect(conversations).toHaveLength(2);
      expect(conversations[0].id).toBe('new');
      expect(conversations[1].id).toBe('existing');
    });

    it('should handle create error', async () => {
      const error = { response: { data: { detail: 'Creation failed' } } };
      createConversationMock.mockRejectedValue(error);

      await expect(useConversationsStore.getState().createConversation('proj-1')).rejects.toEqual(
        error
      );

      const { conversationsLoading, conversationsError } = useConversationsStore.getState();

      expect(conversationsLoading).toBe(false);
      expect(conversationsError).toBe('Creation failed');
    });
  });

  describe('getConversation', () => {
    it('should get conversation successfully', async () => {
      const conversation = createMockConversation('conv-1', 'proj-1', 'Test');

      getConversationMock.mockResolvedValue(conversation);

      const result = await useConversationsStore.getState().getConversation('conv-1', 'proj-1');

      const { currentConversation, conversationsLoading } = useConversationsStore.getState();

      expect(result).toEqual(conversation);
      expect(currentConversation).toEqual(conversation);
      expect(conversationsLoading).toBe(false);
      expect(getConversationMock).toHaveBeenCalledWith('conv-1', 'proj-1');
    });

    it('should return null on error', async () => {
      const error = { response: { data: { detail: 'Not found' } } };
      getConversationMock.mockRejectedValue(error);

      const result = await useConversationsStore.getState().getConversation('conv-1', 'proj-1');

      expect(result).toBe(null);
      expect(useConversationsStore.getState().conversationsLoading).toBe(false);
      expect(useConversationsStore.getState().conversationsError).toBe('Not found');
    });

    it('should handle get error without detail', async () => {
      const error = { message: 'Unknown error' };
      getConversationMock.mockRejectedValue(error);

      const result = await useConversationsStore.getState().getConversation('conv-1', 'proj-1');

      expect(result).toBe(null);
      expect(useConversationsStore.getState().conversationsError).toBe(
        'Failed to get conversation'
      );
    });
  });

  describe('deleteConversation', () => {
    it('should delete conversation successfully', async () => {
      const conv1 = createMockConversation('conv-1', 'proj-1', 'Conversation 1');
      const conv2 = createMockConversation('conv-2', 'proj-1', 'Conversation 2');

      useConversationsStore.setState({
        conversations: [conv1, conv2],
        currentConversation: conv1,
      });

      deleteConversationMock.mockResolvedValue(undefined);

      await useConversationsStore.getState().deleteConversation('conv-1', 'proj-1');

      const { conversations, currentConversation, conversationsLoading } =
        useConversationsStore.getState();

      expect(conversations).toHaveLength(1);
      expect(conversations[0].id).toBe('conv-2');
      expect(currentConversation).toBe(null);
      expect(conversationsLoading).toBe(false);
      expect(deleteConversationMock).toHaveBeenCalledWith('conv-1', 'proj-1');
    });

    it('should keep current conversation if deleting different conversation', async () => {
      const conv1 = createMockConversation('conv-1', 'proj-1', 'Conversation 1');
      const conv2 = createMockConversation('conv-2', 'proj-1', 'Conversation 2');

      useConversationsStore.setState({
        conversations: [conv1, conv2],
        currentConversation: conv1,
      });

      deleteConversationMock.mockResolvedValue(undefined);

      await useConversationsStore.getState().deleteConversation('conv-2', 'proj-1');

      const { currentConversation } = useConversationsStore.getState();

      expect(currentConversation).toEqual(conv1);
    });

    it('should handle delete error', async () => {
      const conv1 = createMockConversation('conv-1', 'proj-1', 'Conversation 1');

      useConversationsStore.setState({
        conversations: [conv1],
      });

      const error = { response: { data: { detail: 'Delete failed' } } };
      deleteConversationMock.mockRejectedValue(error);

      await expect(
        useConversationsStore.getState().deleteConversation('conv-1', 'proj-1')
      ).rejects.toEqual(error);

      const { conversationsLoading, conversationsError } = useConversationsStore.getState();

      expect(conversationsLoading).toBe(false);
      expect(conversationsError).toBe('Delete failed');
    });
  });

  describe('setCurrentConversation', () => {
    it('should set current conversation', () => {
      const conversation = createMockConversation('conv-1', 'proj-1', 'Test');

      useConversationsStore.getState().setCurrentConversation(conversation);

      expect(useConversationsStore.getState().currentConversation).toEqual(conversation);
    });

    it('should set null to clear current conversation', () => {
      const conversation = createMockConversation('conv-1', 'proj-1', 'Test');

      useConversationsStore.setState({
        currentConversation: conversation,
      });

      useConversationsStore.getState().setCurrentConversation(null);

      expect(useConversationsStore.getState().currentConversation).toBe(null);
    });

    it('should clear pending flag when setting conversation', () => {
      useConversationsStore.setState({
        isNewConversationPending: true,
      });

      const conversation = createMockConversation('conv-1', 'proj-1', 'Test');

      useConversationsStore.getState().setCurrentConversation(conversation);

      expect(useConversationsStore.getState().isNewConversationPending).toBe(false);
    });
  });

  describe('generateConversationTitle', () => {
    it('should generate title for conversation', async () => {
      const currentConversation = createMockConversation('conv-1', 'proj-1', 'New Chat');

      const updatedConversation: Conversation = {
        ...currentConversation,
        title: 'Generated Title',
        updated_at: '2024-01-01T01:00:00Z',
      };

      useConversationsStore.setState({
        currentConversation,
        conversations: [currentConversation],
      });

      generateConversationTitleMock.mockResolvedValue(updatedConversation);

      await useConversationsStore.getState().generateConversationTitle();

      const { currentConversation: updated, conversations } = useConversationsStore.getState();

      expect(updated?.title).toBe('Generated Title');
      expect(conversations[0]?.title).toBe('Generated Title');
      expect(generateConversationTitleMock).toHaveBeenCalledWith('conv-1', 'proj-1');
    });

    it('should do nothing if no current conversation', async () => {
      useConversationsStore.setState({
        currentConversation: null,
      });

      await useConversationsStore.getState().generateConversationTitle();

      expect(generateConversationTitleMock).not.toHaveBeenCalled();
    });

    it('should update conversations list with new title', async () => {
      const currentConversation = createMockConversation('conv-1', 'proj-1', 'New Chat');
      const otherConversation = createMockConversation('conv-2', 'proj-1', 'Other');

      useConversationsStore.setState({
        currentConversation,
        conversations: [otherConversation, currentConversation],
      });

      const updatedConversation: Conversation = {
        ...currentConversation,
        title: 'Generated Title',
        updated_at: '2024-01-01T01:00:00Z',
      };

      generateConversationTitleMock.mockResolvedValue(updatedConversation);

      await useConversationsStore.getState().generateConversationTitle();

      const { conversations } = useConversationsStore.getState();

      expect(conversations).toHaveLength(2);
      expect(conversations[1].title).toBe('Generated Title');
    });

    it('should handle generate title error gracefully', async () => {
      const currentConversation = createMockConversation('conv-1', 'proj-1', 'New Chat');

      useConversationsStore.setState({
        currentConversation,
        conversations: [currentConversation],
      });

      const error = new Error('Generation failed');
      generateConversationTitleMock.mockRejectedValue(error);

      await useConversationsStore.getState().generateConversationTitle();

      // Should not throw, just log error
      const { currentConversation: updatedConv } = useConversationsStore.getState();
      expect(updatedConv?.title).toBe('New Chat');
    });
  });

  describe('updateCurrentConversation', () => {
    it('should update current conversation object', () => {
      const currentConversation = createMockConversation('conv-1', 'proj-1', 'Original Title');

      useConversationsStore.setState({
        currentConversation,
        conversations: [currentConversation],
      });

      const updated: Conversation = {
        ...currentConversation,
        title: 'Updated Title',
      };

      useConversationsStore.getState().updateCurrentConversation(updated);

      expect(useConversationsStore.getState().currentConversation).toEqual(updated);
      expect(useConversationsStore.getState().conversations[0]).toEqual(updated);
    });

    it('should not update if current conversation is null', () => {
      useConversationsStore.setState({
        currentConversation: null,
        conversations: [],
      });

      const conversation = createMockConversation('conv-1', 'proj-1', 'Test');

      useConversationsStore.getState().updateCurrentConversation(conversation);

      expect(useConversationsStore.getState().currentConversation).toBe(null);
    });

    it('should update in conversations list by id', () => {
      const conv1 = createMockConversation('conv-1', 'proj-1', 'Conversation 1');
      const conv2 = createMockConversation('conv-2', 'proj-1', 'Conversation 2');

      useConversationsStore.setState({
        currentConversation: conv1,
        conversations: [conv2, conv1],
      });

      const updated: Conversation = {
        ...conv1,
        title: 'Updated Conversation 1',
      };

      useConversationsStore.getState().updateCurrentConversation(updated);

      const { conversations, currentConversation } = useConversationsStore.getState();

      expect(currentConversation).toEqual(updated);
      expect(conversations[1]).toEqual(updated);
      expect(conversations[0]).toEqual(conv2); // Unchanged
    });
  });

  describe('clearPendingFlag', () => {
    it('should clear the new conversation pending flag', () => {
      useConversationsStore.setState({
        isNewConversationPending: true,
      });

      useConversationsStore.getState().clearPendingFlag();

      expect(useConversationsStore.getState().isNewConversationPending).toBe(false);
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty conversations list', async () => {
      listConversationsMock.mockResolvedValue({
        items: [],
        has_more: false,
        total: 0,
      });

      await useConversationsStore.getState().listConversations('proj-1');

      expect(useConversationsStore.getState().conversations).toEqual([]);
    });

    it('should handle setting same conversation multiple times', () => {
      const conversation = createMockConversation('conv-1', 'proj-1', 'Test');

      useConversationsStore.getState().setCurrentConversation(conversation);
      useConversationsStore.getState().setCurrentConversation(conversation);

      expect(useConversationsStore.getState().currentConversation).toEqual(conversation);
    });

    it('should handle switching between conversations', () => {
      const conv1 = createMockConversation('conv-1', 'proj-1', 'Conversation 1');
      const conv2 = createMockConversation('conv-2', 'proj-1', 'Conversation 2');

      useConversationsStore.getState().setCurrentConversation(conv1);
      expect(useConversationsStore.getState().currentConversation?.id).toBe('conv-1');

      useConversationsStore.getState().setCurrentConversation(conv2);
      expect(useConversationsStore.getState().currentConversation?.id).toBe('conv-2');

      useConversationsStore.getState().setCurrentConversation(conv1);
      expect(useConversationsStore.getState().currentConversation?.id).toBe('conv-1');
    });

    it('should handle rapid create conversations', async () => {
      const conversation1 = createMockConversation('conv-1', 'proj-1', 'Conversation 1');
      const conversation2 = createMockConversation('conv-2', 'proj-1', 'Conversation 2');

      createConversationMock
        .mockResolvedValueOnce(conversation1)
        .mockResolvedValueOnce(conversation2);

      await useConversationsStore.getState().createConversation('proj-1', 'Conv 1');
      await useConversationsStore.getState().createConversation('proj-1', 'Conv 2');

      const { conversations, currentConversation } = useConversationsStore.getState();

      expect(conversations).toHaveLength(2);
      expect(currentConversation?.id).toBe('conv-2');
    });

    it('should handle delete when conversation not in list', async () => {
      deleteConversationMock.mockResolvedValue(undefined);

      // Should not throw even if conversation not in list
      await expect(
        useConversationsStore.getState().deleteConversation('non-existent', 'proj-1')
      ).resolves.not.toThrow();

      expect(useConversationsStore.getState().conversations).toEqual([]);
    });

    it('should handle get conversation when list is empty', async () => {
      const conversation = createMockConversation('conv-1', 'proj-1', 'Test');

      getConversationMock.mockResolvedValue(conversation);

      const result = await useConversationsStore.getState().getConversation('conv-1', 'proj-1');

      expect(result).toEqual(conversation);
      expect(useConversationsStore.getState().currentConversation).toEqual(conversation);
    });
  });

  describe('State Immutability', () => {
    it('should reset properly after multiple state changes', async () => {
      const conversation = createMockConversation('conv-1', 'proj-1', 'Test');

      useConversationsStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        conversationsLoading: true,
        conversationsError: 'Error',
        isNewConversationPending: true,
      });

      // Reset
      useConversationsStore.getState().reset();

      // Verify all state reset
      const state = useConversationsStore.getState();
      expect(state.conversations).toEqual([]);
      expect(state.currentConversation).toBe(null);
      expect(state.conversationsLoading).toBe(false);
      expect(state.conversationsError).toBe(null);
      expect(state.isNewConversationPending).toBe(false);
    });
  });
});
