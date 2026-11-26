import { useEffect, useRef } from 'react';
import type { TimelineEvent } from '../../../../../web/src/types/agent';
import { replayCanvasEventsFromTimeline } from '../web/stores/agent/canvasReplay';
import type { InteractionEvent } from './useInteractions';

/**
 * Canvas blocks of a conversation open as tabs of the canvas, in the order they
 * happened. The replay is the one of the original workbench, which then shows
 * the canvas. An event is replayed once, until the page reads the history from
 * its start again.
 */
export function useCanvasBlocks(
  conversation: string,
  events: readonly InteractionEvent[]
) {
  const read = useRef({ conversation: '', first: '', ids: new Set<string>() });
  useEffect(() => {
    const first = events[0]?.id ?? '';
    if (read.current.conversation !== conversation || read.current.first !== first)
      read.current = { conversation, first, ids: new Set() };
    const { ids } = read.current;
    const fresh = events.filter(
      (event) => event.type === 'canvas_updated' && !ids.has(event.id)
    );
    if (!fresh.length) return;
    for (const event of fresh) ids.add(event.id);
    replayCanvasEventsFromTimeline(fresh as unknown as TimelineEvent[]);
  }, [conversation, events]);
}
