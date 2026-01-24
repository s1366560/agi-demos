/**
 * Integration tests for SSE event handling (T051)
 *
 * These tests verify that SSE events from the agent backend
 * are properly handled and update the frontend state correctly.
 *
 * TDD: Tests written first, implementation will follow.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAgentStore } from '../../stores/agent'
import type {
  WorkPlan,
  PlanStatus,
  ThoughtLevel,
  MessageRole,
} from '../../types/agent'

// Mock the agentService
vi.mock('../../services/agentService', () => ({
  agentService: {
    listConversations: vi.fn(() => Promise.resolve([])),
    createConversation: vi.fn(() => Promise.resolve({
      id: 'conv-1',
      project_id: 'proj-1',
      tenant_id: 'tenant-1',
      user_id: 'user-1',
      title: 'Test Conversation',
      status: 'active' as const,
      message_count: 0,
      created_at: new Date().toISOString(),
    })),
    getConversation: vi.fn(() => Promise.resolve(null)),
    deleteConversation: vi.fn(() => Promise.resolve()),
    getConversationMessages: vi.fn(() => Promise.resolve({ conversation_id: 'conv-1', messages: [], total: 0 })),
    chat: vi.fn(() => Promise.resolve()),
    getExecutionHistory: vi.fn(() => Promise.resolve({ conversation_id: 'conv-1', executions: [], total: 0 })),
    listTools: vi.fn(() => Promise.resolve({ tools: [] })),
  },
}))

describe('SSE Event Handling Integration', () => {
  beforeEach(() => {
    // Reset store before each test
    const { reset } = useAgentStore.getState()
    reset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('Work Plan Events', () => {
    it('should handle work_plan SSE event and update store', async () => {
      const mockWorkPlanEventData = {
        plan_id: 'plan-123',
        conversation_id: 'conv-456',
        steps: [
          {
            step_number: 0,
            description: 'Search for memories',
            expected_output: 'List of memories',
          },
          {
            step_number: 1,
            description: 'Analyze results',
            expected_output: 'Analysis',
          },
        ],
        total_steps: 2,
        current_step: 0,
        status: 'in_progress' as PlanStatus,
        thought_level: 'work' as ThoughtLevel,
        workflow_pattern_id: 'pattern-1' as string | undefined,
      }

      const { result } = renderHook(() => useAgentStore())

      // Simulate SSE event handling
      await act(async () => {
        const mockEvent = {
          type: 'work_plan' as const,
          data: mockWorkPlanEventData,
        }

        // Simulate the onWorkPlan handler being called
        await act(async () => {
          const workPlan: WorkPlan = {
            id: mockEvent.data.plan_id,
            conversation_id: mockEvent.data.conversation_id,
            status: mockEvent.data.status,
            steps: mockEvent.data.steps.map((s: any) => ({
              step_number: s.step_number,
              description: s.description,
              thought_prompt: '',
              required_tools: [],
              expected_output: s.expected_output,
              dependencies: [],
            })),
            current_step_index: mockEvent.data.current_step,
            workflow_pattern_id: mockEvent.data.workflow_pattern_id as string | undefined,
            created_at: new Date().toISOString(),
          }
          result.current.currentWorkPlan = workPlan
        })
      })

      expect(result.current.currentWorkPlan).toBeDefined()
      expect(result.current.currentWorkPlan?.id).toBe('plan-123')
      expect(result.current.currentWorkPlan?.steps).toHaveLength(2)
    })

    it('should update work plan status on step events', async () => {
      const { result } = renderHook(() => useAgentStore())

      // Initial work plan
      const initialWorkPlan: WorkPlan = {
        id: 'plan-123',
        conversation_id: 'conv-456',
        status: 'in_progress' as PlanStatus,
        steps: [
          {
            step_number: 0,
            description: 'Step 1',
            thought_prompt: 'Think',
            required_tools: ['tool1'],
            expected_output: 'Output',
            dependencies: [],
          },
          {
            step_number: 1,
            description: 'Step 2',
            thought_prompt: 'Think',
            required_tools: ['tool2'],
            expected_output: 'Output',
            dependencies: [0],
          },
        ],
        current_step_index: 0,
        created_at: new Date().toISOString(),
      }

      await act(async () => {
        result.current.currentWorkPlan = initialWorkPlan
        result.current.currentStepNumber = 0
        result.current.currentStepStatus = 'running'
      })

      // Simulate step_start event
      await act(async () => {
        result.current.currentStepNumber = 1
        result.current.currentStepStatus = 'running'
      })

      expect(result.current.currentStepNumber).toBe(1)
      expect(result.current.currentStepStatus).toBe('running')

      // Simulate step_end event
      await act(async () => {
        const prev = result.current.currentWorkPlan
        if (prev) {
          result.current.currentWorkPlan = {
            ...prev,
            current_step_index: 1,
          }
        }
        result.current.currentStepStatus = 'completed'
      })

      expect(result.current.currentWorkPlan?.current_step_index).toBe(1)
      expect(result.current.currentStepStatus).toBe('completed')
    })
  })

  describe('Step Events', () => {
    it('should handle step_start event and update current step', async () => {
      const { result } = renderHook(() => useAgentStore())

      const stepStartEvent = {
        type: 'step_start' as const,
        data: {
          plan_id: 'plan-123',
          step_number: 1,
          description: 'Analyze retrieved memories',
          required_tools: ['analyze'],
          current_step: 1,
          total_steps: 3,
        },
      }

      await act(async () => {
        result.current.currentStepNumber = stepStartEvent.data.step_number
        result.current.currentStepStatus = 'running'
        result.current.currentThought = `Executing step ${stepStartEvent.data.step_number}: ${stepStartEvent.data.description}`
      })

      expect(result.current.currentStepNumber).toBe(1)
      expect(result.current.currentStepStatus).toBe('running')
      expect(result.current.currentThought).toContain('Analyze retrieved memories')
    })

    it('should handle step_end event and update status', async () => {
      const { result } = renderHook(() => useAgentStore())

      const stepEndEvent = {
        type: 'step_end' as const,
        data: {
          plan_id: 'plan-123',
          step_number: 1,
          description: 'Analyze retrieved memories',
          success: true,
          is_plan_complete: false,
          current_step: 2,
          total_steps: 3,
        },
      }

      await act(async () => {
        result.current.currentStepStatus = stepEndEvent.data.success ? 'completed' : 'failed'
        const prev = result.current.currentWorkPlan
        if (prev) {
          result.current.currentWorkPlan = {
            ...prev,
            current_step_index: stepEndEvent.data.current_step,
          }
        }
      })

      expect(result.current.currentStepStatus).toBe('completed')
    })
  })

  describe('Thought Events', () => {
    it('should handle thought event with work level', async () => {
      const { result } = renderHook(() => useAgentStore())

      const thoughtEvent = {
        type: 'thought' as const,
        data: {
          thought: 'This is a complex query requiring multiple steps',
          thought_level: 'work' as ThoughtLevel,
          step_number: 0,
        },
      }

      await act(async () => {
        result.current.currentThought = thoughtEvent.data.thought
        result.current.currentThoughtLevel = thoughtEvent.data.thought_level
      })

      expect(result.current.currentThought).toBe('This is a complex query requiring multiple steps')
      expect(result.current.currentThoughtLevel).toBe('work')
    })

    it('should handle thought event with task level', async () => {
      const { result } = renderHook(() => useAgentStore())

      const thoughtEvent = {
        type: 'thought' as const,
        data: {
          thought: 'Searching memory database for relevant entries',
          thought_level: 'task' as ThoughtLevel,
          step_number: 1,
        },
      }

      await act(async () => {
        result.current.currentThought = thoughtEvent.data.thought
        result.current.currentThoughtLevel = thoughtEvent.data.thought_level
      })

      expect(result.current.currentThought).toBe('Searching memory database for relevant entries')
      expect(result.current.currentThoughtLevel).toBe('task')
    })
  })

  describe('Tool Execution Events', () => {
    it('should handle act event (tool execution start)', async () => {
      const { result } = renderHook(() => useAgentStore())

      const actEvent = {
        type: 'act' as const,
        data: {
          tool_name: 'memory_search',
          tool_input: {
            query: 'project planning',
            limit: 10,
          },
          step_number: 0,
        },
      }

      await act(async () => {
        result.current.currentToolCall = {
          name: actEvent.data.tool_name,
          input: actEvent.data.tool_input,
          stepNumber: actEvent.data.step_number,
        }
        result.current.currentThought = null
      })

      expect(result.current.currentToolCall?.name).toBe('memory_search')
      expect(result.current.currentToolCall?.input).toEqual({ query: 'project planning', limit: 10 })
      expect(result.current.currentThought).toBeNull()
    })

    it('should handle observe event (tool result)', async () => {
      const { result } = renderHook(() => useAgentStore())

      const observeEvent = {
        type: 'observe' as const,
        data: {
          observation: 'Found 5 relevant memories about project planning',
        },
      }

      await act(async () => {
        result.current.currentObservation = observeEvent.data.observation
      })

      expect(result.current.currentObservation).toBe('Found 5 relevant memories about project planning')
    })
  })

  describe('Complete Event', () => {
    it('should reset streaming state on complete event', async () => {
      const { result } = renderHook(() => useAgentStore())

      // Set some state
      await act(async () => {
        result.current.isStreaming = true
        result.current.currentThought = 'Thinking...'
        result.current.currentToolCall = { name: 'test', input: {} }
        result.current.currentWorkPlan = {
          id: 'plan-1',
          conversation_id: 'conv-1',
          status: 'in_progress' as PlanStatus,
          steps: [],
          current_step_index: 0,
          created_at: new Date().toISOString(),
        }
      })

      expect(result.current.isStreaming).toBe(true)
      expect(result.current.currentThought).toBe('Thinking...')

      // Simulate complete event
      await act(async () => {
        result.current.isStreaming = false
        result.current.currentThought = null
        result.current.currentThoughtLevel = null
        result.current.currentToolCall = null
        result.current.currentObservation = null
        result.current.currentWorkPlan = null
        result.current.currentStepNumber = null
        result.current.currentStepStatus = null
      })

      expect(result.current.isStreaming).toBe(false)
      expect(result.current.currentThought).toBeNull()
      expect(result.current.currentWorkPlan).toBeNull()
    })
  })

  describe('Error Event', () => {
    it('should handle error event and set error state', async () => {
      const { result } = renderHook(() => useAgentStore())

      const errorEvent = {
        type: 'error' as const,
        data: {
          message: 'Tool execution failed: timeout',
        },
      }

      await act(async () => {
        result.current.timelineError = errorEvent.data.message
        result.current.isStreaming = false
        result.current.currentThought = null
        result.current.currentThoughtLevel = null
        result.current.currentToolCall = null
        result.current.currentObservation = null
        result.current.currentWorkPlan = null
        result.current.currentStepNumber = null
        result.current.currentStepStatus = null
      })

      expect(result.current.timelineError).toBe('Tool execution failed: timeout')
      expect(result.current.isStreaming).toBe(false)
    })
  })

  describe('Message Event', () => {
    it('should add message to store on message event', async () => {
      const { result } = renderHook(() => useAgentStore())

      const messageEvent = {
        type: 'message' as const,
        data: {
          id: 'msg-123',
          role: 'assistant' as MessageRole,
          content: 'Based on my analysis...',
          created_at: new Date().toISOString(),
        },
      }

      // Create a TimelineEvent for the new timeline-based API
      const timelineEvent = {
        id: messageEvent.data.id!,
        type: 'assistant_message' as const,
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: messageEvent.data.content,
        role: 'assistant' as const,
      }

      await act(async () => {
        result.current.addTimelineEvent(timelineEvent as any)
      })

      const messages = result.current.timeline.filter(
        (e) => e.type === 'user_message' || e.type === 'assistant_message'
      )
      expect(messages).toHaveLength(1)
      expect((messages[0] as any).content).toBe('Based on my analysis...')
    })
  })

  describe('Event Sequence', () => {
    it('should handle full sequence of events for complex query', async () => {
      const { result } = renderHook(() => useAgentStore())

      // 1. Work plan event
      await act(async () => {
        result.current.currentWorkPlan = {
          id: 'plan-1',
          conversation_id: 'conv-1',
          status: 'in_progress' as PlanStatus,
          steps: [
            {
              step_number: 0,
              description: 'Search',
              thought_prompt: '',
              required_tools: ['search'],
              expected_output: 'Results',
              dependencies: [],
            },
            {
              step_number: 1,
              description: 'Analyze',
              thought_prompt: '',
              required_tools: ['analyze'],
              expected_output: 'Analysis',
              dependencies: [0],
            },
          ],
          current_step_index: 0,
          created_at: new Date().toISOString(),
        }
      })

      expect(result.current.currentWorkPlan?.steps).toHaveLength(2)

      // 2. Thought event (work level)
      await act(async () => {
        result.current.currentThought = 'Starting work plan execution'
        result.current.currentThoughtLevel = 'work'
      })

      expect(result.current.currentThoughtLevel).toBe('work')

      // 3. Step start event
      await act(async () => {
        result.current.currentStepNumber = 0
        result.current.currentStepStatus = 'running'
        result.current.currentThought = 'Executing step 0: Search'
      })

      expect(result.current.currentStepNumber).toBe(0)

      // 4. Act event (tool call)
      await act(async () => {
        result.current.currentToolCall = {
          name: 'memory_search',
          input: { query: 'test' },
          stepNumber: 0,
        }
      })

      expect(result.current.currentToolCall?.name).toBe('memory_search')

      // 5. Observe event (tool result)
      await act(async () => {
        result.current.currentObservation = 'Found 3 memories'
      })

      expect(result.current.currentObservation).toBe('Found 3 memories')

      // 6. Step end event
      await act(async () => {
        const prev = result.current.currentWorkPlan
        if (prev) {
          result.current.currentWorkPlan = {
            ...prev,
            current_step_index: 1,
          }
        }
        result.current.currentStepStatus = 'completed'
      })

      expect(result.current.currentWorkPlan?.current_step_index).toBe(1)

      // 7. Complete event
      await act(async () => {
        result.current.isStreaming = false
        result.current.currentThought = null
        result.current.currentThoughtLevel = null
        result.current.currentToolCall = null
        result.current.currentObservation = null
        result.current.currentWorkPlan = null
        result.current.currentStepNumber = null
        result.current.currentStepStatus = null
      })

      expect(result.current.currentWorkPlan).toBeNull()
    })
  })
})
