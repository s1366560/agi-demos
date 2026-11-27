import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { InlineHITLCardProps } from "../web/hitl/InlineHITLCard";

export interface PendingRequest {
  id: string;
  request_type:
    | "decision"
    | "permission"
    | "clarification"
    | "a2ui_action"
    | "env_var";
  question: string;
  options: NonNullable<InlineHITLCardProps["decisionData"]>["options"];
  created_at: string;
  expires_at?: string;
  block_id?: string;
  authority_revision: number;
  tool_name?: string;
  description?: string;
  allow_custom?: boolean;
  risk_level?: "low" | "medium" | "high";
  selection_mode?: "single" | "multiple";
  max_selections?: number;
}
export interface InteractionEvent {
  id: string;
  /** Position of the event in the conversation timeline. */
  eventTimeUs?: number;
  eventCounter?: number;
  timestamp?: number;
  /**
   * Any event of the timeline. A tool call carries what it did, a canvas block its
   * content, a human-in-the-loop card or an error what it shows, and every other
   * event only keeps its place.
   */
  type: string;
  execution_id?: string;
  call_id?: string;
  message_id?: string;
  /** A request of the transcript carries its id and whether it was answered. */
  requestId?: string;
  answered?: boolean;
  /** Marks an argument draft of a call, which its execution replaces. */
  metadata?: { sourceEventType?: string };
  toolName?: string;
  toolInput?: unknown;
  toolOutput?: string;
  isError?: boolean;
  execution?: {
    startTime?: number;
    endTime?: number;
    duration?: number;
    status?: string;
  };
  action?: string;
  block_id?: string;
  block?: {
    id?: string;
    block_type?: string;
    title?: string;
    content?: string;
  };
  /** A file the agent produced. Its address is signed anew by the `artifact` view. */
  artifactId?: string;
  filename?: string;
  mimeType?: string;
  category?: string;
  sizeBytes?: number;
  url?: string;
  previewUrl?: string;
  sourceTool?: string;
  error?: string;
}
type View = { events: InteractionEvent[]; requests: PendingRequest[] };
const empty: View = { events: [], requests: [] };
/**
 * The page the original transcript reads, so a conversation starts with the same
 * history. Both commands read the same window: a turn keeps its steps with its messages.
 */
export const PAGE = 200;
export type Interactions = ReturnType<typeof useInteractions>;
export function useInteractions(
  conversation: string,
  active: boolean,
  enabled: boolean,
  reloaded = 0,
) {
  const [data, setData] = useState<{ id: string; view: View }>();
  const [earlier, setEarlier] = useState<{
    id: string;
    events: InteractionEvent[];
  }>();
  const [failure, setFailure] = useState("");
  const [refresh, setRefresh] = useState(0);
  const retryKeys = useRef(new Map<string, string>());
  useEffect(() => {
    if (!enabled || !conversation) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setFailure("");
    async function load() {
      try {
        const view = (await window.memstack.invoke(
          "chat-interactions",
          { conversation_id: conversation, limit: PAGE },
          { signal: controller.signal },
        )) as View;
        if (!controller.signal.aborted) setData({ id: conversation, view });
      } catch (cause) {
        if (!controller.signal.aborted) setFailure(String(cause));
      } finally {
        if (active && !controller.signal.aborted)
          timer = setTimeout(load, 1800);
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [conversation, active, enabled, refresh]);
  // The page read the first page again, so the events of earlier pages no longer
  // belong next to its messages.
  useEffect(() => setEarlier(undefined), [conversation, reloaded]);
  /** Read the events of an earlier page, so its tool steps stay with its messages. */
  const older = useCallback(
    async (before: { before_time_us: number; before_counter: number }) => {
      const view = (await window.memstack.invoke("chat-interactions", {
        conversation_id: conversation,
        limit: PAGE,
        ...before,
      })) as View;
      setEarlier((old) => {
        const merged = [
          ...view.events,
          ...(old?.id === conversation ? old.events : []),
        ];
        return {
          id: conversation,
          events: [
            ...new Map(merged.map((event) => [event.id, event])).values(),
          ],
        };
      });
    },
    [conversation],
  );
  const respond = useCallback(
    async (request: PendingRequest, response: Record<string, unknown>) => {
      const key = JSON.stringify([
        conversation,
        request.id,
        request.authority_revision,
        response,
      ]);
      const id = retryKeys.current.get(key) ?? crypto.randomUUID();
      retryKeys.current.set(key, id);
      await window.memstack.invoke("chat-respond", {
        conversation_id: conversation,
        request_id: request.id,
        hitl_type: request.request_type,
        expected_revision: request.authority_revision,
        idempotency_key: id,
        response_data: response,
      });
      retryKeys.current.delete(key);
      setRefresh((v) => v + 1);
    },
    [conversation],
  );
  const current = data?.id === conversation && enabled ? data.view : empty;
  const loaded = earlier?.id === conversation ? earlier.events : empty.events;
  const events = useMemo(
    () => (loaded.length ? [...loaded, ...current.events] : current.events),
    [loaded, current.events],
  );
  return {
    events,
    requests: current.requests,
    respond,
    older,
    /** Whether the events of the page are in, so the transcript can be measured. */
    ready: !enabled || data?.id === conversation,
    failure,
  };
}
