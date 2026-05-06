import { describe, expect, it } from 'vitest';

import {
  DEFAULT_LANE_CONTRACT,
  evaluateArtifactGate,
  formatArtifactLabel,
} from '@/utils/artifactGate';

describe('evaluateArtifactGate', () => {
  it('returns canAdvance=true with no nextColumn when in terminal lane', () => {
    const evalResult = evaluateArtifactGate(DEFAULT_LANE_CONTRACT, 'done', {
      total: 0,
      byType: {},
    });
    expect(evalResult.nextColumn).toBeNull();
    expect(evalResult.canAdvance).toBe(true);
  });

  it('blocks dev → review when test_results + commit missing', () => {
    const evalResult = evaluateArtifactGate(DEFAULT_LANE_CONTRACT, 'dev', {
      total: 1,
      byType: { code_diff: 1 },
    });
    expect(evalResult.canAdvance).toBe(false);
    expect(evalResult.missing).toEqual(['test_results', 'commit']);
    expect(evalResult.nextColumn?.id).toBe('review');
  });

  it('allows dev → review when all required present', () => {
    const evalResult = evaluateArtifactGate(DEFAULT_LANE_CONTRACT, 'dev', {
      total: 3,
      byType: { code_diff: 1, test_results: 2, commit: 1 },
    });
    expect(evalResult.canAdvance).toBe(true);
    expect(evalResult.missing).toEqual([]);
  });

  it('allows backlog → todo with no requirements', () => {
    const evalResult = evaluateArtifactGate(DEFAULT_LANE_CONTRACT, 'backlog', {
      total: 0,
      byType: {},
    });
    expect(evalResult.canAdvance).toBe(true);
    expect(evalResult.requiredArtifacts).toEqual([]);
  });

  it('handles unknown column gracefully', () => {
    const evalResult = evaluateArtifactGate(DEFAULT_LANE_CONTRACT, 'no-such-column', {
      total: 0,
      byType: {},
    });
    expect(evalResult.currentColumn).toBeNull();
    expect(evalResult.nextColumn).toBeNull();
    expect(evalResult.canAdvance).toBe(true);
  });
});

describe('formatArtifactLabel', () => {
  it('returns human label for known kinds', () => {
    expect(formatArtifactLabel('test_results')).toBe('Test Results');
    expect(formatArtifactLabel('code_diff')).toBe('Code Diff');
  });

  it('falls back to raw key for unknown kinds', () => {
    expect(formatArtifactLabel('custom_thing')).toBe('custom_thing');
  });
});
