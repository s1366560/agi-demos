/**
 * Canvas event replay utility.
 *
 * Extracts the canvas-tab-creation logic used by the SSE `onCanvasUpdated`
 * handler into a pure function so it can also be called when replaying
 * persisted `canvas_updated` events from the conversation timeline.
 */


import { useCanvasStore } from '../canvasStore';
import { useLayoutModeStore } from '../layoutMode';

import { mergeA2UIMessageStream } from './a2uiMessages';

import type { CanvasUpdatedTimelineEvent, TimelineEvent } from '../../types/agent';
import type { CanvasContentType } from '../canvasStore';

// Backend block_type -> frontend CanvasContentType
const BLOCK_TYPE_MAP: Record<string, CanvasContentType> = {
  code: 'code',
  markdown: 'markdown',
  image: 'preview',
  table: 'data',
  chart: 'data',
  form: 'data',
  widget: 'preview',
  a2ui_surface: 'a2ui-surface',
};

/**
 * Replay a single `canvas_updated` timeline event into canvasStore.
 *
 * This mirrors the logic inside `onCanvasUpdated` in streamEventHandlers.ts
 * but operates on a raw `TimelineEvent` from the messages API rather than
 * an SSE `AgentEvent` wrapper.
 */
function replayCanvasEvent(event: CanvasUpdatedTimelineEvent): void {
  const { action, block_id: blockId, block } = event;

  if (!action) return;

  const canvasStore = useCanvasStore.getState();

  if (action === 'created' && block) {
    const tabType = BLOCK_TYPE_MAP[block.block_type] ?? 'code';

    canvasStore.openTab({
      id: block.id,
      title: block.title,
      type: tabType,
      content: block.content,
      language: block.metadata?.language as string | undefined,
      mimeType: block.metadata?.mime_type as string | undefined,
      ...(tabType === 'a2ui-surface'
        ? {
            a2uiSurfaceId:
              typeof block.metadata?.surface_id === 'string' ? block.metadata.surface_id : block.id,
            a2uiMessages: block.content,
          }
        : {}),
    });
  } else if (action === 'updated' && block) {
    const existingTab = canvasStore.tabs.find((t) => t.id === blockId);
    if (existingTab) {
      if (existingTab.type === 'a2ui-surface') {
        const mergedA2UI = mergeA2UIMessageStream(
          existingTab.a2uiMessages ?? existingTab.content,
          block.content,
        );
        canvasStore.updateContent(blockId, mergedA2UI);
        canvasStore.updateTab(blockId, {
          a2uiMessages: mergedA2UI,
          a2uiSurfaceId:
            (typeof block.metadata?.surface_id === 'string' ? block.metadata.surface_id : undefined) ??
            existingTab.a2uiSurfaceId ??
            block.id,
        });
      } else {
        canvasStore.updateContent(blockId, block.content);
      }
      if (existingTab.title !== block.title) {
        canvasStore.updateTab(blockId, { title: block.title });
      }
    } else {
      // Tab not open yet -- open it
      const fallbackTabType = BLOCK_TYPE_MAP[block.block_type] ?? 'code';
      canvasStore.openTab({
        id: block.id,
        title: block.title,
        type: fallbackTabType,
        content: block.content,
        language: block.metadata?.language as string | undefined,
        mimeType: block.metadata?.mime_type as string | undefined,
        ...(fallbackTabType === 'a2ui-surface'
          ? {
              a2uiSurfaceId:
                typeof block.metadata?.surface_id === 'string'
                  ? block.metadata.surface_id
                  : block.id,
              a2uiMessages: block.content,
            }
          : {}),
      });
    }
  } else if (action === 'deleted') {
    canvasStore.closeTab(blockId, true);
  }
}

/**
 * Replay all `canvas_updated` events from a loaded conversation timeline.
 *
 * Call this after `loadMessages` finishes to rebuild the canvas state from
 * server-persisted events.  Events are replayed in timeline order so that
 * create → update → delete sequences resolve correctly.
 *
 * After replaying, if any canvas tabs were opened the layout is switched to
 * canvas mode automatically.
 */
export function replayCanvasEventsFromTimeline(timeline: readonly TimelineEvent[]): void {
  const canvasEvents = timeline.filter(
    (e): e is CanvasUpdatedTimelineEvent => e.type === 'canvas_updated',
  );
  if (canvasEvents.length === 0) return;

  for (const event of canvasEvents) {
    replayCanvasEvent(event);
  }

  // If canvas tabs exist after replay, switch layout to canvas
  const canvasStore = useCanvasStore.getState();
  const layoutStore = useLayoutModeStore.getState();
  if (canvasStore.tabs.length > 0 && layoutStore.mode !== 'canvas') {
    layoutStore.setMode('canvas');
  }
}
