import { describe, expect, it } from 'vitest';

import {
  estimateGroupedItemHeight,
  estimateMarkdownHeight,
} from '../../../../components/agent/message/heightEstimation';

describe('heightEstimation', () => {
  it('estimates text_end rows from fullText instead of the default row height', () => {
    const fullText = Array.from(
      { length: 30 },
      (_, index) => `Line ${String(index)} with enough content to wrap in the assistant bubble.`
    ).join('\n');

    const estimatedHeight = estimateGroupedItemHeight({
      kind: 'event',
      index: 0,
      event: {
        id: 'text-end-1',
        type: 'text_end',
        fullText,
        timestamp: Date.now(),
      },
    } as any);

    expect(estimatedHeight).toBe(estimateMarkdownHeight(fullText));
    expect(estimatedHeight).toBeGreaterThan(80);
  });
});
