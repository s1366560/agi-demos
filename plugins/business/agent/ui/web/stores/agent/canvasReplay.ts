/**
 * Canvas event replay utility.
 *
 * Extracts the canvas-tab-creation logic used by the SSE `onCanvasUpdated`
 * handler into a pure function so it can also be called when replaying
 * persisted `canvas_updated` events from the conversation timeline.
 */

import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';

import {
  buildA2UIMessageStreamSnapshot,
  extractA2UISurfaceId,
  mergeA2UIMessageStreamWithSnapshot,
} from './a2uiMessages';

import type { CanvasUpdatedTimelineEvent, TimelineEvent } from '@/types/agent';
import type { CanvasContentType } from '@/stores/canvasStore';

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

    const a2uiSnapshot =
      tabType === 'a2ui-surface' ? buildA2UIMessageStreamSnapshot(block.content) : undefined;
    const derivedSurfaceId = a2uiSnapshot?.surfaceId ?? extractA2UISurfaceId(block.content);
    const metadataSurfaceId =
      typeof block.metadata?.surface_id === 'string' && block.metadata.surface_id.length > 0
        ? block.metadata.surface_id
        : undefined;
    const metadataHitlRequestId =
      typeof block.metadata?.hitl_request_id === 'string' &&
      block.metadata.hitl_request_id.length > 0
        ? block.metadata.hitl_request_id
        : undefined;
    canvasStore.openTab({
      id: block.id,
      title: block.title,
      type: tabType,
      content: block.content,
      language: block.metadata?.language as string | undefined,
      mimeType: block.metadata?.mime_type as string | undefined,
      ...(tabType === 'a2ui-surface'
        ? {
            a2uiSurfaceId: metadataSurfaceId ?? derivedSurfaceId ?? block.id,
            a2uiHitlRequestId: metadataHitlRequestId,
            a2uiMessages: block.content,
            a2uiSnapshot,
          }
        : {}),
    });
  } else if (action === 'updated' && block) {
    const existingTab = canvasStore.tabs.find((t) => t.id === blockId);
    if (existingTab) {
      if (existingTab.type === 'a2ui-surface') {
        const mergedA2UI = mergeA2UIMessageStreamWithSnapshot(
          existingTab.a2uiSnapshot,
          existingTab.a2uiMessages ?? existingTab.content,
          block.content
        );
        const derivedSurfaceId =
          mergedA2UI.snapshot?.surfaceId ?? extractA2UISurfaceId(mergedA2UI.messages);
        const metadataSurfaceId =
          typeof block.metadata?.surface_id === 'string' && block.metadata.surface_id.length > 0
            ? block.metadata.surface_id
            : undefined;
        const hasHitlRequestId =
          block.metadata !== undefined &&
          Object.prototype.hasOwnProperty.call(block.metadata, 'hitl_request_id');
        const metadataHitlRequestId =
          typeof block.metadata?.hitl_request_id === 'string' &&
          block.metadata.hitl_request_id.length > 0
            ? block.metadata.hitl_request_id
            : undefined;
        canvasStore.updateContent(blockId, mergedA2UI.messages);
        canvasStore.updateTab(blockId, {
          a2uiMessages: mergedA2UI.messages,
          a2uiSnapshot: mergedA2UI.snapshot,
          a2uiSurfaceId:
            metadataSurfaceId ?? derivedSurfaceId ?? existingTab.a2uiSurfaceId ?? block.id,
          ...(hasHitlRequestId ? { a2uiHitlRequestId: metadataHitlRequestId } : {}),
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
      const a2uiSnapshot =
        fallbackTabType === 'a2ui-surface'
          ? buildA2UIMessageStreamSnapshot(block.content)
          : undefined;
      const derivedSurfaceId = a2uiSnapshot?.surfaceId ?? extractA2UISurfaceId(block.content);
      const metadataSurfaceId =
        typeof block.metadata?.surface_id === 'string' && block.metadata.surface_id.length > 0
          ? block.metadata.surface_id
          : undefined;
      const metadataHitlRequestId =
        typeof block.metadata?.hitl_request_id === 'string' &&
        block.metadata.hitl_request_id.length > 0
          ? block.metadata.hitl_request_id
          : undefined;
      canvasStore.openTab({
        id: block.id,
        title: block.title,
        type: fallbackTabType,
        content: block.content,
        language: block.metadata?.language as string | undefined,
        mimeType: block.metadata?.mime_type as string | undefined,
        ...(fallbackTabType === 'a2ui-surface'
          ? {
              a2uiSurfaceId: metadataSurfaceId ?? derivedSurfaceId ?? block.id,
              a2uiHitlRequestId: metadataHitlRequestId,
              a2uiMessages: block.content,
              a2uiSnapshot,
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
  let replayedCanvas = false;
  const pendingRequestIds = new Map<string, string>();
  for (const event of timeline) {
    if (event.type === 'canvas_updated') {
      const canvasEvent = event;
      replayCanvasEvent(canvasEvent);
      const pendingRequestId = pendingRequestIds.get(canvasEvent.block_id);
      if (pendingRequestId) {
        useCanvasStore.getState().updateTab(canvasEvent.block_id, {
          a2uiHitlRequestId: pendingRequestId,
        });
        pendingRequestIds.delete(canvasEvent.block_id);
      }
      replayedCanvas = true;
      continue;
    }

    if (event.type !== 'a2ui_action_asked') continue;
    const requestId =
      typeof (event as { request_id?: unknown }).request_id === 'string'
        ? (event as { request_id: string }).request_id || undefined
        : undefined;
    const blockId =
      typeof (event as { block_id?: unknown }).block_id === 'string'
        ? (event as { block_id: string }).block_id || undefined
        : undefined;
    if (!requestId || !blockId) continue;
    pendingRequestIds.set(blockId, requestId);
    useCanvasStore.getState().updateTab(blockId, { a2uiHitlRequestId: requestId });
  }

  // If canvas tabs exist after replay, switch layout to canvas
  const canvasStore = useCanvasStore.getState();
  if (!replayedCanvas && canvasStore.tabs.length === 0) return;
  const layoutStore = useLayoutModeStore.getState();
  if (canvasStore.tabs.length > 0 && layoutStore.mode !== 'canvas') {
    layoutStore.setMode('canvas');
  }
}
