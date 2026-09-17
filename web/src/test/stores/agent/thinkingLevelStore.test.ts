/**
 * Unit tests for thinkingLevelStore.
 *
 * Feature: per-conversation thinking level (reasoning effort) surfaced in the
 * composer toolbar and mirrored into llm_overrides.reasoning_effort.
 */

import { describe, it, expect, beforeEach } from 'vitest';

import {
  isAgentThinkingLevel,
  thinkingLevelToEffort,
  useAgentThinkingLevelStore,
} from '../../../stores/agent/thinkingLevelStore';

describe('thinkingLevelStore', () => {
  beforeEach(() => {
    useAgentThinkingLevelStore.setState({ levelsByConversation: {} });
  });

  describe('Level state', () => {
    it('should default to default for unknown conversations', () => {
      expect(useAgentThinkingLevelStore.getState().getThinkingLevel('conv-1')).toBe('default');
    });

    it('should persist a level per conversation', () => {
      useAgentThinkingLevelStore.getState().setThinkingLevel('conv-1', 'high');
      useAgentThinkingLevelStore.getState().setThinkingLevel('conv-2', 'low');

      expect(useAgentThinkingLevelStore.getState().getThinkingLevel('conv-1')).toBe('high');
      expect(useAgentThinkingLevelStore.getState().getThinkingLevel('conv-2')).toBe('low');
      expect(useAgentThinkingLevelStore.getState().getThinkingLevel('conv-3')).toBe('default');
    });

    it('should clear a conversation level without touching others', () => {
      useAgentThinkingLevelStore.getState().setThinkingLevel('conv-1', 'medium');
      useAgentThinkingLevelStore.getState().setThinkingLevel('conv-2', 'high');

      useAgentThinkingLevelStore.getState().clearConversation('conv-1');

      expect(useAgentThinkingLevelStore.getState().getThinkingLevel('conv-1')).toBe('default');
      expect(useAgentThinkingLevelStore.getState().getThinkingLevel('conv-2')).toBe('high');
    });
  });

  describe('thinkingLevelToEffort', () => {
    it('should map default to undefined (no override)', () => {
      expect(thinkingLevelToEffort('default')).toBeUndefined();
    });

    it('should map explicit levels to their effort value', () => {
      expect(thinkingLevelToEffort('low')).toBe('low');
      expect(thinkingLevelToEffort('medium')).toBe('medium');
      expect(thinkingLevelToEffort('high')).toBe('high');
    });
  });

  describe('isAgentThinkingLevel', () => {
    it('should accept known levels and reject anything else', () => {
      expect(isAgentThinkingLevel('low')).toBe(true);
      expect(isAgentThinkingLevel('ultra')).toBe(false);
      expect(isAgentThinkingLevel(42)).toBe(false);
    });
  });
});
