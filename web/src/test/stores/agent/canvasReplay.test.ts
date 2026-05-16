import { beforeEach, describe, expect, it } from 'vitest';

import { replayCanvasEventsFromTimeline } from '../../../stores/agent/canvasReplay';
import { useCanvasStore } from '../../../stores/canvasStore';
import { useLayoutModeStore } from '../../../stores/layoutMode';
import {
  getA2UIContractMessages,
  getA2UIContractSnapshot,
} from '../../fixtures/a2uiContractFixtures';
import {
  getNativeBlockFixtureCase,
  serializeNativeBlockContent,
} from '../../fixtures/canvasNativeBlockFixtures';

describe('canvasReplay', () => {
  beforeEach(() => {
    useCanvasStore.getState().reset();
    useLayoutModeStore.getState().setMode('chat');
  });

  it('replays A2UI request ids onto reopened canvas tabs', () => {
    const content = [
      '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
    ].join('\n');

    replayCanvasEventsFromTimeline([
      {
        id: 'evt-1',
        type: 'canvas_updated',
        eventTimeUs: 1,
        eventCounter: 1,
        timestamp: 1,
        action: 'created',
        block_id: 'block-1',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content,
          metadata: {},
          version: 1,
        },
      } as any,
      {
        id: 'evt-2',
        type: 'a2ui_action_asked',
        eventTimeUs: 2,
        eventCounter: 2,
        timestamp: 2,
        block_id: 'block-1',
        request_id: 'hitl-req-1',
      } as any,
    ]);

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-1');
    expect(tab?.a2uiSurfaceId).toBe('surface-42');
    expect(tab?.a2uiHitlRequestId).toBe('hitl-req-1');
    expect(useLayoutModeStore.getState().mode).toBe('canvas');
  });

  it('buffers replayed request ids that appear before the canvas event', () => {
    const content = [
      '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
    ].join('\n');

    replayCanvasEventsFromTimeline([
      {
        id: 'evt-1',
        type: 'a2ui_action_asked',
        eventTimeUs: 1,
        eventCounter: 1,
        timestamp: 1,
        block_id: 'block-1',
        request_id: 'hitl-req-buffered',
      } as any,
      {
        id: 'evt-2',
        type: 'canvas_updated',
        eventTimeUs: 2,
        eventCounter: 2,
        timestamp: 2,
        action: 'created',
        block_id: 'block-1',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content,
          metadata: {},
          version: 1,
        },
      } as any,
    ]);

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-1');
    expect(tab?.a2uiHitlRequestId).toBe('hitl-req-buffered');
  });

  it('materializes incremental A2UI dataModel updates during replay', () => {
    const initialContent = [
      '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
    ].join('\n');
    const incrementalContent =
      '{"dataModelUpdate":{"surfaceId":"surface-42","path":"/","contents":[{"key":"stats","valueMap":[{"key":"count","valueNumber":2}]}]}}';

    replayCanvasEventsFromTimeline([
      {
        id: 'evt-1',
        type: 'canvas_updated',
        eventTimeUs: 1,
        eventCounter: 1,
        timestamp: 1,
        action: 'created',
        block_id: 'block-1',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content: initialContent,
          metadata: {},
          version: 1,
        },
      } as any,
      {
        id: 'evt-2',
        type: 'canvas_updated',
        eventTimeUs: 2,
        eventCounter: 2,
        timestamp: 2,
        action: 'updated',
        block_id: 'block-1',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content: incrementalContent,
          metadata: {},
          version: 2,
        },
      } as any,
    ]);

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-1');
    expect(tab?.a2uiSnapshot?.surfaceId).toBe('surface-42');
    expect(tab?.a2uiSnapshot?.data).toEqual({ stats: { count: 2 } });
  });

  it('replays the shared typed-envelope fixture into canonical snapshot state', () => {
    const content = getA2UIContractMessages('tier2_typed_envelopes');

    replayCanvasEventsFromTimeline([
      {
        id: 'evt-1',
        type: 'canvas_updated',
        eventTimeUs: 1,
        eventCounter: 1,
        timestamp: 1,
        action: 'created',
        block_id: 'block-typed',
        block: {
          id: 'block-typed',
          block_type: 'a2ui_surface',
          title: 'Typed Surface',
          content,
          metadata: {},
          version: 1,
        },
      } as any,
    ]);

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-typed');
    expect(tab?.a2uiSurfaceId).toBe('typed-surface');
    expect(tab?.a2uiSnapshot?.surfaceId).toBe('typed-surface');
    expect(tab?.a2uiSnapshot?.data).toEqual({ status: 'ok' });
    expect(useLayoutModeStore.getState().mode).toBe('canvas');
  });

  it('preserves historical snapshot fixtures without promoting them into canonical messages', () => {
    const snapshot = getA2UIContractSnapshot('tier3_historical_snapshot_object_components');

    useCanvasStore.getState().openTab({
      id: 'block-historical',
      type: 'a2ui-surface',
      title: 'Historical Surface',
      content: 'not-json',
      a2uiSurfaceId: 'surface-42',
      a2uiMessages: 'not-json',
      a2uiSnapshot: snapshot,
    });

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-historical');
    expect(tab?.a2uiSnapshot?.surfaceId).toBe('surface-42');
    expect(Array.isArray(tab?.a2uiSnapshot?.components)).toBe(false);
    expect(tab?.a2uiMessages).toBe('not-json');
  });

  it.each(['chart_top_level_datasets', 'widget_html_preview'])(
    'replays native canvas block contract case %s into the correct tab type',
    (caseId) => {
      const fixtureCase = getNativeBlockFixtureCase(caseId);
      const updatedContent = serializeNativeBlockContent(
        fixtureCase.updatedContent ?? fixtureCase.content
      );
      const updatedTitle = fixtureCase.updatedTitle ?? `${fixtureCase.title} Updated`;

      replayCanvasEventsFromTimeline([
        {
          id: `${caseId}-create`,
          type: 'canvas_updated',
          eventTimeUs: 1,
          eventCounter: 1,
          timestamp: 1,
          action: 'created',
          block_id: `block-${caseId}`,
          block: {
            id: `block-${caseId}`,
            block_type: fixtureCase.blockType,
            title: fixtureCase.title,
            content: serializeNativeBlockContent(fixtureCase.content),
            metadata: {},
            version: 1,
          },
        } as any,
        {
          id: `${caseId}-update`,
          type: 'canvas_updated',
          eventTimeUs: 2,
          eventCounter: 2,
          timestamp: 2,
          action: 'updated',
          block_id: `block-${caseId}`,
          block: {
            id: `block-${caseId}`,
            block_type: fixtureCase.blockType,
            title: updatedTitle,
            content: updatedContent,
            metadata: {},
            version: 2,
          },
        } as any,
      ]);

      const tab = useCanvasStore.getState().tabs.find((item) => item.id === `block-${caseId}`);
      expect(tab?.type).toBe(fixtureCase.expected.frontendTabType);
      expect(tab?.title).toBe(updatedTitle);
      expect(tab?.content).toBe(updatedContent);
      expect(useLayoutModeStore.getState().mode).toBe('canvas');
    }
  );

  it.each(['chart_top_level_datasets', 'widget_html_preview'])(
    'opens a native tab from replay when only an updated event exists for %s',
    (caseId) => {
      const fixtureCase = getNativeBlockFixtureCase(caseId);
      const updatedContent = serializeNativeBlockContent(
        fixtureCase.updatedContent ?? fixtureCase.content
      );
      const updatedTitle = fixtureCase.updatedTitle ?? `${fixtureCase.title} Updated`;

      replayCanvasEventsFromTimeline([
        {
          id: `${caseId}-update-only`,
          type: 'canvas_updated',
          eventTimeUs: 1,
          eventCounter: 1,
          timestamp: 1,
          action: 'updated',
          block_id: `block-${caseId}-update-only`,
          block: {
            id: `block-${caseId}-update-only`,
            block_type: fixtureCase.blockType,
            title: updatedTitle,
            content: updatedContent,
            metadata: {},
            version: 2,
          },
        } as any,
      ]);

      const tab = useCanvasStore
        .getState()
        .tabs.find((item) => item.id === `block-${caseId}-update-only`);
      expect(tab?.type).toBe(fixtureCase.expected.frontendTabType);
      expect(tab?.title).toBe(updatedTitle);
      expect(tab?.content).toBe(updatedContent);
      expect(useLayoutModeStore.getState().mode).toBe('canvas');
    }
  );
});
