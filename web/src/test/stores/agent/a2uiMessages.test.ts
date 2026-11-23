import { describe, expect, it } from 'vitest';

import {
  buildA2UIMessageStreamSnapshot,
  extractA2UISurfaceId,
  mergeA2UIMessageStream,
  mergeA2UIMessageStreamWithSnapshot,
} from '@business/agent/ui/web/stores/agent/a2uiMessages';
import { getA2UIContractCase, getA2UIContractMessages } from '../../fixtures/a2uiContractFixtures';

describe('mergeA2UIMessageStream', () => {
  it('rebuilds a merged surface snapshot for incremental surfaceUpdate payloads', () => {
    const previous =
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}\n' +
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}';
    const incoming =
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"world"}}}}]}}';

    const merged = mergeA2UIMessageStream(previous, incoming);

    expect(merged).toContain('"beginRendering"');
    expect(merged.split('\n')).toHaveLength(2);
    expect(merged).toContain('"world"');
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

  it('reuses the structured snapshot when merging incremental updates', () => {
    const previous =
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}\n' +
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}';
    const incoming =
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"world"}}}}]}}';
    const previousSnapshot = buildA2UIMessageStreamSnapshot(previous);

    const merged = mergeA2UIMessageStreamWithSnapshot(previousSnapshot, previous, incoming);

    expect(merged.messages).toContain('"world"');
    expect(merged.snapshot?.surfaceId).toBe('s1');
    expect(merged.snapshot?.components).toHaveLength(1);
  });

  it('materializes merged data into the structured snapshot', () => {
    const previous =
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}\n' +
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}';
    const incoming =
      '{"dataModelUpdate":{"surfaceId":"s1","path":"/","contents":[{"key":"stats","valueMap":[{"key":"count","valueNumber":2}]}]}}';
    const previousSnapshot = buildA2UIMessageStreamSnapshot(previous);

    const merged = mergeA2UIMessageStreamWithSnapshot(previousSnapshot, previous, incoming);

    expect(merged.snapshot?.data).toEqual({ stats: { count: 2 } });
  });

  it('preserves prior components when incremental updates switch array and object shapes', () => {
    const previous = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"root"}}}},{"id":"child-1","component":{"Text":{"text":{"literal":"child"}}}}]}}',
    ].join('\n');
    const incoming = JSON.stringify({
      surfaceUpdate: {
        surfaceId: 's1',
        components: {
          slot: {
            id: 'child-1',
            component: {
              Text: {
                text: { literal: 'updated child' },
              },
            },
          },
        },
      },
    });
    const previousSnapshot = buildA2UIMessageStreamSnapshot(previous);

    const merged = mergeA2UIMessageStreamWithSnapshot(previousSnapshot, previous, incoming);

    expect(Array.isArray(merged.snapshot?.components)).toBe(false);
    const components = merged.snapshot?.components as Record<
      string,
      { id: string; component: { Text?: { text?: { literalString?: string } } } }
    >;
    expect(Object.values(components).map((component) => component.id)).toEqual(
      expect.arrayContaining(['root-1', 'child-1'])
    );
    const updatedChild = Object.values(components).find((component) => component.id === 'child-1');
    expect(updatedChild?.component.Text?.text?.literalString).toBe('updated child');
  });

  it('ignores unsafe object-shaped component keys when building snapshots', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":{"__proto__":{"id":"poison","component":{"Text":{"text":{"literal":"bad"}}}},"root":{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}}}}',
    ].join('\n');

    const snapshot = buildA2UIMessageStreamSnapshot(messages);

    expect(snapshot).toBeDefined();
    expect(Array.isArray(snapshot?.components)).toBe(false);
    const components = snapshot?.components as Record<string, { id: string }>;
    expect(Object.keys(components)).toEqual(['root']);
    expect(Object.prototype.hasOwnProperty.call(components, '__proto__')).toBe(false);
    expect(components.root.id).toBe('root-1');
  });

  it('returns incoming payload when there is no previous message stream', () => {
    const incoming = '{"surfaceUpdate":{"surfaceId":"s1","components":[]}}';
    expect(mergeA2UIMessageStream(undefined, incoming)).toBe(incoming);
  });

  it('treats deleteSurface payloads as a full reset', () => {
    const previous =
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}\n' +
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}';
    const incoming = '{"deleteSurface":{"surfaceId":"s1"}}';

    const merged = mergeA2UIMessageStream(previous, incoming);

    expect(merged).toBe(incoming);
  });

  it('treats incremental surfaceId drift as a canonicalized full replacement', () => {
    const previous =
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}\n' +
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}';
    const incoming =
      '{"surfaceUpdate":{"surfaceId":"s2","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"world"}}}}]}}';

    expect(mergeA2UIMessageStream(previous, incoming)).toContain('"literalString":"world"');
  });

  it('extracts a single surface id from the message stream', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-1","components":[]}}',
    ].join('\n');

    expect(extractA2UISurfaceId(messages)).toBe('surface-1');
  });

  it('returns undefined when the message stream mixes multiple surface ids', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
      '{"beginRendering":{"surfaceId":"surface-2","root":"root-2"}}',
    ].join('\n');

    expect(extractA2UISurfaceId(messages)).toBeUndefined();
  });

  it('ignores nested non-envelope surfaceId fields', () => {
    const messages = JSON.stringify({
      surfaceUpdate: {
        surfaceId: 'real-surface',
        components: [
          {
            id: 'btn-1',
            component: {
              Button: {
                child: 'label-1',
                action: {
                  name: 'submit',
                  context: {
                    surfaceId: 'domain-object-id',
                  },
                },
              },
            },
          },
        ],
      },
    });

    expect(extractA2UISurfaceId(messages)).toBe('real-surface');
  });

  it('supports pretty-printed multi-line JSON objects', () => {
    const messages = `
{
  "beginRendering": {
    "surfaceId": "surface-1",
    "root": "root-1"
  }
}
{
  "surfaceUpdate": {
    "surfaceId": "surface-1",
    "components": []
  }
}
`;

    expect(extractA2UISurfaceId(messages)).toBe('surface-1');
  });

  it('extracts a surface id from compound envelope records', () => {
    const messages = JSON.stringify({
      beginRendering: {
        surfaceId: 'surface-1',
        root: 'root-1',
      },
      surfaceUpdate: {
        surfaceId: 'surface-1',
        components: [
          {
            id: 'root-1',
            component: {
              CheckBox: {
                label: { literalString: 'Enable alerts' },
                value: { literalBoolean: false, path: '/form/enabled' },
              },
            },
          },
        ],
        dataModelUpdate: {
          surfaceId: 'surface-1',
          path: '/',
          contents: [{ form: { enabled: false } }],
        },
      },
    });

    expect(extractA2UISurfaceId(messages)).toBe('surface-1');
    expect(buildA2UIMessageStreamSnapshot(messages)).toMatchObject({
      surfaceId: 'surface-1',
      root: 'root-1',
      data: { form: { enabled: false } },
    });
  });

  it('parses JSON-like payloads with Python boolean literals', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"root-1","component":{"CheckBox":{"label":{"literalString":"Enable alerts"},"value":{"literalBoolean":False,"path":"/form/enabled"}}}}]}}',
    ].join('\n');

    expect(extractA2UISurfaceId(messages)).toBe('surface-1');
    expect(buildA2UIMessageStreamSnapshot(messages)).toMatchObject({
      surfaceId: 'surface-1',
      root: 'root-1',
    });
    expect(mergeA2UIMessageStream(undefined, messages)).toContain('"literalBoolean":false');
  });

  it('returns undefined for malformed chunked payloads', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-1","components":[',
    ].join('\n');

    expect(extractA2UISurfaceId(messages)).toBeUndefined();
  });

  it('extracts and snapshots the shared typed-envelope contract fixture', () => {
    const contractCase = getA2UIContractCase('tier2_typed_envelopes');
    const messages = getA2UIContractMessages(contractCase.id);

    const snapshot = buildA2UIMessageStreamSnapshot(messages);

    expect(extractA2UISurfaceId(messages)).toBe(contractCase.identity?.surfaceId);
    expect(snapshot).toMatchObject({
      surfaceId: contractCase.identity?.surfaceId,
      root: 'root-1',
      data: { status: 'ok' },
    });
    expect(Array.isArray(snapshot?.components)).toBe(true);
    expect(snapshot?.components).toEqual([
      expect.objectContaining({
        id: 'root-1',
      }),
    ]);
  });

  it('merges typed incremental envelope fixtures into the canonical stream state', () => {
    const canonicalCase = getA2UIContractCase('tier1_typed_canonical');
    const typedCase = getA2UIContractCase('tier2_typed_envelopes');
    const previousMessages =
      canonicalCase.records
        ?.slice(0, 2)
        .map((record) => JSON.stringify(record))
        .join('\n') ?? '';
    const incomingMessages = JSON.stringify(typedCase.records?.[2]);
    const previousSnapshot = buildA2UIMessageStreamSnapshot(previousMessages);

    const merged = mergeA2UIMessageStreamWithSnapshot(
      previousSnapshot,
      previousMessages,
      incomingMessages
    );

    expect(merged.messages).toContain('"beginRendering"');
    expect(merged.messages).toContain('"surfaceUpdate"');
    expect(merged.messages).toContain('"dataModelUpdate"');
    expect(merged.messages).not.toContain('"data_model_update"');
    expect(merged.snapshot?.surfaceId).toBe('typed-surface');
    expect(merged.snapshot?.data).toEqual({ status: 'ok' });
  });

  it('builds the same replay snapshot for accepted+canonicalized typed envelopes as canonical messages', () => {
    const typedMessages = getA2UIContractMessages('tier2_typed_envelopes');
    const canonicalMessages = getA2UIContractMessages('tier1_typed_canonical');

    const typedSnapshot = buildA2UIMessageStreamSnapshot(typedMessages);
    const canonicalSnapshot = buildA2UIMessageStreamSnapshot(canonicalMessages);

    expect(typedSnapshot).toEqual(canonicalSnapshot);
  });

  it('serializes accepted+canonicalized typed updates back to the canonical message stream', () => {
    const canonicalMessages = getA2UIContractMessages('tier1_typed_canonical');
    const typedCase = getA2UIContractCase('tier2_typed_envelopes');
    const previousMessages = canonicalMessages.split('\n').slice(0, 2).join('\n');
    const previousSnapshot = buildA2UIMessageStreamSnapshot(previousMessages);

    const merged = mergeA2UIMessageStreamWithSnapshot(
      previousSnapshot,
      previousMessages,
      JSON.stringify(typedCase.records?.[2])
    );

    expect(merged.snapshot).toEqual(buildA2UIMessageStreamSnapshot(canonicalMessages));
    expect(merged.messages.split('\n').map((record) => JSON.parse(record))).toEqual(
      canonicalMessages.split('\n').map((record) => JSON.parse(record))
    );
  });

  it('materializes repeated canonical dataModelUpdate fixtures into a stable replay snapshot', () => {
    const messages = getA2UIContractMessages('tier1_repeated_data_model_updates');

    const snapshot = buildA2UIMessageStreamSnapshot(messages);

    expect(snapshot?.surfaceId).toBe('multi-update-surface');
    expect(snapshot?.root).toBe('status-text');
    expect(snapshot?.data).toEqual({
      status: 'queued',
      progress: { current: 2 },
    });
  });

  it('canonicalizes tier2 legacy alias fixtures before snapshot persistence', () => {
    const messages = getA2UIContractMessages('tier2_legacy_aliases');

    const snapshot = buildA2UIMessageStreamSnapshot(messages);
    const merged = mergeA2UIMessageStream(undefined, messages);

    expect(snapshot).toBeDefined();
    expect(merged).toContain('"CheckBox"');
    expect(merged).toContain('"MultipleChoice"');
    expect(merged).toContain('"literalString":"Email updates"');
    expect(merged).toContain('"literalString":"Priority"');
    expect(merged).not.toContain('"Checkbox"');
    expect(merged).not.toContain('"Select"');
    expect(merged).not.toContain('"literal":"Email updates"');
  });
});
