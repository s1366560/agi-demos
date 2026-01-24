
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAgentChat } from '../../hooks/useAgentChat';
import { useProjectStore } from '../../stores/project';
import { useAgentStore } from '../../stores/agent';
import { useParams, useNavigate } from 'react-router-dom';

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

  beforeEach(() => {
    (useNavigate as any).mockReturnValue(mockNavigate);
    (useParams as any).mockReturnValue({ projectId: 'p1' });

    (useProjectStore as any).mockReturnValue({
      currentProject: { id: 'p1' },
      projects: [{ id: 'p1' }],
      setCurrentProject: mockSetCurrentProject,
    });

    (useAgentStore as any).mockReturnValue({
      conversations: [],
      currentConversation: null,
      listConversations: mockListConversations,
      createConversation: mockCreateConversation,
      setCurrentConversation: mockSetCurrentConversation,
      sendMessage: mockSendMessage,
      stopChat: mockStopChat,
      isStreaming: false,
      messages: [],
      messagesLoading: false,
      getPlanModeStatus: mockGetPlanModeStatus,
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
    });
  });

  it('initializes correctly', () => {
    const { result } = renderHook(() => useAgentChat());
    expect(result.current.projectId).toBe('p1');
    expect(mockListConversations).toHaveBeenCalledWith('p1');
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
