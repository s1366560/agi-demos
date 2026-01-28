/**
 * Tests for TimelineEventAdapter
 *
 * This module tests the adapter that converts TimelineEvents to renderable groups.
 * Ensures consistent behavior between streaming and historical message rendering.
 *
 * @see web/src/utils/timelineEventAdapter.ts
 */

import { describe, it, expect } from 'vitest';
import {
  groupTimelineEvents,
  extractExecutionData
} from '../../utils/timelineEventAdapter';
import type { TimelineEvent } from '../../types/agent';

describe('groupTimelineEvents', () => {
  it('should group user message with its associated events', () => {
    const events: TimelineEvent[] = [
      {
        id: 'user-1',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'What is the weather?',
        role: 'user'
      },
      {
        id: 'thought-1',
        type: 'thought',
        sequenceNumber: 2,
        timestamp: Date.now() + 100,
        content: 'I need to search for weather information'
      },
      {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 3,
        timestamp: Date.now() + 200,
        toolName: 'WebSearch',
        toolInput: { query: 'weather today' }
      }
    ];

    const groups = groupTimelineEvents(events);

    expect(groups).toHaveLength(2); // user group + assistant group
    expect(groups[0].type).toBe('user');
    expect(groups[0].content).toBe('What is the weather?');
    expect(groups[1].type).toBe('assistant');
    expect(groups[1].thoughts).toHaveLength(1);
    expect(groups[1].toolCalls).toHaveLength(1);
  });

  it('should group assistant message with its execution data', () => {
    const events: TimelineEvent[] = [
      {
        id: 'assistant-1',
        type: 'assistant_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'The weather is sunny',
        role: 'assistant'
      },
      {
        id: 'thought-1',
        type: 'thought',
        sequenceNumber: 2,
        timestamp: Date.now() + 100,
        content: 'Weather data retrieved'
      }
    ];

    const groups = groupTimelineEvents(events);

    expect(groups).toHaveLength(1);
    expect(groups[0].type).toBe('assistant');
    expect(groups[0].content).toBe('The weather is sunny');
    expect(groups[0].thoughts).toContain('Weather data retrieved');
  });

  it('should handle empty timeline', () => {
    const groups = groupTimelineEvents([]);
    expect(groups).toEqual([]);
  });

  it('should preserve sequence order', () => {
    const events: TimelineEvent[] = [
      {
        id: 'user-1',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: 1000,
        content: 'First',
        role: 'user'
      },
      {
        id: 'assistant-1',
        type: 'assistant_message',
        sequenceNumber: 2,
        timestamp: 2000,
        content: 'Response 1',
        role: 'assistant'
      },
      {
        id: 'user-2',
        type: 'user_message',
        sequenceNumber: 3,
        timestamp: 3000,
        content: 'Second',
        role: 'user'
      }
    ];

    const groups = groupTimelineEvents(events);

    expect(groups).toHaveLength(3);
    expect(groups[0].content).toBe('First');
    expect(groups[1].content).toBe('Response 1');
    expect(groups[2].content).toBe('Second');
  });

  it('should extract work plan events', () => {
    const events: TimelineEvent[] = [
      {
        id: 'plan-1',
        type: 'work_plan',
        sequenceNumber: 1,
        timestamp: Date.now(),
        steps: [
          { step_number: 1, description: 'Search weather', expected_output: 'Weather data' },
          { step_number: 2, description: 'Summarize', expected_output: 'Summary' }
        ],
        status: 'planning'
      }
    ];

    const groups = groupTimelineEvents(events);

    expect(groups).toHaveLength(1);
    expect(groups[0].workPlan).toBeDefined();
    expect(groups[0].workPlan?.steps).toHaveLength(2);
  });

  it('should extract step events and associate with work plan', () => {
    const events: TimelineEvent[] = [
      {
        id: 'plan-1',
        type: 'work_plan',
        sequenceNumber: 1,
        timestamp: Date.now(),
        steps: [{ step_number: 1, description: 'Step 1', expected_output: 'Output' }],
        status: 'in_progress'
      },
      {
        id: 'step-start-1',
        type: 'step_start',
        sequenceNumber: 2,
        timestamp: Date.now() + 100,
        stepIndex: 0,
        stepDescription: 'Step 1'
      }
    ];

    const groups = groupTimelineEvents(events);

    expect(groups[0].workPlan).toBeDefined();
    // The step should be associated with the work plan
    expect(groups[0].workPlan?.steps[0].description).toBe('Step 1');
  });
});

describe('extractExecutionData', () => {
  it('should extract tool calls from act events', () => {
    const events: TimelineEvent[] = [
      {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'MemorySearch',
        toolInput: { query: 'test' }
      },
      {
        id: 'observe-1',
        type: 'observe',
        sequenceNumber: 2,
        timestamp: Date.now() + 100,
        toolName: 'MemorySearch',
        toolOutput: 'Search results',
        isError: false
      }
    ];

    const data = extractExecutionData(events);

    expect(data.toolCalls).toHaveLength(1);
    expect(data.toolCalls[0].name).toBe('MemorySearch');
    expect(data.toolCalls[0].input).toEqual({ query: 'test' });
  });

  it('should extract thoughts from thought events', () => {
    const events: TimelineEvent[] = [
      {
        id: 'thought-1',
        type: 'thought',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'First thought'
      },
      {
        id: 'thought-2',
        type: 'thought',
        sequenceNumber: 2,
        timestamp: Date.now() + 100,
        content: 'Second thought'
      }
    ];

    const data = extractExecutionData(events);

    expect(data.thoughts).toEqual(['First thought', 'Second thought']);
  });

  it('should calculate duration from act and observe events', () => {
    const startTime = Date.now();
    const endTime = startTime + 500;

    const events: TimelineEvent[] = [
      {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: startTime,
        toolName: 'TestTool',
        toolInput: {}
      },
      {
        id: 'observe-1',
        type: 'observe',
        sequenceNumber: 2,
        timestamp: endTime,
        toolName: 'TestTool',
        toolOutput: 'Success',
        isError: false
      }
    ];

    const data = extractExecutionData(events);

    expect(data.toolCalls[0].duration).toBeGreaterThanOrEqual(450);
    expect(data.toolCalls[0].duration).toBeLessThanOrEqual(550);
  });

  it('should determine tool status from observe event', () => {
    const events: TimelineEvent[] = [
      {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'TestTool',
        toolInput: {}
      },
      {
        id: 'observe-error',
        type: 'observe',
        sequenceNumber: 2,
        timestamp: Date.now() + 100,
        toolName: 'TestTool',
        toolOutput: 'Error occurred',
        isError: true
      }
    ];

    const data = extractExecutionData(events);

    expect(data.toolCalls[0].status).toBe('error');
    expect(data.toolCalls[0].error).toBe('Error occurred');
  });

  it('should mark tool as running if no observe event', () => {
    const events: TimelineEvent[] = [
      {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'TestTool',
        toolInput: {}
      }
    ];

    const data = extractExecutionData(events);

    expect(data.toolCalls[0].status).toBe('running');
  });
});
