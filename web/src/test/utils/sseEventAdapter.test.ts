/**
 * Tests for SSE Event Adapter
 *
 * This test suite verifies that sseEventAdapter correctly converts
 * SSE AgentEvent types to TimelineEvent format, ensuring consistency
 * between streaming and historical messages.
 *
 * TDD Phase 3: SSE to TimelineEvent Converter
 */

import { describe, it, expect, beforeEach } from 'vitest';

import {
  sseEventToTimeline,
  batchConvertSSEEvents,
  generateTimelineEventId,
  getNextSequenceNumber,
  resetSequenceCounter,
  appendSSEEventToTimeline,
  isSupportedEventType,
} from '../../utils/sseEventAdapter';

import type {
  AgentEvent,
  MessageEventData,
  ThoughtEventData,
  ActEventData,
  ObserveEventData,
  WorkPlanEventData,
  StepStartEventData,
  StepEndEventData,
  CompleteEventData,
  TextDeltaEventData,
  TextEndEventData,
} from '../../types/agent';

describe('SSE Event Adapter', () => {
  beforeEach(() => {
    // Reset sequence counter before each test
    resetSequenceCounter();
  });

  describe('Typewriter Effect Support (text_*)', () => {
    it('should support text_delta event type', () => {
      expect(isSupportedEventType('text_delta')).toBe(true);
    });

    it('should support text_start event type', () => {
      expect(isSupportedEventType('text_start')).toBe(true);
    });

    it('should support text_end event type', () => {
      expect(isSupportedEventType('text_end')).toBe(true);
    });

    it('should convert text_delta event to TimelineEvent', () => {
      const event: AgentEvent<TextDeltaEventData> = {
        type: 'text_delta',
        data: { delta: 'Hello' },
      };

      const result = sseEventToTimeline(event, 1);

      expect(result).not.toBeNull();
      expect(result?.type).toBe('text_delta');
      if (result?.type === 'text_delta') {
        expect(result.content).toBe('Hello');
      }
    });

    it('should append text_delta to timeline', () => {
      const existingTimeline: any[] = [];
      const event: AgentEvent<TextDeltaEventData> = {
        type: 'text_delta',
        data: { delta: 'World' },
      };

      const result = appendSSEEventToTimeline(existingTimeline, event);

      expect(result).toHaveLength(1);
      expect(result[0].type).toBe('text_delta');
      if (result[0].type === 'text_delta') {
        expect(result[0].content).toBe('World');
      }
    });

    it('should handle multiple text_delta events in sequence', () => {
      let timeline: any[] = [];

      const deltas = ['Hello', ' ', 'World', '!'];
      deltas.forEach((delta) => {
        const event: AgentEvent<TextDeltaEventData> = {
          type: 'text_delta',
          data: { delta },
        };
        timeline = appendSSEEventToTimeline(timeline, event);
      });

      expect(timeline).toHaveLength(4);
      if (timeline[0].type === 'text_delta') expect(timeline[0].content).toBe('Hello');
      if (timeline[1].type === 'text_delta') expect(timeline[1].content).toBe(' ');
      if (timeline[2].type === 'text_delta') expect(timeline[2].content).toBe('World');
      if (timeline[3].type === 'text_delta') expect(timeline[3].content).toBe('!');
    });

    it('should convert text_start event to TimelineEvent', () => {
      const event: AgentEvent<Record<string, unknown>> = {
        type: 'text_start',
        data: {},
      };

      const result = sseEventToTimeline(event, 1);

      expect(result).not.toBeNull();
      expect(result?.type).toBe('text_start');
    });

    it('should convert text_end event to TimelineEvent', () => {
      const event: AgentEvent<TextEndEventData> = {
        type: 'text_end',
        data: { full_text: 'Hello World!' },
      };

      const result = sseEventToTimeline(event, 1);

      expect(result).not.toBeNull();
      expect(result?.type).toBe('text_end');
      if (result?.type === 'text_end') {
        expect(result.fullText).toBe('Hello World!');
      }
    });
  });
  describe('ID Generation', () => {
    it('should generate unique IDs for events', () => {
      const id1 = generateTimelineEventId('thought');
      const id2 = generateTimelineEventId('thought');

      expect(id1).not.toBe(id2);
      expect(id1).toMatch(/^thought-/);
      expect(id2).toMatch(/^thought-/);
    });

    it('should include timestamp in ID for uniqueness', () => {
      const before = Date.now();
      const id = generateTimelineEventId('act');
      const after = Date.now();

      const timestampPart = id.split('-')[1];
      const timestamp = parseInt(timestampPart, 16); // Hex timestamp

      expect(timestamp).toBeGreaterThanOrEqual(Math.floor(before / 1000));
      expect(timestamp).toBeLessThanOrEqual(Math.floor(after / 1000) + 1);
    });

    it('should support custom ID prefix', () => {
      const id = generateTimelineEventId('custom', 'abc');

      expect(id).toMatch(/^abc-/);
    });
  });

  describe('Sequence Number Management', () => {
    it('should start sequence from 1', () => {
      const seq1 = getNextSequenceNumber();
      const seq2 = getNextSequenceNumber();

      expect(seq1).toBe(1);
      expect(seq2).toBe(2);
    });

    it('should increment sequence for each call', () => {
      const sequences = [
        getNextSequenceNumber(),
        getNextSequenceNumber(),
        getNextSequenceNumber(),
        getNextSequenceNumber(),
      ];

      expect(sequences).toEqual([1, 2, 3, 4]);
    });

    it('should reset sequence when requested', () => {
      getNextSequenceNumber(); // 1
      getNextSequenceNumber(); // 2
      getNextSequenceNumber(); // 3

      const afterReset = getNextSequenceNumber(true); // Reset

      expect(afterReset).toBe(1);
    });
  });

  describe('SSE to TimelineEvent Conversion', () => {
    it('should convert user message event', () => {
      const sseEvent: AgentEvent<MessageEventData> = {
        type: 'message',
        data: {
          id: 'msg-1',
          role: 'user',
          content: 'Hello, how are you?',
          created_at: new Date().toISOString(),
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 1);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('user_message');
      expect(timelineEvent?.sequenceNumber).toBe(1);
      if (timelineEvent?.type === 'user_message') {
        expect(timelineEvent.content).toBe('Hello, how are you?');
        expect(timelineEvent.role).toBe('user');
      }
    });

    it('should convert assistant message event', () => {
      const sseEvent: AgentEvent<MessageEventData> = {
        type: 'message',
        data: {
          id: 'msg-2',
          role: 'assistant',
          content: 'I am doing well, thank you!',
          created_at: new Date().toISOString(),
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 2);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('assistant_message');
      expect(timelineEvent?.sequenceNumber).toBe(2);
      if (timelineEvent?.type === 'assistant_message') {
        expect(timelineEvent.content).toBe('I am doing well, thank you!');
        expect(timelineEvent.role).toBe('assistant');
      }
    });

    it('should convert thought event', () => {
      const sseEvent: AgentEvent<ThoughtEventData> = {
        type: 'thought',
        data: {
          thought: 'I need to search for information about...',
          thought_level: 'task',
          step_number: 1,
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 3);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('thought');
      expect(timelineEvent?.sequenceNumber).toBe(3);
      if (timelineEvent?.type === 'thought') {
        expect(timelineEvent.content).toBe('I need to search for information about...');
      }
    });

    it('should convert act event (tool call)', () => {
      const sseEvent: AgentEvent<ActEventData> = {
        type: 'act',
        data: {
          tool_name: 'web_search',
          tool_input: { query: 'TypeScript best practices' },
          step_number: 2,
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 4);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('act');
      expect(timelineEvent?.sequenceNumber).toBe(4);
      if (timelineEvent?.type === 'act') {
        expect(timelineEvent.toolName).toBe('web_search');
        expect(timelineEvent.toolInput).toEqual({ query: 'TypeScript best practices' });
        expect(timelineEvent.execution).toBeDefined();
        expect(timelineEvent.execution?.startTime).toBeGreaterThan(0);
      }
    });

    it('should convert observe event (tool result)', () => {
      const sseEvent: AgentEvent<ObserveEventData> = {
        type: 'observe',
        data: {
          observation: 'Search completed successfully with 10 results',
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 5);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('observe');
      expect(timelineEvent?.sequenceNumber).toBe(5);
      if (timelineEvent?.type === 'observe') {
        expect(timelineEvent.toolOutput).toBe('Search completed successfully with 10 results');
        expect(timelineEvent.isError).toBe(false);
      }
    });

    it('should convert work_plan event', () => {
      const sseEvent: AgentEvent<WorkPlanEventData> = {
        type: 'work_plan',
        data: {
          plan_id: 'plan-1',
          conversation_id: 'conv-1',
          steps: [
            {
              step_number: 1,
              description: 'Search for information',
              expected_output: 'Search results',
            },
            {
              step_number: 2,
              description: 'Summarize findings',
              expected_output: 'Summary',
            },
          ],
          total_steps: 2,
          current_step: 0,
          status: 'planning',
          workflow_pattern_id: 'pattern-1',
          thought_level: 'work',
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 6);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('work_plan');
      expect(timelineEvent?.sequenceNumber).toBe(6);
      if (timelineEvent?.type === 'work_plan') {
        expect(timelineEvent.steps).toHaveLength(2);
        expect(timelineEvent.steps[0].description).toBe('Search for information');
        expect(timelineEvent.status).toBe('planning');
      }
    });

    it('should convert step_start event', () => {
      const sseEvent: AgentEvent<StepStartEventData> = {
        type: 'step_start',
        data: {
          plan_id: 'plan-1',
          step_number: 1,
          description: 'Search for information',
          required_tools: ['web_search'],
          current_step: 1,
          total_steps: 3,
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 7);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('step_start');
      expect(timelineEvent?.sequenceNumber).toBe(7);
      if (timelineEvent?.type === 'step_start') {
        expect(timelineEvent.stepIndex).toBe(1);
        expect(timelineEvent.stepDescription).toBe('Search for information');
      }
    });

    it('should convert step_end event', () => {
      const sseEvent: AgentEvent<StepEndEventData> = {
        type: 'step_end',
        data: {
          plan_id: 'plan-1',
          step_number: 1,
          description: 'Search for information',
          success: true,
          is_plan_complete: false,
          current_step: 1,
          total_steps: 3,
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 8);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('step_end');
      expect(timelineEvent?.sequenceNumber).toBe(8);
      if (timelineEvent?.type === 'step_end') {
        expect(timelineEvent.stepIndex).toBe(1);
        expect(timelineEvent.status).toBe('completed');
      }
    });

    it('should convert complete event to assistant_message', () => {
      const sseEvent: AgentEvent<CompleteEventData> = {
        type: 'complete',
        data: {
          content: 'Based on my research, here are the key points...',
          trace_url: 'https://langfuse.com/trace/123',
          id: 'msg-complete',
          artifacts: [],
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 9);

      expect(timelineEvent).not.toBeNull();
      expect(timelineEvent?.type).toBe('assistant_message');
      expect(timelineEvent?.sequenceNumber).toBe(9);
      if (timelineEvent?.type === 'assistant_message') {
        expect(timelineEvent.content).toBe('Based on my research, here are the key points...');
        expect(timelineEvent.artifacts).toEqual([]);
        expect(timelineEvent.metadata?.traceUrl).toBe('https://langfuse.com/trace/123');
      }
    });

    it('should return null for unsupported event types', () => {
      const unsupportedEvents = [
        { type: 'start', data: {} },
        { type: 'status', data: {} },
        { type: 'cost_update', data: {} },
        { type: 'error', data: { message: 'Error occurred' } },
        { type: 'title_generated', data: { title: 'New Title' } },
      ] as const;

      unsupportedEvents.forEach((event) => {
        const timelineEvent = sseEventToTimeline(event as any, 10);
        expect(timelineEvent).toBeNull();
      });
    });

    it('should handle observe events with errors', () => {
      const sseEvent: AgentEvent<ObserveEventData> = {
        type: 'tool_result',
        data: {
          observation: 'Tool execution failed',
        },
      };

      // When using tool_result type, we need to add error marker
      // For now, test normal observe
      const timelineEvent = sseEventToTimeline(
        {
          type: 'observe',
          data: sseEvent.data,
        },
        11
      );

      expect(timelineEvent).not.toBeNull();
      if (timelineEvent?.type === 'observe') {
        expect(timelineEvent.toolOutput).toBe('Tool execution failed');
        expect(timelineEvent.isError).toBe(false); // Default
      }
    });
  });

  describe('Batch Conversion', () => {
    it('should convert multiple SSE events to timeline', () => {
      const sseEvents: AgentEvent<any>[] = [
        {
          type: 'message',
          data: { role: 'user', content: 'Help me', id: 'm1' },
        },
        {
          type: 'thought',
          data: { thought: 'I should help the user', thought_level: 'task' },
        },
        {
          type: 'act',
          data: { tool_name: 'search', tool_input: { query: 'help' } },
        },
        {
          type: 'observe',
          data: { observation: 'Results found' },
        },
        {
          type: 'complete',
          data: { content: 'Here is the help you need', id: 'm2' },
        },
      ];

      const timelineEvents = batchConvertSSEEvents(sseEvents);

      expect(timelineEvents).toHaveLength(5);
      expect(timelineEvents[0].type).toBe('user_message');
      expect(timelineEvents[1].type).toBe('thought');
      expect(timelineEvents[2].type).toBe('act');
      expect(timelineEvents[3].type).toBe('observe');
      expect(timelineEvents[4].type).toBe('assistant_message');

      // Verify sequence numbers
      expect(timelineEvents[0].sequenceNumber).toBe(1);
      expect(timelineEvents[1].sequenceNumber).toBe(2);
      expect(timelineEvents[2].sequenceNumber).toBe(3);
      expect(timelineEvents[3].sequenceNumber).toBe(4);
      expect(timelineEvents[4].sequenceNumber).toBe(5);
    });

    it('should filter out null events in batch conversion', () => {
      const sseEvents: AgentEvent<any>[] = [
        {
          type: 'message',
          data: { role: 'user', content: 'Hello', id: 'm1' },
        },
        {
          type: 'status', // Unsupported, will be null
          data: { status: 'processing' },
        },
        {
          type: 'cost_update', // Unsupported, will be null
          data: { cost: 0.01 },
        },
        {
          type: 'complete',
          data: { content: 'Done', id: 'm2' },
        },
      ];

      const timelineEvents = batchConvertSSEEvents(sseEvents);

      expect(timelineEvents).toHaveLength(2); // Only 2 valid events
      expect(timelineEvents[0].type).toBe('user_message');
      expect(timelineEvents[1].type).toBe('assistant_message');
    });

    it('should reset sequence number for each batch', () => {
      const batch1: AgentEvent<any>[] = [
        { type: 'message', data: { role: 'user', content: 'A', id: 'm1' } },
        { type: 'message', data: { role: 'assistant', content: 'B', id: 'm2' } },
      ];

      const batch2: AgentEvent<any>[] = [
        { type: 'message', data: { role: 'user', content: 'C', id: 'm3' } },
        { type: 'message', data: { role: 'assistant', content: 'D', id: 'm4' } },
      ];

      const timeline1 = batchConvertSSEEvents(batch1);
      const timeline2 = batchConvertSSEEvents(batch2);

      expect(timeline1[0].sequenceNumber).toBe(1);
      expect(timeline1[1].sequenceNumber).toBe(2);

      expect(timeline2[0].sequenceNumber).toBe(1);
      expect(timeline2[1].sequenceNumber).toBe(2);
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty batch', () => {
      const timelineEvents = batchConvertSSEEvents([]);
      expect(timelineEvents).toEqual([]);
    });

    it('should handle missing optional fields', () => {
      const sseEvent: AgentEvent<ThoughtEventData> = {
        type: 'thought',
        data: {
          thought: 'Minimal thought',
          // thought_level and step_number are optional
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 1);

      expect(timelineEvent).not.toBeNull();
      if (timelineEvent?.type === 'thought') {
        expect(timelineEvent.content).toBe('Minimal thought');
      }
    });

    it('should handle artifacts in message events', () => {
      const sseEvent: AgentEvent<MessageEventData> = {
        type: 'message',
        data: {
          id: 'msg-1',
          role: 'assistant',
          content: 'Generated a chart',
          artifacts: [
            {
              url: 'https://example.com/chart.png',
              mime_type: 'image/png',
              size_bytes: 1024,
            },
          ],
        },
      };

      const timelineEvent = sseEventToTimeline(sseEvent, 1);

      expect(timelineEvent).not.toBeNull();
      if (timelineEvent?.type === 'assistant_message') {
        expect(timelineEvent.artifacts).toBeDefined();
        expect(timelineEvent.artifacts).toHaveLength(1);
        expect(timelineEvent.artifacts?.[0].url).toBe('https://example.com/chart.png');
      }
    });
  });
});

/**
 * Conversion Rules:
 *
 * SSE Event Type → TimelineEvent Type
 * ───────────────────────────────────
 * message (role: user) → user_message
 * message (role: assistant) → assistant_message
 * thought → thought
 * act → act
 * observe → observe
 * tool_result → observe (merged)
 * work_plan → work_plan
 * step_start → step_start
 * step_end → step_end
 * step_finish → step_end (merged)
 * complete → assistant_message
 * text_start → text_start (typewriter effect)
 * text_delta → text_delta (typewriter effect)
 * text_end → text_end (typewriter effect)
 *
 * Unsupported (return null):
 * - start, status, cost_update, retry, compact_needed
 * - doom_loop_detected, doom_loop_intervened
 * - clarification_asked, clarification_answered
 * - decision_asked, decision_answered
 * - permission_asked, permission_replied
 * - skill_*, pattern_match, context_compressed
 * - plan_mode_enter, plan_mode_exit, plan_*, title_generated
 * - thought_delta, error
 */
