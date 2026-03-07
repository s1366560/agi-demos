import { describe, expect, it } from 'vitest';

import { mergeA2UIMessageStream } from '../../../stores/agent/a2uiMessages';

describe('mergeA2UIMessageStream', () => {
  it('appends incremental surfaceUpdate payloads to preserve previous beginRendering', () => {
    const previous =
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}\n' +
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}';
    const incoming =
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"world"}}}}]}}';

    const merged = mergeA2UIMessageStream(previous, incoming);

    expect(merged).toContain('"beginRendering"');
    expect(merged.split('\n')).toHaveLength(3);
  });

  it('replaces payload when incoming already contains beginRendering', () => {
    const previous = '{"surfaceUpdate":{"surfaceId":"s1","components":[]}}';
    const incoming = '{"beginRendering":{"surfaceId":"s1","root":"root-2"}}';

    const merged = mergeA2UIMessageStream(previous, incoming);

    expect(merged).toBe(incoming);
  });

  it('appends incremental dataModelUpdate payloads', () => {
    const previous =
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}\n' +
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}';
    const incoming = '{"dataModelUpdate":{"surfaceId":"s1","path":"/","contents":[{"count":2}]}}';

    const merged = mergeA2UIMessageStream(previous, incoming);

    expect(merged).toContain('"beginRendering"');
    expect(merged).toContain('"dataModelUpdate"');
    expect(merged.split('\n')).toHaveLength(3);
  });

  it('returns incoming payload when there is no previous message stream', () => {
    const incoming = '{"surfaceUpdate":{"surfaceId":"s1","components":[]}}';
    expect(mergeA2UIMessageStream(undefined, incoming)).toBe(incoming);
  });
});
