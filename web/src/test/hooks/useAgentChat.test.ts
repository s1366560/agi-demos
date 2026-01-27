
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAgentChat } from '../../hooks/useAgentChat';
import { useProjectStore } from '../../stores/project';
import { useAgentStore } from '../../stores/agent';
import { useParams, useNavigate } from 'react-router-dom';
import { agentService } from '../../services/agentService';

// Mock selector functions
const mockUseMessages = vi.fn();
const mockUseMessagesLoading = vi.fn();
const mockUseHasEarlierMessages = vi.fn();

// Mock dependencies
vi.mock('react-router-dom', () => ({
  useParams: vi.fn(),
  useNavigate: vi.fn(),
}));

vi.mock('../../stores/project', () => ({
  useProjectStore: vi.fn(),
}));

vi.mock('../../stores/agent', () => ({
  useAgentStore: vi.fn(),
  useMessages: () => mockUseMessages(),
  useMessagesLoading: () => mockUseMessagesLoading(),
  useHasEarlierMessages: () => mockUseHasEarlierMessages(),
}));

// Also mock the store directly for getState() calls
const mockAgentStoreInstance = {
  getState: vi.fn(() => ({
    currentConversation: null,
    isStreaming: false,
  })),
};

(useAgentStore as any).getState = mockAgentStoreInstance.getState.bind(mockAgentStoreInstance);

vi.mock('../../services/agentService', () => ({
  agentService: {
    connect: vi.fn(() => Promise.resolve()),
    isConnected: vi.fn(() => false),
    stopChat: vi.fn(),
  },
}));

// Mock Antd Form
vi.mock('antd', () => ({
  Form: {
    useForm: () => [{ validateFields: vi.fn(), resetFields: vi.fn() }],
  },
  message: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

describe('useAgentChat', () => {
  const mockNavigate = vi.fn();
  const mockSetCurrentProject = vi.fn();
  const mockListConversations = vi.fn();
  const mockCreateConversation = vi.fn();
  const mockSetCurrentConversation = vi.fn();
  const mockSendMessage = vi.fn();
  const mockStopChat = vi.fn();
  const mockGetPlanModeStatus = vi.fn();
  const mockLoadEarlierMessages = vi.fn();

  const mockStoreState = {
    conversations: [],
    currentConversation: null,
    isStreaming: false,
  };

  beforeEach(() => {
    (useNavigate as any).mockReturnValue(mockNavigate);
    (useParams as any).mockReturnValue({ projectId: 'p1' });

    (useProjectStore as any).mockReturnValue({
      currentProject: { id: 'p1' },
      projects: [{ id: 'p1' }],
      setCurrentProject: mockSetCurrentProject,
    });

    // Mock selector functions
    mockUseMessages.mockReturnValue([]);
    mockUseMessagesLoading.mockReturnValue(false);
    mockUseHasEarlierMessages.mockReturnValue(false);

    const mockAgentStore = {
      conversations: [],
      currentConversation: null,
      listConversations: mockListConversations,
      createConversation: mockCreateConversation,
      setCurrentConversation: mockSetCurrentConversation,
      sendMessage: mockSendMessage,
      stopChat: mockStopChat,
      isStreaming: false,
      getPlanModeStatus: mockGetPlanModeStatus,
      loadEarlierMessages: mockLoadEarlierMessages,
      // Add other required store properties
      currentWorkPlan: null,
      currentStepNumber: null,
      currentThought: null,
      currentToolCall: null,
      executionTimeline: [],
      toolExecutionHistory: [],
      matchedPattern: null,
      currentPlan: null,
      planModeStatus: null,
      planLoading: false,
      enterPlanMode: vi.fn(),
      exitPlanMode: vi.fn(),
      updatePlan: vi.fn(),
      assistantDraftContent: null,
      isTextStreaming: false,
      isNewConversationPending: false,
      getState: () => mockStoreState,
    };

    (useAgentStore as any).mockReturnValue(mockAgentStore);
  });

  it('initializes correctly', () => {
    const { result } = renderHook(() => useAgentChat());
    expect(result.current.projectId).toBe('p1');
    expect(mockListConversations).toHaveBeenCalledWith('p1');
    expect(typeof result.current.handleLoadEarlier).toBe('function');
  });

  it('handles sending a message', async () => {
    const { result } = renderHook(() => useAgentChat());

    mockCreateConversation.mockResolvedValue({ id: 'c1', project_id: 'p1' });

    await act(async () => {
      await result.current.handleSend('Hello');
    });

    expect(mockCreateConversation).toHaveBeenCalledWith('p1');
    expect(mockSetCurrentConversation).toHaveBeenCalled();
    expect(mockSendMessage).toHaveBeenCalledWith('c1', 'Hello', 'p1');
  });
});
