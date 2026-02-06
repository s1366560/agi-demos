/**
 * Integration tests for usePlanModeEvents hook
 *
 * Tests SSE event handling for plan mode events including:
 * - plan_mode_enter
 * - plan_generated
 * - plan_step_complete
 * - plan_step_failed
 * - reflection_complete
 * - adjustment_applied
 * - plan_mode_completed
 */

import { EventEmitter } from 'events';

import { renderHook, act, waitFor } from '@testing-library/react';
import { vi, beforeEach, afterEach, describe, it, expect } from 'vitest';

import type { AgentEvent } from '../../types/agent';

// Mock the SSE module using factory function
vi.mock('../../services/sse', () => {
  const emitter = new EventEmitter();
  emitter.setMaxListeners(100);

  // Add onPlanEvent method
  (emitter as any).onPlanEvent = function (
    listener: (event: AgentEvent<unknown>) => void
  ): () => void {
    this.on('plan_event', listener);
    return () => this.off('plan_event', listener);
  };

  return {
    sseEmitter: emitter,
    PlanModeEventHandlers: {} as any,
  };
});

// Import after mock
import { usePlanModeEvents } from '../../hooks/usePlanModeEvents';
import { sseEmitter as mockSSEEmitter } from '../../services/sse';

import type { PlanModeEventHandlers } from '../../services/sse';

// Helper to emit events
function emitPlanEvent(event: AgentEvent<unknown>) {
  (mockSSEEmitter as any).emit('plan_event', event);
}

describe('usePlanModeEvents Integration Tests', () => {
  let mockHandlers: {
    onPlanModeEntered: ReturnType<typeof vi.fn>;
    onPlanGenerated: ReturnType<typeof vi.fn>;
    onStepUpdated: ReturnType<typeof vi.fn>;
    onReflectionComplete: ReturnType<typeof vi.fn>;
    onPlanAdjusted: ReturnType<typeof vi.fn>;
    onPlanCompleted: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    // Reset all mocks before each test
    vi.clearAllMocks();
    mockSSEEmitter.removeAllListeners();

    // Create fresh mock handlers for each test
    mockHandlers = {
      onPlanModeEntered: vi.fn(),
      onPlanGenerated: vi.fn(),
      onStepUpdated: vi.fn(),
      onReflectionComplete: vi.fn(),
      onPlanAdjusted: vi.fn(),
      onPlanCompleted: vi.fn(),
    };
  });

  afterEach(() => {
    // Cleanup: remove all listeners after each test
    mockSSEEmitter.removeAllListeners();
  });

  describe('Event Registration and Cleanup', () => {
    it('should register SSE event listeners on mount', () => {
      const { unmount } = renderHook(() => usePlanModeEvents(mockHandlers));

      // Verify that listeners are registered
      const listenerCount = mockSSEEmitter.listenerCount('plan_event');
      expect(listenerCount).toBeGreaterThan(0);

      unmount();
    });

    it('should clean up event listeners on unmount', () => {
      const { unmount } = renderHook(() => usePlanModeEvents(mockHandlers));

      const listenerCountBefore = mockSSEEmitter.listenerCount('plan_event');
      expect(listenerCountBefore).toBeGreaterThan(0);

      // Unmount the hook
      act(() => {
        unmount();
      });

      // Verify listeners are removed
      const listenerCountAfter = mockSSEEmitter.listenerCount('plan_event');
      expect(listenerCountAfter).toBe(0);
    });

    it('should re-register listeners when handlers change', () => {
      const { rerender } = renderHook(({ handlers }) => usePlanModeEvents(handlers), {
        initialProps: {
          handlers: mockHandlers,
        },
      });

      const firstListenerCount = mockSSEEmitter.listenerCount('plan_event');

      // Update handlers
      const newHandlers = {
        onPlanModeEntered: vi.fn(),
        onPlanGenerated: vi.fn(),
        onStepUpdated: vi.fn(),
        onReflectionComplete: vi.fn(),
        onPlanAdjusted: vi.fn(),
        onPlanCompleted: vi.fn(),
      };

      act(() => {
        rerender({ handlers: newHandlers });
      });

      const secondListenerCount = mockSSEEmitter.listenerCount('plan_event');

      // Should still have listeners (may have removed old ones and added new ones)
      expect(secondListenerCount).toBeGreaterThan(0);
    });
  });

  describe('plan_mode_entered Event', () => {
    it('should call onPlanModeEntered when plan_mode_entered event is received', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const eventData = {
        type: 'plan_mode_enter' as const,
        data: {
          conversation_id: 'conv-123',
          plan_id: 'plan-456',
          plan_title: 'Test Plan',
        },
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onPlanModeEntered).toHaveBeenCalledTimes(1);
        expect(mockHandlers.onPlanModeEntered).toHaveBeenCalledWith(eventData.data);
      });
    });

    it('should handle missing onPlanModeEntered handler gracefully', async () => {
      const handlersWithoutModeEnter: PlanModeEventHandlers = {
        onPlanGenerated: vi.fn(),
        onStepUpdated: vi.fn(),
        onReflectionComplete: vi.fn(),
        onPlanAdjusted: vi.fn(),
        onPlanCompleted: vi.fn(),
      };

      renderHook(() => usePlanModeEvents(handlersWithoutModeEnter));

      const eventData = {
        type: 'plan_mode_enter' as const,
        data: {
          conversation_id: 'conv-123',
          plan_id: 'plan-456',
          plan_title: 'Test Plan',
        },
      };

      // Should not throw
      await act(async () => {
        emitPlanEvent(eventData);
      });

      // Other handlers should not be called
      expect(handlersWithoutModeEnter.onPlanGenerated).not.toHaveBeenCalled();
    });
  });

  describe('plan_generated Event', () => {
    it('should call onPlanGenerated with plan data', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const planData = {
        id: 'plan-123',
        conversation_id: 'conv-456',
        user_query: 'Test query',
        steps: [
          {
            step_id: 'step-1',
            description: 'Step 1',
            tool_name: 'test_tool',
            tool_input: {},
            dependencies: [],
            status: 'pending' as const,
          },
        ],
        status: 'draft' as const,
        reflection_enabled: true,
        max_reflection_cycles: 3,
        completed_steps: [],
        failed_steps: [],
        progress_percentage: 0,
        is_complete: false,
      };

      const eventData = {
        type: 'plan_created' as const,
        data: planData,
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onPlanGenerated).toHaveBeenCalledWith({
          plan: planData,
        });
      });
    });
  });

  describe('plan_step_complete Event', () => {
    it('should call onStepUpdated when step completes successfully', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const stepData = {
        step_id: 'step-1',
        status: 'completed' as const,
        result: 'Step completed successfully',
      };

      const eventData = {
        type: 'plan_step_complete' as const,
        data: {
          plan_id: 'plan-123',
          ...stepData,
        },
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onStepUpdated).toHaveBeenCalledWith({
          step_id: 'step-1',
          step: expect.objectContaining(stepData),
        });
      });
    });
  });

  describe('plan_step_failed Event', () => {
    it('should call onStepUpdated when step fails', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const stepData = {
        step_id: 'step-2',
        status: 'failed' as const,
        error: 'Step execution failed',
      };

      const eventData = {
        type: 'plan_step_complete' as const,
        data: {
          plan_id: 'plan-123',
          step_id: 'step-2',
          status: 'failed',
          error: 'Step execution failed',
        },
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onStepUpdated).toHaveBeenCalledWith({
          step_id: 'step-2',
          step: expect.objectContaining({
            status: 'failed',
            error: 'Step execution failed',
          }),
        });
      });
    });
  });

  describe('reflection_complete Event', () => {
    it('should call onReflectionComplete with reflection data', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const reflectionData = {
        plan_id: 'plan-123',
        assessment: 'needs_adjustment' as const,
        reasoning: 'Plan needs adjustment based on results',
        has_adjustments: true,
        adjustment_count: 2,
      };

      const eventData = {
        type: 'reflection_complete' as const,
        data: reflectionData,
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onReflectionComplete).toHaveBeenCalledWith({
          reflection: reflectionData,
        });
      });
    });

    it('should handle reflection with no adjustments', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const reflectionData = {
        plan_id: 'plan-123',
        assessment: 'on_track' as const,
        reasoning: 'Plan is progressing well',
        has_adjustments: false,
        adjustment_count: 0,
      };

      const eventData = {
        type: 'reflection_complete' as const,
        data: reflectionData,
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onReflectionComplete).toHaveBeenCalledWith({
          reflection: reflectionData,
        });
      });
    });
  });

  describe('adjustment_applied Event', () => {
    it('should call onPlanAdjusted with adjustment data', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const adjustments = [
        {
          step_id: 'step-1',
          adjustment_type: 'retry' as const,
          reason: 'Tool call failed',
        },
        {
          step_id: 'step-2',
          adjustment_type: 'modify' as const,
          reason: 'Update parameters',
          new_tool_input: { param: 'new_value' },
        },
      ];

      const eventData = {
        type: 'adjustment_applied' as const,
        data: {
          plan_id: 'plan-123',
          adjustment_count: 2,
          adjustments,
        },
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onPlanAdjusted).toHaveBeenCalledWith({
          adjustments,
        });
      });
    });
  });

  describe('plan_mode_completed Event', () => {
    it('should call onPlanCompleted when plan execution completes', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const completionData = {
        plan_id: 'plan-123',
        status: 'completed' as const,
        completed_steps: 5,
        failed_steps: 0,
      };

      const eventData = {
        type: 'plan_execution_complete' as const,
        data: completionData,
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onPlanCompleted).toHaveBeenCalledWith({
          plan_id: 'plan-123',
          status: 'completed',
        });
      });
    });

    it('should handle plan completion with failures', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const completionData = {
        plan_id: 'plan-123',
        status: 'failed' as const,
        completed_steps: 3,
        failed_steps: 2,
      };

      const eventData = {
        type: 'plan_execution_complete' as const,
        data: completionData,
      };

      act(() => {
        emitPlanEvent(eventData);
      });

      await waitFor(() => {
        expect(mockHandlers.onPlanCompleted).toHaveBeenCalledWith({
          plan_id: 'plan-123',
          status: 'failed',
        });
      });
    });
  });

  describe('Event Sequencing', () => {
    it('should handle multiple events in correct order', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const events = [
        {
          type: 'plan_mode_enter' as const,
          data: { conversation_id: 'conv-1', plan_id: 'plan-1', plan_title: 'Test' },
        },
        {
          type: 'plan_created' as const,
          data: { id: 'plan-1', conversation_id: 'conv-1' },
        },
        {
          type: 'plan_step_complete' as const,
          data: { plan_id: 'plan-1', step_id: 'step-1', status: 'completed', result: 'Done' },
        },
        {
          type: 'reflection_complete' as const,
          data: {
            plan_id: 'plan-1',
            assessment: 'on_track',
            reasoning: 'Good',
            has_adjustments: false,
            adjustment_count: 0,
          },
        },
        {
          type: 'plan_execution_complete' as const,
          data: { plan_id: 'plan-1', status: 'completed', completed_steps: 1, failed_steps: 0 },
        },
      ];

      for (const event of events) {
        act(() => {
          emitPlanEvent(event);
        });
      }

      await waitFor(() => {
        expect(mockHandlers.onPlanModeEntered).toHaveBeenCalledTimes(1);
        expect(mockHandlers.onPlanGenerated).toHaveBeenCalledTimes(1);
        expect(mockHandlers.onStepUpdated).toHaveBeenCalledTimes(1);
        expect(mockHandlers.onReflectionComplete).toHaveBeenCalledTimes(1);
        expect(mockHandlers.onPlanCompleted).toHaveBeenCalledTimes(1);
      });
    });

    it('should handle rapid sequential events', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      // Emit 10 step completion events rapidly
      for (let i = 0; i < 10; i++) {
        const eventData = {
          type: 'plan_step_complete' as const,
          data: {
            plan_id: 'plan-123',
            step_id: `step-${i}`,
            status: 'completed' as const,
            result: `Step ${i} completed`,
          },
        };

        act(() => {
          emitPlanEvent(eventData);
        });
      }

      await waitFor(() => {
        expect(mockHandlers.onStepUpdated).toHaveBeenCalledTimes(10);
      });
    });
  });

  describe('Error Handling', () => {
    it('should handle malformed events gracefully', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation();

      renderHook(() => usePlanModeEvents(mockHandlers));

      // Emit event with missing required fields
      const malformedEvent = {
        type: 'plan_step_complete' as const,
        data: {
          step_id: 'step-1',
          status: 'completed',
          // Missing result
        },
      };

      act(() => {
        emitPlanEvent(malformedEvent);
      });

      // Handler is still called with whatever data is available
      expect(mockHandlers.onStepUpdated).toHaveBeenCalled();

      consoleSpy.mockRestore();
    });

    it('should handle exceptions in event handlers gracefully', async () => {
      let handlerCalled = false;
      const errorHandler = vi.fn(() => {
        handlerCalled = true;
        throw new Error('Handler error');
      });

      renderHook(() =>
        usePlanModeEvents({
          onPlanModeEntered: errorHandler,
          onPlanGenerated: vi.fn(),
          onStepUpdated: vi.fn(),
          onReflectionComplete: vi.fn(),
          onPlanAdjusted: vi.fn(),
          onPlanCompleted: vi.fn(),
        })
      );

      const eventData = {
        type: 'plan_mode_enter' as const,
        data: {
          conversation_id: 'conv-123',
          plan_id: 'plan-456',
          plan_title: 'Test Plan',
        },
      };

      // Should not throw despite handler error
      await act(async () => {
        emitPlanEvent(eventData);
      });

      // Handler was called
      expect(handlerCalled).toBe(true);
    });
  });

  describe('Unknown Event Types', () => {
    it('should ignore unknown event types', async () => {
      renderHook(() => usePlanModeEvents(mockHandlers));

      const unknownEvent = {
        type: 'unknown_event_type' as any,
        data: {},
      };

      act(() => {
        emitPlanEvent(unknownEvent);
      });

      // No handlers should be called
      expect(mockHandlers.onPlanModeEntered).not.toHaveBeenCalled();
      expect(mockHandlers.onPlanGenerated).not.toHaveBeenCalled();
      expect(mockHandlers.onStepUpdated).not.toHaveBeenCalled();
      expect(mockHandlers.onReflectionComplete).not.toHaveBeenCalled();
      expect(mockHandlers.onPlanAdjusted).not.toHaveBeenCalled();
      expect(mockHandlers.onPlanCompleted).not.toHaveBeenCalled();
    });
  });
});
