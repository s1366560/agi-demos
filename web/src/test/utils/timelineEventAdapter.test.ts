/**
 * TimelineEventAdapter Tests
 *
 * Tests the grouping and rendering logic for timeline events.
 * Critical for ensuring chat history renders correctly.
 *
 * @module utils/timelineEventAdapter.test
 */

import { describe, it, expect } from 'vitest';
import {
  groupTimelineEvents,
  extractExecutionData,
  findMatchingObserve,
  isMessageEvent,
  isExecutionEvent,
  type EventGroup,
  type TimelineEvent,
} from '../../utils/timelineEventAdapter';
import type { ActEvent, ObserveEvent, ThoughtEvent } from '../../types/agent';

describe('timelineEventAdapter', () => {
  describe('groupTimelineEvents', () => {
    it('should group user message as standalone group', () => {
      const events: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
      ];

      const groups = groupTimelineEvents(events);

      expect(groups).toHaveLength(1);
      expect(groups[0].type).toBe('user');
      expect(groups[0].content).toBe('Hello');
      expect(groups[0].thoughts).toHaveLength(0);
      expect(groups[0].toolCalls).toHaveLength(0);
    });

    it('should group thought events with assistant message', () => {
      const events: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'What is the weather?',
          role: 'user',
        },
        {
          id: 'thought-1',
          type: 'thought',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'I need to check the weather API',
        },
        {
          id: 'msg-2',
          type: 'assistant_message',
          sequenceNumber: 3,
          timestamp: Date.now(),
          content: 'The weather is sunny',
          role: 'assistant',
        },
      ];

      const groups = groupTimelineEvents(events);

      // Should have: user group + assistant group with thought
      expect(groups).toHaveLength(2);

      // First group: user message
      expect(groups[0].type).toBe('user');
      expect(groups[0].content).toBe('What is the weather?');

      // Second group: assistant message with thought
      expect(groups[1].type).toBe('assistant');
      expect(groups[1].thoughts).toHaveLength(1);
      expect(groups[1].thoughts[0]).toBe('I need to check the weather API');
      expect(groups[1].content).toBe('The weather is sunny');
    });

    it('should pair act and observe events correctly when observe has toolName', () => {
      const events: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Search for info',
          role: 'user',
        },
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'search',
          toolInput: { query: 'test' },
        },
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 3,
          timestamp: Date.now(),
          toolName: 'search', // Correct toolName
          toolOutput: 'Result: test data',
          isError: false,
        },
        {
          id: 'msg-2',
          type: 'assistant_message',
          sequenceNumber: 4,
          timestamp: Date.now(),
          content: 'Here is the result',
          role: 'assistant',
        },
      ];

      const groups = groupTimelineEvents(events);

      // Should have: user + assistant groups
      expect(groups).toHaveLength(2);

      // Assistant group should have tool call with success status
      expect(groups[1].toolCalls).toHaveLength(1);
      expect(groups[1].toolCalls[0].name).toBe('search');
      expect(groups[1].toolCalls[0].status).toBe('success');
      expect(groups[1].toolCalls[0].result).toBe('Result: test data');
    });

    it('should handle observe events with unknown toolName (SSE case)', () => {
      const events: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Search for info',
          role: 'user',
        },
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'search',
          toolInput: { query: 'test' },
        },
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 3,
          timestamp: Date.now(),
          toolName: 'unknown', // SSE events don't have toolName
          toolOutput: 'Result: test data',
          isError: false,
        },
      ];

      const groups = groupTimelineEvents(events);

      // Should still pair act/observe using order-based matching
      expect(groups[1].toolCalls).toHaveLength(1);
      expect(groups[1].toolCalls[0].name).toBe('search');
      expect(groups[1].toolCalls[0].status).toBe('success');
    });

    it('should handle multiple tool calls in sequence', () => {
      const events: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Do multiple searches',
          role: 'user',
        },
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'search',
          toolInput: { query: 'test1' },
        },
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 3,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'Result 1',
          isError: false,
        },
        {
          id: 'act-2',
          type: 'act',
          sequenceNumber: 4,
          timestamp: Date.now(),
          toolName: 'memory_search',
          toolInput: { query: 'test2' },
        },
        {
          id: 'obs-2',
          type: 'observe',
          sequenceNumber: 5,
          timestamp: Date.now(),
          toolName: 'memory_search',
          toolOutput: 'Result 2',
          isError: false,
        },
        {
          id: 'msg-2',
          type: 'assistant_message',
          sequenceNumber: 6,
          timestamp: Date.now(),
          content: 'Done',
          role: 'assistant',
        },
      ];

      const groups = groupTimelineEvents(events);

      expect(groups[1].toolCalls).toHaveLength(2);
      expect(groups[1].toolCalls[0].name).toBe('search');
      expect(groups[1].toolCalls[0].result).toBe('Result 1');
      expect(groups[1].toolCalls[1].name).toBe('memory_search');
      expect(groups[1].toolCalls[1].result).toBe('Result 2');
    });

    it('should create implicit assistant group for orphaned thought events', () => {
      const events: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
        {
          id: 'thought-1',
          type: 'thought',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'Thinking...',
        },
      ];

      const groups = groupTimelineEvents(events);

      // User group + implicit assistant group for thought
      expect(groups).toHaveLength(2);
      expect(groups[1].type).toBe('assistant');
      expect(groups[1].thoughts).toHaveLength(1);
      expect(groups[1].thoughts[0]).toBe('Thinking...');
    });

    it('should include work plan in assistant group', () => {
      const events: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Complex task',
          role: 'user',
        },
        {
          id: 'plan-1',
          type: 'work_plan',
          sequenceNumber: 2,
          timestamp: Date.now(),
          steps: [
            { step_number: 1, description: 'Step 1', expected_output: 'Output 1' },
            { step_number: 2, description: 'Step 2', expected_output: 'Output 2' },
          ],
          status: 'in_progress',
        },
        {
          id: 'msg-2',
          type: 'assistant_message',
          sequenceNumber: 3,
          timestamp: Date.now(),
          content: 'Working on it',
          role: 'assistant',
        },
      ];

      const groups = groupTimelineEvents(events);

      expect(groups[1].workPlan).toBeDefined();
      expect(groups[1].workPlan?.steps).toHaveLength(2);
      expect(groups[1].workPlan?.status).toBe('in_progress');
    });

    it('should correctly render the expected pattern: user -> thought -> act -> observe -> assistant', () => {
      const events: TimelineEvent[] = [
        // User message
        {
          id: 'user-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'What is the capital of France?',
          role: 'user',
        },
        // Thought
        {
          id: 'thought-1',
          type: 'thought',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'I need to search for information about France capital',
        },
        // Act
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 3,
          timestamp: Date.now(),
          toolName: 'web_search',
          toolInput: { query: 'capital of France' },
        },
        // Observe
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 4,
          timestamp: Date.now(),
          toolName: 'web_search',
          toolOutput: 'The capital of France is Paris',
          isError: false,
        },
        // Assistant summary
        {
          id: 'assistant-1',
          type: 'assistant_message',
          sequenceNumber: 5,
          timestamp: Date.now(),
          content: 'The capital of France is Paris.',
          role: 'assistant',
        },
      ];

      const groups = groupTimelineEvents(events);

      // Should render as: User group -> Assistant group (with thought + tool + content)
      expect(groups).toHaveLength(2);

      // User group
      expect(groups[0].type).toBe('user');
      expect(groups[0].content).toBe('What is the capital of France?');

      // Assistant group with all execution details
      expect(groups[1].type).toBe('assistant');
      expect(groups[1].thoughts).toHaveLength(1);
      expect(groups[1].thoughts[0]).toBe('I need to search for information about France capital');
      expect(groups[1].toolCalls).toHaveLength(1);
      expect(groups[1].toolCalls[0].name).toBe('web_search');
      expect(groups[1].toolCalls[0].result).toBe('The capital of France is Paris');
      expect(groups[1].content).toBe('The capital of France is Paris.');
    });

    it('should handle multiple conversation rounds', () => {
      const events: TimelineEvent[] = [
        // Round 1
        {
          id: 'user-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'First question',
          role: 'user',
        },
        {
          id: 'thought-1',
          type: 'thought',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'Thinking 1',
        },
        {
          id: 'assistant-1',
          type: 'assistant_message',
          sequenceNumber: 3,
          timestamp: Date.now(),
          content: 'Answer 1',
          role: 'assistant',
        },
        // Round 2
        {
          id: 'user-2',
          type: 'user_message',
          sequenceNumber: 4,
          timestamp: Date.now(),
          content: 'Second question',
          role: 'user',
        },
        {
          id: 'thought-2',
          type: 'thought',
          sequenceNumber: 5,
          timestamp: Date.now(),
          content: 'Thinking 2',
        },
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 6,
          timestamp: Date.now(),
          toolName: 'search',
          toolInput: { query: 'test' },
        },
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 7,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'Result',
          isError: false,
        },
        {
          id: 'assistant-2',
          type: 'assistant_message',
          sequenceNumber: 8,
          timestamp: Date.now(),
          content: 'Answer 2',
          role: 'assistant',
        },
      ];

      const groups = groupTimelineEvents(events);

      // Should have 4 groups: user1 -> assistant1 -> user2 -> assistant2
      expect(groups).toHaveLength(4);

      expect(groups[0].type).toBe('user');
      expect(groups[0].content).toBe('First question');

      expect(groups[1].type).toBe('assistant');
      expect(groups[1].thoughts).toHaveLength(1);
      expect(groups[1].thoughts[0]).toBe('Thinking 1');
      expect(groups[1].content).toBe('Answer 1');

      expect(groups[2].type).toBe('user');
      expect(groups[2].content).toBe('Second question');

      expect(groups[3].type).toBe('assistant');
      expect(groups[3].thoughts).toHaveLength(1);
      expect(groups[3].thoughts[0]).toBe('Thinking 2');
      expect(groups[3].toolCalls).toHaveLength(1);
      expect(groups[3].content).toBe('Answer 2');
    });
  });

  describe('extractExecutionData', () => {
    it('should extract thoughts from timeline', () => {
      const events: TimelineEvent[] = [
        {
          id: 'thought-1',
          type: 'thought',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Thought 1',
        },
        {
          id: 'thought-2',
          type: 'thought',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'Thought 2',
        },
      ];

      const data = extractExecutionData(events);

      expect(data.thoughts).toEqual(['Thought 1', 'Thought 2']);
    });

    it('should extract and pair tool calls', () => {
      const events: TimelineEvent[] = [
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 1,
          timestamp: Date.now() - 100,
          toolName: 'search',
          toolInput: { query: 'test' },
        },
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'Result',
          isError: false,
        },
      ];

      const data = extractExecutionData(events);

      expect(data.toolCalls).toHaveLength(1);
      expect(data.toolCalls[0].name).toBe('search');
      expect(data.toolCalls[0].status).toBe('success');
      expect(data.toolCalls[0].result).toBe('Result');
    });

    it('should mark tool as running if no observe event', () => {
      const events: TimelineEvent[] = [
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 1,
          timestamp: Date.now(),
          toolName: 'search',
          toolInput: { query: 'test' },
        },
      ];

      const data = extractExecutionData(events);

      expect(data.toolCalls).toHaveLength(1);
      expect(data.toolCalls[0].status).toBe('running');
    });

    it('should extract work plan', () => {
      const events: TimelineEvent[] = [
        {
          id: 'plan-1',
          type: 'work_plan',
          sequenceNumber: 1,
          timestamp: Date.now(),
          steps: [
            { step_number: 1, description: 'Step 1', expected_output: 'Output 1' },
          ],
          status: 'in_progress',
        },
      ];

      const data = extractExecutionData(events);

      expect(data.workPlan).toBeDefined();
      expect(data.workPlan?.steps).toHaveLength(1);
      expect(data.workPlan?.status).toBe('in_progress');
    });

    it('should indicate streaming when any tool is running', () => {
      const events: TimelineEvent[] = [
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 1,
          timestamp: Date.now(),
          toolName: 'search',
          toolInput: { query: 'test' },
        },
      ];

      const data = extractExecutionData(events);

      expect(data.isStreaming).toBe(true);
    });
  });

  describe('findMatchingObserve', () => {
    it('should find observe event after act event', () => {
      const actEvent: ActEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'search',
        toolInput: { query: 'test' },
      };

      const events: TimelineEvent[] = [
        actEvent,
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'Result',
          isError: false,
        },
      ];

      const matchingObserve = findMatchingObserve(actEvent, events);

      expect(matchingObserve).toBeDefined();
      expect(matchingObserve?.toolOutput).toBe('Result');
    });

    it('should return undefined when no matching observe exists', () => {
      const actEvent: ActEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'search',
        toolInput: { query: 'test' },
      };

      const events: TimelineEvent[] = [actEvent];

      const matchingObserve = findMatchingObserve(actEvent, events);

      expect(matchingObserve).toBeUndefined();
    });
  });

  describe('isMessageEvent', () => {
    it('should return true for user message', () => {
      const event: TimelineEvent = {
        id: 'msg-1',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Hello',
        role: 'user',
      };

      expect(isMessageEvent(event)).toBe(true);
    });

    it('should return true for assistant message', () => {
      const event: TimelineEvent = {
        id: 'msg-1',
        type: 'assistant_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Hello',
        role: 'assistant',
      };

      expect(isMessageEvent(event)).toBe(true);
    });

    it('should return false for execution events', () => {
      const event: TimelineEvent = {
        id: 'thought-1',
        type: 'thought',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Thinking',
      };

      expect(isMessageEvent(event)).toBe(false);
    });
  });

  describe('isExecutionEvent', () => {
    it('should return true for thought event', () => {
      const event: ThoughtEvent = {
        id: 'thought-1',
        type: 'thought',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Thinking',
      };

      expect(isExecutionEvent(event)).toBe(true);
    });

    it('should return true for act event', () => {
      const event: ActEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'search',
        toolInput: { query: 'test' },
      };

      expect(isExecutionEvent(event)).toBe(true);
    });

    it('should return true for observe event', () => {
      const event: ObserveEvent = {
        id: 'obs-1',
        type: 'observe',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'search',
        toolOutput: 'Result',
        isError: false,
      };

      expect(isExecutionEvent(event)).toBe(true);
    });

    it('should return false for message events', () => {
      const event: TimelineEvent = {
        id: 'msg-1',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Hello',
        role: 'user',
      };

      expect(isExecutionEvent(event)).toBe(false);
    });
  });

  describe('extractExecutionData edge cases', () => {
    it('should handle empty events array', () => {
      const data = extractExecutionData([]);

      expect(data.thoughts).toEqual([]);
      expect(data.toolCalls).toEqual([]);
      expect(data.workPlan).toBeUndefined();
      expect(data.isStreaming).toBe(false);
    });

    it('should handle unknown work plan status', () => {
      const events: TimelineEvent[] = [
        {
          id: 'plan-1',
          type: 'work_plan',
          sequenceNumber: 1,
          timestamp: Date.now(),
          steps: [{ step_number: 1, description: 'Step 1', expected_output: 'Output 1' }],
          status: 'unknown' as any, // Invalid status
        },
      ];

      const data = extractExecutionData(events);

      expect(data.workPlan?.status).toBe('in_progress'); // Should default to in_progress
    });

    it('should handle observe event with error', () => {
      const events: TimelineEvent[] = [
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 1,
          timestamp: Date.now() - 100,
          toolName: 'search',
          toolInput: { query: 'test' },
        },
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'Error occurred',
          isError: true,
        },
      ];

      const data = extractExecutionData(events);

      expect(data.toolCalls).toHaveLength(1);
      expect(data.toolCalls[0].status).toBe('error');
      expect(data.toolCalls[0].error).toBe('Error occurred');
      expect(data.toolCalls[0].result).toBeUndefined();
    });
  });

  describe('findMatchingObserve edge cases', () => {
    it('should stop at another act event', () => {
      const actEvent1: ActEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'search',
        toolInput: { query: 'test' },
      };

      const events: TimelineEvent[] = [
        actEvent1,
        {
          id: 'act-2',
          type: 'act',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'memory_search',
          toolInput: { query: 'test2' },
        },
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 3,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'Result',
          isError: false,
        },
      ];

      const matchingObserve = findMatchingObserve(actEvent1, events);

      // Should not find observe because another act event came in between
      expect(matchingObserve).toBeUndefined();
    });

    it('should stop at message event', () => {
      const actEvent: ActEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'search',
        toolInput: { query: 'test' },
      };

      const events: TimelineEvent[] = [
        actEvent,
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'New message',
          role: 'user',
        },
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 3,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'Result',
          isError: false,
        },
      ];

      const matchingObserve = findMatchingObserve(actEvent, events);

      // Should not find observe because message event came in between
      expect(matchingObserve).toBeUndefined();
    });

    it('should match observe with different toolName after act', () => {
      const actEvent: ActEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'search',
        toolInput: { query: 'test' },
      };

      const events: TimelineEvent[] = [
        actEvent,
        {
          id: 'obs-1',
          type: 'observe',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'different_tool', // Different tool name
          toolOutput: 'Result',
          isError: false,
        },
      ];

      const matchingObserve = findMatchingObserve(actEvent, events);

      // Should not match because tool names differ
      expect(matchingObserve).toBeUndefined();
    });
  });
});
